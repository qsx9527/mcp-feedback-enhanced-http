#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话管理系统
============

管理多用户的交互会话，提供会话创建、状态跟踪、超时处理等功能。

主要功能：
- 会话创建和管理
- 多用户并发支持
- 会话状态跟踪
- 自动超时清理
- 线程安全操作
"""

import asyncio
import time
import uuid
import threading
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from .debug import debug_log


class SessionStatus(Enum):
    """会话状态枚举"""
    CREATED = "created"          # 已创建
    ACTIVE = "active"            # 活跃中
    WAITING = "waiting"          # 等待用户回饋
    COMPLETED = "completed"      # 已完成
    TIMEOUT = "timeout"          # 已超时
    ERROR = "error"              # 发生错误


@dataclass
class SessionData:
    """会话数据类"""
    session_id: str
    project_directory: str
    summary: str
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    timeout_seconds: int = 600
    
    # 回饋数据
    feedback_text: str = ""
    command_logs: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    
    # 异步事件
    completion_event: Optional[asyncio.Event] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        """初始化后处理"""
        if self.completion_event is None:
            self.completion_event = asyncio.Event()
    
    def is_expired(self) -> bool:
        """检查会话是否已过期"""
        if self.status in [SessionStatus.COMPLETED, SessionStatus.TIMEOUT, SessionStatus.ERROR]:
            return True
        
        expiry_time = self.created_at + timedelta(seconds=self.timeout_seconds)
        return datetime.now() > expiry_time
    
    def update_activity(self):
        """更新最后活动时间"""
        self.last_activity = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "project_directory": self.project_directory,
            "summary": self.summary,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "timeout_seconds": self.timeout_seconds,
            "feedback_text": self.feedback_text,
            "command_logs": self.command_logs,
            "images": self.images,
            "error_message": self.error_message
        }


class SessionManager:
    """会话管理器"""
    
    def __init__(self):
        self._sessions: Dict[str, SessionData] = {}
        self._lock = threading.RLock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 60  # 清理间隔（秒）
        
    def create_session(self, project_directory: str, summary: str, timeout: int = 600) -> str:
        """
        创建新会话
        
        Args:
            project_directory: 项目目录
            summary: AI 工作摘要
            timeout: 超时时间（秒）
            
        Returns:
            str: 会话ID
        """
        session_id = self._generate_session_id()
        
        with self._lock:
            session_data = SessionData(
                session_id=session_id,
                project_directory=project_directory,
                summary=summary,
                timeout_seconds=timeout
            )
            
            self._sessions[session_id] = session_data
            debug_log(f"创建新会话: {session_id}")
            
        # 启动清理任务（如果尚未启动）
        self._ensure_cleanup_task()
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """
        获取会话数据
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[SessionData]: 会话数据，如果不存在则返回None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session and not session.is_expired():
                session.update_activity()
                return session
            elif session and session.is_expired():
                # 清理过期会话
                self._cleanup_session(session_id)
                return None
            return None
    
    def update_session_status(self, session_id: str, status: SessionStatus) -> bool:
        """
        更新会话状态
        
        Args:
            session_id: 会话ID
            status: 新状态
            
        Returns:
            bool: 更新是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.status = status
                session.update_activity()
                debug_log(f"会话 {session_id} 状态更新为: {status.value}")
                return True
            return False
    
    def add_feedback(self, session_id: str, feedback_type: str, data: Any) -> bool:
        """
        添加回饋数据
        
        Args:
            session_id: 会话ID
            feedback_type: 回饋类型 ('text', 'command', 'image')
            data: 回饋数据
            
        Returns:
            bool: 添加是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.update_activity()
            
            if feedback_type == 'text':
                session.feedback_text = str(data)
            elif feedback_type == 'command':
                if isinstance(data, dict):
                    session.command_logs.append(data)
                else:
                    session.command_logs.append({"output": str(data)})
            elif feedback_type == 'image':
                if isinstance(data, dict):
                    session.images.append(data)
                else:
                    session.images.append({"data": data})
            
            debug_log(f"会话 {session_id} 添加 {feedback_type} 回饋")
            return True
    
    def complete_session(self, session_id: str, result_data: Dict[str, Any]) -> bool:
        """
        完成会话
        
        Args:
            session_id: 会话ID
            result_data: 结果数据
            
        Returns:
            bool: 完成是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.status = SessionStatus.COMPLETED
            session.result_data = result_data
            session.update_activity()
            
            # 触发完成事件
            if session.completion_event:
                try:
                    # 在事件循环中设置事件
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(session.completion_event.set)
                except RuntimeError:
                    # 如果没有运行的事件循环，创建一个新的
                    asyncio.run(self._set_event_async(session.completion_event))
            
            debug_log(f"会话 {session_id} 已完成")
            return True
    
    async def _set_event_async(self, event: asyncio.Event):
        """异步设置事件"""
        event.set()
    
    def fail_session(self, session_id: str, error_message: str) -> bool:
        """
        标记会话失败
        
        Args:
            session_id: 会话ID
            error_message: 错误信息
            
        Returns:
            bool: 标记是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.status = SessionStatus.ERROR
            session.error_message = error_message
            session.update_activity()
            
            # 触发完成事件
            if session.completion_event:
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(session.completion_event.set)
                except RuntimeError:
                    asyncio.run(self._set_event_async(session.completion_event))
            
            debug_log(f"会话 {session_id} 失败: {error_message}")
            return True
    
    async def wait_for_completion(self, session_id: str, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        等待会话完成
        
        Args:
            session_id: 会话ID
            timeout: 超时时间（秒），None表示使用会话默认超时
            
        Returns:
            Optional[Dict[str, Any]]: 会话结果，超时或失败返回None
        """
        session = self.get_session(session_id)
        if not session:
            return None
        
        # 如果已经完成，直接返回结果
        if session.status == SessionStatus.COMPLETED:
            return session.result_data
        elif session.status in [SessionStatus.ERROR, SessionStatus.TIMEOUT]:
            return None
        
        # 等待完成事件
        wait_timeout = timeout or session.timeout_seconds
        
        try:
            await asyncio.wait_for(session.completion_event.wait(), timeout=wait_timeout)
            
            # 重新获取会话状态
            updated_session = self.get_session(session_id)
            if updated_session and updated_session.status == SessionStatus.COMPLETED:
                return updated_session.result_data
            else:
                return None
                
        except asyncio.TimeoutError:
            # 标记会话超时
            self.update_session_status(session_id, SessionStatus.TIMEOUT)
            debug_log(f"会话 {session_id} 等待超时")
            return None
    
    def list_sessions(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """
        列出所有会话
        
        Args:
            include_expired: 是否包含过期会话
            
        Returns:
            List[Dict[str, Any]]: 会话列表
        """
        with self._lock:
            sessions = []
            for session in self._sessions.values():
                if include_expired or not session.is_expired():
                    sessions.append(session.to_dict())
            return sessions
    
    def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话
        
        Returns:
            int: 清理的会话数量
        """
        with self._lock:
            expired_sessions = []
            for session_id, session in self._sessions.items():
                if session.is_expired():
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                self._cleanup_session(session_id)
            
            if expired_sessions:
                debug_log(f"清理了 {len(expired_sessions)} 个过期会话")
            
            return len(expired_sessions)
    
    def _cleanup_session(self, session_id: str):
        """清理单个会话"""
        session = self._sessions.pop(session_id, None)
        if session:
            debug_log(f"清理会话: {session_id}")
    
    def _generate_session_id(self) -> str:
        """生成唯一的会话ID"""
        return f"session_{uuid.uuid4().hex[:12]}_{int(time.time())}"
    
    def _ensure_cleanup_task(self):
        """确保清理任务正在运行"""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                loop = asyncio.get_event_loop()
                self._cleanup_task = loop.create_task(self._cleanup_loop())
            except RuntimeError:
                # 如果没有运行的事件循环，不启动清理任务
                # 清理将在下次调用时进行
                pass
    
    async def _cleanup_loop(self):
        """清理循环任务"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                self.cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"清理任务发生错误: {e}")
                await asyncio.sleep(self._cleanup_interval)
    
    def shutdown(self):
        """关闭会话管理器"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        
        with self._lock:
            self._sessions.clear()
        
        debug_log("会话管理器已关闭")


# 全局会话管理器实例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局会话管理器实例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def shutdown_session_manager():
    """关闭全局会话管理器"""
    global _session_manager
    if _session_manager:
        _session_manager.shutdown()
        _session_manager = None 