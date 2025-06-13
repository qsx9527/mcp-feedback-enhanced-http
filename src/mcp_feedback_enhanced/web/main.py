#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web UI 主要管理器
================

基於 FastAPI 的 Web 用戶介面主要管理類，參考 GUI 的設計模式重構。
專為 SSH 遠端開發環境設計，支援現代化界面和多語言。
"""

import asyncio
import json
import logging
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

from .models import WebFeedbackSession, FeedbackResult, CleanupReason, SessionStatus
from .routes import setup_routes
from .utils import find_free_port, get_browser_opener
from .utils.port_manager import PortManager
from .utils.compression_config import get_compression_manager
from ..utils.error_handler import ErrorHandler, ErrorType
from ..utils.memory_monitor import get_memory_monitor
from ..debug import web_debug_log as debug_log
from ..i18n import get_i18n_manager


class WebUIManager:
    """Web UI 管理器 - 重構為單一活躍會話模式"""

    def __init__(self, host: str = "127.0.0.1", port: int = None):
        self.host = host

        # 確定偏好端口：環境變數 > 參數 > 預設值 8765
        preferred_port = 8765

        # 檢查環境變數 MCP_WEB_PORT
        env_port = os.getenv("MCP_WEB_PORT")
        if env_port:
            try:
                custom_port = int(env_port)
                if 1024 <= custom_port <= 65535:
                    preferred_port = custom_port
                    debug_log(f"使用環境變數指定的端口: {preferred_port}")
                else:
                    debug_log(f"MCP_WEB_PORT 值無效 ({custom_port})，必須在 1024-65535 範圍內，使用預設端口 8765")
            except ValueError:
                debug_log(f"MCP_WEB_PORT 格式錯誤 ({env_port})，必須為數字，使用預設端口 8765")
        else:
            debug_log(f"未設定 MCP_WEB_PORT 環境變數，使用預設端口 {preferred_port}")

        # 使用增強的端口管理，支持自動清理
        self.port = port or PortManager.find_free_port_enhanced(
            preferred_port=preferred_port,
            auto_cleanup=True,
            host=self.host
        )
        self.app = FastAPI(title="MCP Feedback Enhanced")

        # 設置壓縮和緩存中間件
        self._setup_compression_middleware()

        # 設置內存監控
        self._setup_memory_monitoring()

        # 重構：使用單一活躍會話而非會話字典
        self.current_session: Optional[WebFeedbackSession] = None
        self.sessions: Dict[str, WebFeedbackSession] = {}  # 保留用於向後兼容

        # 全局標籤頁狀態管理 - 跨會話保持
        self.global_active_tabs: Dict[str, dict] = {}

        # 會話更新通知標記
        self._pending_session_update = False

        # 會話清理統計
        self.cleanup_stats = {
            "total_cleanups": 0,
            "expired_cleanups": 0,
            "memory_pressure_cleanups": 0,
            "manual_cleanups": 0,
            "last_cleanup_time": None,
            "total_cleanup_duration": 0.0,
            "sessions_cleaned": 0
        }

        self.server_thread = None
        self.server_process = None
        self.i18n = get_i18n_manager()

        # 設置靜態文件和模板
        self._setup_static_files()
        self._setup_templates()

        # 設置路由
        setup_routes(self)

        debug_log(f"WebUIManager 初始化完成，將在 {self.host}:{self.port} 啟動")

    def _setup_compression_middleware(self):
        """設置壓縮和緩存中間件"""
        # 獲取壓縮管理器
        compression_manager = get_compression_manager()
        config = compression_manager.config

        # 添加 Gzip 壓縮中間件
        self.app.add_middleware(
            GZipMiddleware,
            minimum_size=config.minimum_size
        )

        # 添加緩存和壓縮統計中間件
        @self.app.middleware("http")
        async def compression_and_cache_middleware(request: Request, call_next):
            """壓縮和緩存中間件"""
            response = await call_next(request)

            # 添加緩存頭
            if not config.should_exclude_path(request.url.path):
                cache_headers = config.get_cache_headers(request.url.path)
                for key, value in cache_headers.items():
                    response.headers[key] = value

            # 更新壓縮統計（如果可能）
            try:
                content_length = int(response.headers.get('content-length', 0))
                content_encoding = response.headers.get('content-encoding', '')
                was_compressed = 'gzip' in content_encoding

                if content_length > 0:
                    # 估算原始大小（如果已壓縮，假設壓縮比為 30%）
                    original_size = content_length if not was_compressed else int(content_length / 0.7)
                    compression_manager.update_stats(original_size, content_length, was_compressed)
            except (ValueError, TypeError):
                # 忽略統計錯誤，不影響正常響應
                pass

            return response

        debug_log("壓縮和緩存中間件設置完成")

    def _setup_memory_monitoring(self):
        """設置內存監控"""
        try:
            self.memory_monitor = get_memory_monitor()

            # 添加 Web 應用特定的警告回調
            def web_memory_alert(alert):
                debug_log(f"Web UI 內存警告 [{alert.level}]: {alert.message}")

                # 根據警告級別觸發不同的清理策略
                if alert.level == "critical":
                    # 危險級別：清理過期會話
                    cleaned = self.cleanup_expired_sessions()
                    debug_log(f"內存危險警告觸發，清理了 {cleaned} 個過期會話")
                elif alert.level == "emergency":
                    # 緊急級別：強制清理會話
                    cleaned = self.cleanup_sessions_by_memory_pressure(force=True)
                    debug_log(f"內存緊急警告觸發，強制清理了 {cleaned} 個會話")

            self.memory_monitor.add_alert_callback(web_memory_alert)

            # 添加會話清理回調到內存監控
            def session_cleanup_callback(force: bool = False):
                """內存監控觸發的會話清理回調"""
                try:
                    if force:
                        # 強制清理：包括內存壓力清理
                        cleaned = self.cleanup_sessions_by_memory_pressure(force=True)
                        debug_log(f"內存監控強制清理了 {cleaned} 個會話")
                    else:
                        # 常規清理：只清理過期會話
                        cleaned = self.cleanup_expired_sessions()
                        debug_log(f"內存監控清理了 {cleaned} 個過期會話")
                except Exception as e:
                    error_id = ErrorHandler.log_error_with_context(
                        e,
                        context={"operation": "內存監控會話清理", "force": force},
                        error_type=ErrorType.SYSTEM
                    )
                    debug_log(f"內存監控會話清理失敗 [錯誤ID: {error_id}]: {e}")

            self.memory_monitor.add_cleanup_callback(session_cleanup_callback)

            # 確保內存監控已啟動（ResourceManager 可能已經啟動了）
            if not self.memory_monitor.is_monitoring:
                self.memory_monitor.start_monitoring()

            debug_log("Web UI 內存監控設置完成，已集成會話清理回調")

        except Exception as e:
            error_id = ErrorHandler.log_error_with_context(
                e,
                context={"operation": "設置 Web UI 內存監控"},
                error_type=ErrorType.SYSTEM
            )
            debug_log(f"設置 Web UI 內存監控失敗 [錯誤ID: {error_id}]: {e}")

    def _setup_static_files(self):
        """設置靜態文件服務"""
        # Web UI 靜態文件
        web_static_path = Path(__file__).parent / "static"
        if web_static_path.exists():
            self.app.mount("/static", StaticFiles(directory=str(web_static_path)), name="static")
        else:
            raise RuntimeError(f"Static files directory not found: {web_static_path}")

    def _setup_templates(self):
        """設置模板引擎"""
        # Web UI 模板
        web_templates_path = Path(__file__).parent / "templates"
        if web_templates_path.exists():
            self.templates = Jinja2Templates(directory=str(web_templates_path))
        else:
            raise RuntimeError(f"Templates directory not found: {web_templates_path}")

    def create_session(self, project_directory: str, summary: str) -> str:
        """創建新的回饋會話 - 重構為單一活躍會話模式，保留標籤頁狀態"""
        # 保存舊會話的 WebSocket 連接以便發送更新通知
        old_websocket = None
        if self.current_session and self.current_session.websocket:
            old_websocket = self.current_session.websocket
            debug_log("保存舊會話的 WebSocket 連接以發送更新通知")

        # 如果已有活躍會話，先保存其標籤頁狀態到全局狀態
        if self.current_session:
            debug_log("保存現有會話的標籤頁狀態並清理會話")
            # 保存標籤頁狀態到全局
            if hasattr(self.current_session, 'active_tabs'):
                self._merge_tabs_to_global(self.current_session.active_tabs)

            # 同步清理會話資源（但保留 WebSocket 連接）
            self.current_session._cleanup_sync()

        session_id = str(uuid.uuid4())
        session = WebFeedbackSession(session_id, project_directory, summary)

        # 將全局標籤頁狀態繼承到新會話
        session.active_tabs = self.global_active_tabs.copy()

        # 設置為當前活躍會話
        self.current_session = session
        # 同時保存到字典中以保持向後兼容
        self.sessions[session_id] = session

        debug_log(f"創建新的活躍會話: {session_id}")
        debug_log(f"繼承 {len(session.active_tabs)} 個活躍標籤頁")

        # 處理會話更新通知
        if old_websocket:
            # 有舊連接，立即發送會話更新通知並轉移連接
            self._old_websocket_for_update = old_websocket
            self._new_session_for_update = session
            debug_log("已保存舊 WebSocket 連接，準備發送會話更新通知")

            # 立即發送會話更新通知
            import asyncio
            try:
                # 在後台任務中發送通知並轉移連接
                asyncio.create_task(self._send_immediate_session_update())
            except Exception as e:
                debug_log(f"創建會話更新任務失敗: {e}")
                # 即使任務創建失敗，也要嘗試直接轉移連接
                session.websocket = old_websocket
                debug_log("任務創建失敗，直接轉移 WebSocket 連接到新會話")
                self._pending_session_update = True
        else:
            # 沒有舊連接，標記需要發送會話更新通知（當新 WebSocket 連接建立時）
            self._pending_session_update = True
            debug_log("沒有舊 WebSocket 連接，設置待更新標記")

        return session_id

    def get_session(self, session_id: str) -> Optional[WebFeedbackSession]:
        """獲取回饋會話 - 保持向後兼容"""
        return self.sessions.get(session_id)

    def get_current_session(self) -> Optional[WebFeedbackSession]:
        """獲取當前活躍會話"""
        return self.current_session
    
    def set_current_session_by_id(self, session_id: str) -> bool:
        """通过会话ID设置当前活跃会话"""
        # 首先检查新的会话管理器
        from ..session_manager import get_session_manager
        session_manager = get_session_manager()
        session_data = session_manager.get_session(session_id)
        
        if session_data:
            # 从新的会话管理器创建 WebFeedbackSession
            web_session = WebFeedbackSession(
                session_id=session_data.session_id,
                project_directory=session_data.project_directory,
                summary=session_data.summary
            )
            
            # 同步状态
            if session_data.status.value == "active":
                web_session.status = SessionStatus.ACTIVE
            elif session_data.status.value == "waiting":
                web_session.status = SessionStatus.WAITING
            elif session_data.status.value == "completed":
                web_session.status = SessionStatus.COMPLETED
            elif session_data.status.value == "error":
                web_session.status = SessionStatus.ERROR
            elif session_data.status.value == "timeout":
                web_session.status = SessionStatus.TIMEOUT
            
            # 同步回饋数据
            web_session.feedback_text = session_data.feedback_text
            web_session.command_logs = session_data.command_logs
            web_session.images = session_data.images
            
            # 设置为当前会话
            self.current_session = web_session
            self.sessions[session_id] = web_session
            
            debug_log(f"通过会话ID设置当前会话: {session_id}")
            return True
        
        # 检查现有会话
        if session_id in self.sessions:
            self.current_session = self.sessions[session_id]
            debug_log(f"从现有会话设置当前会话: {session_id}")
            return True
        
        debug_log(f"未找到会话: {session_id}")
        return False

    def remove_session(self, session_id: str):
        """移除回饋會話"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.cleanup()
            del self.sessions[session_id]

            # 如果移除的是當前活躍會話，清空當前會話
            if self.current_session and self.current_session.session_id == session_id:
                self.current_session = None
                debug_log("清空當前活躍會話")

            debug_log(f"移除回饋會話: {session_id}")

    def clear_current_session(self):
        """清空當前活躍會話"""
        if self.current_session:
            session_id = self.current_session.session_id
            self.current_session.cleanup()
            self.current_session = None

            # 同時從字典中移除
            if session_id in self.sessions:
                del self.sessions[session_id]

            debug_log("已清空當前活躍會話")

    def _merge_tabs_to_global(self, session_tabs: dict):
        """將會話的標籤頁狀態合併到全局狀態"""
        current_time = time.time()
        expired_threshold = 60  # 60秒過期閾值

        # 清理過期的全局標籤頁
        self.global_active_tabs = {
            tab_id: tab_info
            for tab_id, tab_info in self.global_active_tabs.items()
            if current_time - tab_info.get('last_seen', 0) <= expired_threshold
        }

        # 合併會話標籤頁到全局
        for tab_id, tab_info in session_tabs.items():
            if current_time - tab_info.get('last_seen', 0) <= expired_threshold:
                self.global_active_tabs[tab_id] = tab_info

        debug_log(f"合併標籤頁狀態，全局活躍標籤頁數量: {len(self.global_active_tabs)}")

    def get_global_active_tabs_count(self) -> int:
        """獲取全局活躍標籤頁數量"""
        current_time = time.time()
        expired_threshold = 60

        # 清理過期標籤頁並返回數量
        valid_tabs = {
            tab_id: tab_info
            for tab_id, tab_info in self.global_active_tabs.items()
            if current_time - tab_info.get('last_seen', 0) <= expired_threshold
        }

        self.global_active_tabs = valid_tabs
        return len(valid_tabs)

    async def broadcast_to_active_tabs(self, message: dict):
        """向所有活躍標籤頁廣播消息"""
        if not self.current_session or not self.current_session.websocket:
            debug_log("沒有活躍的 WebSocket 連接，無法廣播消息")
            return

        try:
            await self.current_session.websocket.send_json(message)
            debug_log(f"已廣播消息到活躍標籤頁: {message.get('type', 'unknown')}")
        except Exception as e:
            debug_log(f"廣播消息失敗: {e}")

    def start_server(self):
        """啟動 Web 伺服器"""
        def run_server_with_retry():
            max_retries = 5
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    debug_log(f"嘗試啟動伺服器在 {self.host}:{self.port} (嘗試 {retry_count + 1}/{max_retries})")
                    
                    config = uvicorn.Config(
                        app=self.app,
                        host=self.host,
                        port=self.port,
                        log_level="warning",
                        access_log=False
                    )
                    
                    server = uvicorn.Server(config)
                    asyncio.run(server.serve())
                    break
                    
                except OSError as e:
                    if e.errno == 10048:  # Windows: 位址已在使用中
                        retry_count += 1
                        if retry_count < max_retries:
                            debug_log(f"端口 {self.port} 被占用，使用增強端口管理查找新端口")
                            # 使用增強的端口管理查找新端口
                            try:
                                self.port = PortManager.find_free_port_enhanced(
                                    preferred_port=self.port + 1,
                                    auto_cleanup=False,  # 啟動時不自動清理，避免誤殺其他服務
                                    host=self.host
                                )
                                debug_log(f"找到新的可用端口: {self.port}")
                            except RuntimeError as port_error:
                                # 使用統一錯誤處理
                                error_id = ErrorHandler.log_error_with_context(
                                    port_error,
                                    context={"operation": "端口查找", "current_port": self.port},
                                    error_type=ErrorType.NETWORK
                                )
                                debug_log(f"無法找到可用端口 [錯誤ID: {error_id}]: {port_error}")
                                break
                        else:
                            debug_log("已達到最大重試次數，無法啟動伺服器")
                            break
                    else:
                        # 使用統一錯誤處理
                        error_id = ErrorHandler.log_error_with_context(
                            e,
                            context={"operation": "伺服器啟動", "host": self.host, "port": self.port},
                            error_type=ErrorType.NETWORK
                        )
                        debug_log(f"伺服器啟動錯誤 [錯誤ID: {error_id}]: {e}")
                        break
                except Exception as e:
                    # 使用統一錯誤處理
                    error_id = ErrorHandler.log_error_with_context(
                        e,
                        context={"operation": "伺服器運行", "host": self.host, "port": self.port},
                        error_type=ErrorType.SYSTEM
                    )
                    debug_log(f"伺服器運行錯誤 [錯誤ID: {error_id}]: {e}")
                    break

        # 在新線程中啟動伺服器
        self.server_thread = threading.Thread(target=run_server_with_retry, daemon=True)
        self.server_thread.start()
        
        # 等待伺服器啟動
        time.sleep(2)

    def open_browser(self, url: str):
        """開啟瀏覽器"""
        try:
            # browser_opener = get_browser_opener()
            # browser_opener(url)
            webbrowser.open(url)
            debug_log(f"已開啟瀏覽器：{url}")
        except Exception as e:
            debug_log(f"無法開啟瀏覽器: {e}")

    async def smart_open_browser(self, url: str) -> bool:
        """智能開啟瀏覽器 - 檢測是否已有活躍標籤頁

        Returns:
            bool: True 表示檢測到活躍標籤頁，False 表示開啟了新視窗
        """
        import asyncio
        import aiohttp

        try:
            # 檢查是否有活躍標籤頁
            has_active_tabs = await self._check_active_tabs()

            if has_active_tabs:
                debug_log("檢測到活躍標籤頁，不開啟新瀏覽器視窗")
                debug_log(f"用戶可以在現有標籤頁中查看更新：{url}")
                return True

            # 沒有活躍標籤頁，開啟新瀏覽器視窗
            debug_log("沒有檢測到活躍標籤頁，開啟新瀏覽器視窗")
            self.open_browser(url)
            return False

        except Exception as e:
            debug_log(f"智能瀏覽器開啟失敗，回退到普通開啟：{e}")
            self.open_browser(url)
            return False

    async def notify_session_update(self, session):
        """向活躍標籤頁發送會話更新通知"""
        try:
            # 檢查是否有活躍的 WebSocket 連接
            if session.websocket:
                # 直接通過當前會話的 WebSocket 發送
                await session.websocket.send_json({
                    "type": "session_updated",
                    "message": "新會話已創建，正在更新頁面內容",
                    "session_info": {
                        "project_directory": session.project_directory,
                        "summary": session.summary,
                        "session_id": session.session_id
                    }
                })
                debug_log("會話更新通知已通過 WebSocket 發送")
            else:
                # 沒有活躍連接，設置待更新標記
                self._pending_session_update = True
                debug_log("沒有活躍 WebSocket 連接，設置待更新標記")
        except Exception as e:
            debug_log(f"發送會話更新通知失敗: {e}")
            # 設置待更新標記作為備用方案
            self._pending_session_update = True

    async def _send_immediate_session_update(self):
        """立即發送會話更新通知（使用舊的 WebSocket 連接）"""
        try:
            # 檢查是否有保存的舊 WebSocket 連接
            if hasattr(self, '_old_websocket_for_update') and hasattr(self, '_new_session_for_update'):
                old_websocket = self._old_websocket_for_update
                new_session = self._new_session_for_update

                # 改進的連接有效性檢查
                websocket_valid = False
                if old_websocket:
                    try:
                        # 檢查 WebSocket 連接狀態
                        if hasattr(old_websocket, 'client_state'):
                            websocket_valid = old_websocket.client_state != old_websocket.client_state.DISCONNECTED
                        else:
                            # 如果沒有 client_state 屬性，嘗試發送測試消息來檢查連接
                            websocket_valid = True
                    except Exception as check_error:
                        debug_log(f"檢查 WebSocket 連接狀態失敗: {check_error}")
                        websocket_valid = False

                if websocket_valid:
                    try:
                        # 發送會話更新通知
                        await old_websocket.send_json({
                            "type": "session_updated",
                            "message": "新會話已創建，正在更新頁面內容",
                            "session_info": {
                                "project_directory": new_session.project_directory,
                                "summary": new_session.summary,
                                "session_id": new_session.session_id
                            }
                        })
                        debug_log("已通過舊 WebSocket 連接發送會話更新通知")

                        # 延遲一小段時間讓前端處理消息
                        await asyncio.sleep(0.2)

                        # 將 WebSocket 連接轉移到新會話
                        new_session.websocket = old_websocket
                        debug_log("已將 WebSocket 連接轉移到新會話")

                    except Exception as send_error:
                        debug_log(f"發送會話更新通知失敗: {send_error}")
                        # 如果發送失敗，仍然嘗試轉移連接
                        new_session.websocket = old_websocket
                        debug_log("發送失敗但仍轉移 WebSocket 連接到新會話")
                else:
                    debug_log("舊 WebSocket 連接無效，設置待更新標記")
                    self._pending_session_update = True

                # 清理臨時變數
                delattr(self, '_old_websocket_for_update')
                delattr(self, '_new_session_for_update')

            else:
                # 沒有舊連接，設置待更新標記
                self._pending_session_update = True
                debug_log("沒有舊 WebSocket 連接，設置待更新標記")

        except Exception as e:
            debug_log(f"立即發送會話更新通知失敗: {e}")
            # 回退到待更新標記
            self._pending_session_update = True

    async def _safe_close_websocket(self, websocket):
        """安全關閉 WebSocket 連接，避免事件循環衝突 - 僅在連接已轉移後調用"""
        if not websocket:
            return

        # 注意：此方法現在主要用於清理，因為連接已經轉移到新會話
        # 只有在確認連接沒有被新會話使用時才關閉
        try:
            # 檢查連接狀態
            if hasattr(websocket, 'client_state') and websocket.client_state.DISCONNECTED:
                debug_log("WebSocket 已斷開，跳過關閉操作")
                return

            # 由於連接已轉移到新會話，這裡不再主動關閉
            # 讓新會話管理這個連接的生命週期
            debug_log("WebSocket 連接已轉移到新會話，跳過關閉操作")

        except Exception as e:
            debug_log(f"檢查 WebSocket 連接狀態時發生錯誤: {e}")

    async def _check_active_tabs(self) -> bool:
        """檢查是否有活躍標籤頁 - 優先檢查全局狀態，回退到 API"""
        try:
            # 首先檢查全局標籤頁狀態
            global_count = self.get_global_active_tabs_count()
            if global_count > 0:
                debug_log(f"檢測到 {global_count} 個全局活躍標籤頁")
                return True

            # 如果全局狀態沒有活躍標籤頁，嘗試通過 API 檢查
            # 等待一小段時間讓服務器完全啟動
            await asyncio.sleep(0.5)

            # 調用活躍標籤頁 API
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.get_server_url()}/api/active-tabs", timeout=2) as response:
                    if response.status == 200:
                        data = await response.json()
                        tab_count = data.get("count", 0)
                        debug_log(f"API 檢測到 {tab_count} 個活躍標籤頁")
                        return tab_count > 0
                    else:
                        debug_log(f"檢查活躍標籤頁失敗，狀態碼：{response.status}")
                        return False

        except asyncio.TimeoutError:
            debug_log("檢查活躍標籤頁超時")
            return False
        except Exception as e:
            debug_log(f"檢查活躍標籤頁時發生錯誤：{e}")
            return False

    def get_server_url(self) -> str:
        """獲取伺服器 URL"""
        return f"http://{self.host}:{self.port}"

    def cleanup_expired_sessions(self) -> int:
        """清理過期會話"""
        cleanup_start_time = time.time()
        expired_sessions = []

        # 掃描過期會話
        for session_id, session in self.sessions.items():
            if session.is_expired():
                expired_sessions.append(session_id)

        # 批量清理過期會話
        cleaned_count = 0
        for session_id in expired_sessions:
            try:
                session = self.sessions.get(session_id)
                if session:
                    # 使用增強清理方法
                    session._cleanup_sync_enhanced(CleanupReason.EXPIRED)
                    del self.sessions[session_id]
                    cleaned_count += 1

                    # 如果清理的是當前活躍會話，清空當前會話
                    if self.current_session and self.current_session.session_id == session_id:
                        self.current_session = None
                        debug_log("清空過期的當前活躍會話")

            except Exception as e:
                error_id = ErrorHandler.log_error_with_context(
                    e,
                    context={"session_id": session_id, "operation": "清理過期會話"},
                    error_type=ErrorType.SYSTEM
                )
                debug_log(f"清理過期會話 {session_id} 失敗 [錯誤ID: {error_id}]: {e}")

        # 更新統計
        cleanup_duration = time.time() - cleanup_start_time
        self.cleanup_stats.update({
            "total_cleanups": self.cleanup_stats["total_cleanups"] + 1,
            "expired_cleanups": self.cleanup_stats["expired_cleanups"] + 1,
            "last_cleanup_time": datetime.now().isoformat(),
            "total_cleanup_duration": self.cleanup_stats["total_cleanup_duration"] + cleanup_duration,
            "sessions_cleaned": self.cleanup_stats["sessions_cleaned"] + cleaned_count
        })

        if cleaned_count > 0:
            debug_log(f"清理了 {cleaned_count} 個過期會話，耗時: {cleanup_duration:.2f}秒")

        return cleaned_count

    def cleanup_sessions_by_memory_pressure(self, force: bool = False) -> int:
        """根據內存壓力清理會話"""
        cleanup_start_time = time.time()
        sessions_to_clean = []

        # 根據優先級選擇要清理的會話
        # 優先級：已完成 > 已提交反饋 > 錯誤狀態 > 空閒時間最長
        for session_id, session in self.sessions.items():
            # 跳過當前活躍會話（除非強制清理）
            if not force and self.current_session and session.session_id == self.current_session.session_id:
                continue

            # 優先清理已完成或錯誤狀態的會話
            if session.status in [SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.TIMEOUT]:
                sessions_to_clean.append((session_id, session, 1))  # 高優先級
            elif session.status == SessionStatus.FEEDBACK_SUBMITTED:
                # 已提交反饋但空閒時間較長的會話
                if session.get_idle_time() > 300:  # 5分鐘空閒
                    sessions_to_clean.append((session_id, session, 2))  # 中優先級
            elif session.get_idle_time() > 600:  # 10分鐘空閒
                sessions_to_clean.append((session_id, session, 3))  # 低優先級

        # 按優先級排序
        sessions_to_clean.sort(key=lambda x: x[2])

        # 清理會話（限制數量避免過度清理）
        max_cleanup = min(len(sessions_to_clean), 5 if not force else len(sessions_to_clean))
        cleaned_count = 0

        for i in range(max_cleanup):
            session_id, session, priority = sessions_to_clean[i]
            try:
                # 使用增強清理方法
                session._cleanup_sync_enhanced(CleanupReason.MEMORY_PRESSURE)
                del self.sessions[session_id]
                cleaned_count += 1

                # 如果清理的是當前活躍會話，清空當前會話
                if self.current_session and self.current_session.session_id == session_id:
                    self.current_session = None
                    debug_log("因內存壓力清空當前活躍會話")

            except Exception as e:
                error_id = ErrorHandler.log_error_with_context(
                    e,
                    context={"session_id": session_id, "operation": "內存壓力清理"},
                    error_type=ErrorType.SYSTEM
                )
                debug_log(f"內存壓力清理會話 {session_id} 失敗 [錯誤ID: {error_id}]: {e}")

        # 更新統計
        cleanup_duration = time.time() - cleanup_start_time
        self.cleanup_stats.update({
            "total_cleanups": self.cleanup_stats["total_cleanups"] + 1,
            "memory_pressure_cleanups": self.cleanup_stats["memory_pressure_cleanups"] + 1,
            "last_cleanup_time": datetime.now().isoformat(),
            "total_cleanup_duration": self.cleanup_stats["total_cleanup_duration"] + cleanup_duration,
            "sessions_cleaned": self.cleanup_stats["sessions_cleaned"] + cleaned_count
        })

        if cleaned_count > 0:
            debug_log(f"因內存壓力清理了 {cleaned_count} 個會話，耗時: {cleanup_duration:.2f}秒")

        return cleaned_count

    def get_session_cleanup_stats(self) -> dict:
        """獲取會話清理統計"""
        stats = self.cleanup_stats.copy()
        stats.update({
            "active_sessions": len(self.sessions),
            "current_session_id": self.current_session.session_id if self.current_session else None,
            "expired_sessions": sum(1 for s in self.sessions.values() if s.is_expired()),
            "idle_sessions": sum(1 for s in self.sessions.values() if s.get_idle_time() > 300),
            "memory_usage_mb": 0  # 將在下面計算
        })

        # 計算內存使用（如果可能）
        try:
            import psutil
            process = psutil.Process()
            stats["memory_usage_mb"] = round(process.memory_info().rss / (1024 * 1024), 2)
        except:
            pass

        return stats

    def _scan_expired_sessions(self) -> List[str]:
        """掃描過期會話ID列表"""
        expired_sessions = []
        for session_id, session in self.sessions.items():
            if session.is_expired():
                expired_sessions.append(session_id)
        return expired_sessions

    def stop(self):
        """停止 Web UI 服務"""
        # 清理所有會話
        cleanup_start_time = time.time()
        session_count = len(self.sessions)

        for session in list(self.sessions.values()):
            try:
                session._cleanup_sync_enhanced(CleanupReason.SHUTDOWN)
            except Exception as e:
                debug_log(f"停止服務時清理會話失敗: {e}")

        self.sessions.clear()
        self.current_session = None

        # 更新統計
        cleanup_duration = time.time() - cleanup_start_time
        self.cleanup_stats.update({
            "total_cleanups": self.cleanup_stats["total_cleanups"] + 1,
            "manual_cleanups": self.cleanup_stats["manual_cleanups"] + 1,
            "last_cleanup_time": datetime.now().isoformat(),
            "total_cleanup_duration": self.cleanup_stats["total_cleanup_duration"] + cleanup_duration,
            "sessions_cleaned": self.cleanup_stats["sessions_cleaned"] + session_count
        })

        debug_log(f"停止服務時清理了 {session_count} 個會話，耗時: {cleanup_duration:.2f}秒")

        # 停止伺服器（注意：uvicorn 的 graceful shutdown 需要額外處理）
        if self.server_thread and self.server_thread.is_alive():
            debug_log("正在停止 Web UI 服務")


# 全域實例
_web_ui_manager: Optional[WebUIManager] = None


def get_web_ui_manager() -> WebUIManager:
    """獲取 Web UI 管理器實例"""
    global _web_ui_manager
    if _web_ui_manager is None:
        _web_ui_manager = WebUIManager()
    return _web_ui_manager


async def launch_web_feedback_ui(project_directory: str, summary: str, timeout: int = 600) -> dict:
    """
    啟動 Web 回饋介面並等待用戶回饋 - 重構為使用根路徑

    Args:
        project_directory: 專案目錄路徑
        summary: AI 工作摘要
        timeout: 超時時間（秒）

    Returns:
        dict: 回饋結果，包含 logs、interactive_feedback 和 images
    """
    manager = get_web_ui_manager()

    # 創建或更新當前活躍會話
    session_id = manager.create_session(project_directory, summary)
    session = manager.get_current_session()

    if not session:
        raise RuntimeError("無法創建回饋會話")

    # 啟動伺服器（如果尚未啟動）
    if not manager.server_thread or not manager.server_thread.is_alive():
        manager.start_server()

    # 使用根路徑 URL 並智能開啟瀏覽器
    feedback_url = manager.get_server_url()  # 直接使用根路徑
    has_active_tabs = await manager.smart_open_browser(feedback_url)

    debug_log(f"[DEBUG] 服務器地址: {feedback_url}")

    # 如果檢測到活躍標籤頁但沒有開啟新視窗，立即發送會話更新通知
    if has_active_tabs:
        await manager._send_immediate_session_update()
        debug_log("已向活躍標籤頁發送會話更新通知")

    try:
        # 等待用戶回饋，傳遞 timeout 參數
        result = await session.wait_for_feedback(timeout)
        debug_log(f"收到用戶回饋")
        return result
    except TimeoutError:
        debug_log(f"會話超時")
        # 資源已在 wait_for_feedback 中清理，這裡只需要記錄和重新拋出
        raise
    except Exception as e:
        debug_log(f"會話發生錯誤: {e}")
        raise
    finally:
        # 注意：不再自動清理會話和停止服務器，保持持久性
        # 會話將保持活躍狀態，等待下次 MCP 調用
        debug_log("會話保持活躍狀態，等待下次 MCP 調用")


def stop_web_ui():
    """停止 Web UI 服務"""
    global _web_ui_manager
    if _web_ui_manager:
        _web_ui_manager.stop()
        _web_ui_manager = None
        debug_log("Web UI 服務已停止")


# 測試用主函數
if __name__ == "__main__":
    async def main():
        try:
            project_dir = os.getcwd()
            summary = "這是一個測試摘要，用於驗證 Web UI 功能。"
            
            from ..debug import debug_log
            debug_log(f"啟動 Web UI 測試...")
            debug_log(f"專案目錄: {project_dir}")
            debug_log("等待用戶回饋...")

            result = await launch_web_feedback_ui(project_dir, summary)

            debug_log("收到回饋結果:")
            debug_log(f"命令日誌: {result.get('logs', '')}")
            debug_log(f"互動回饋: {result.get('interactive_feedback', '')}")
            debug_log(f"圖片數量: {len(result.get('images', []))}")

        except KeyboardInterrupt:
            debug_log("\n用戶取消操作")
        except Exception as e:
            debug_log(f"錯誤: {e}")
        finally:
            stop_web_ui()

    asyncio.run(main()) 