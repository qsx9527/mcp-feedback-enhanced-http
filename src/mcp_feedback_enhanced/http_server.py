#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP MCP 服务器
===============

基于 FastAPI 的 HTTP MCP 服务器，实现 JSON-RPC 2.0 协议。

主要功能：
- HTTP MCP 协议支持
- 多用户会话管理
- 安全的 URL 生成
- 与现有 Web UI 集成
- 异步处理支持
"""

import asyncio
import json
import os
import sys
import traceback
from typing import Dict, Any, Optional, List, Union
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .debug import debug_log
from .session_manager import get_session_manager, SessionStatus
from .url_generator import get_url_generator, validate_session_access
from .server import interactive_feedback as original_interactive_feedback
from .web.main import get_web_ui_manager

# 导入版本信息
from . import __version__


class MCPRequest(BaseModel):
    """MCP 请求模型"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC 版本")
    id: Optional[Union[str, int]] = Field(default=None, description="请求 ID")
    method: str = Field(description="方法名")
    params: Optional[Dict[str, Any]] = Field(default=None, description="参数")


class MCPResponse(BaseModel):
    """MCP 响应模型"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC 版本")
    id: Optional[Union[str, int]] = Field(default=None, description="请求 ID")
    result: Optional[Any] = Field(default=None, description="结果")
    error: Optional[Dict[str, Any]] = Field(default=None, description="错误信息")


class MCPError:
    """MCP 错误代码"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class HTTPMCPServer:
    """HTTP MCP 服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 8766):
        self.host = host
        self.port = port
        self.app: Optional[FastAPI] = None
        self.server_task: Optional[asyncio.Task] = None
        self.session_manager = get_session_manager()
        self.url_generator = get_url_generator()
        
        # 更新 URL 生成器配置
        self.url_generator.base_host = host
        self.url_generator.base_port = port
        
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """应用生命周期管理"""
        debug_log("HTTP MCP 服务器启动")
        yield
        debug_log("HTTP MCP 服务器关闭")
        # 清理资源
        self.session_manager.shutdown()
    
    def create_app(self) -> FastAPI:
        """创建 FastAPI 应用"""
        app = FastAPI(
            title="MCP Feedback Enhanced HTTP Server",
            description="HTTP MCP 服务器，提供交互式回饋功能",
            version=__version__,
            lifespan=self.lifespan
        )
        
        # 添加 CORS 中间件
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # 注册路由
        self._register_routes(app)
        
        return app
    
    def _register_routes(self, app: FastAPI):
        """注册路由"""
        
        @app.post("/mcp")
        async def handle_mcp_request(request: Request):
            """处理 MCP 请求"""
            try:
                # 解析请求体
                body = await request.body()
                if not body:
                    return self._create_error_response(
                        None, MCPError.INVALID_REQUEST, "Empty request body"
                    )
                
                try:
                    request_data = json.loads(body.decode('utf-8'))
                except json.JSONDecodeError as e:
                    return self._create_error_response(
                        None, MCPError.PARSE_ERROR, f"JSON parse error: {str(e)}"
                    )
                
                # 验证请求格式
                if not isinstance(request_data, dict):
                    return self._create_error_response(
                        None, MCPError.INVALID_REQUEST, "Request must be a JSON object"
                    )
                
                # 处理请求
                response = await self._handle_mcp_method(request_data)
                return JSONResponse(content=response)
                
            except Exception as e:
                debug_log(f"MCP 请求处理错误: {e}")
                debug_log(f"错误详情: {traceback.format_exc()}")
                return self._create_error_response(
                    None, MCPError.INTERNAL_ERROR, f"Internal server error: {str(e)}"
                )
        
        @app.get("/")
        async def root():
            """根路径"""
            return {
                "name": "MCP Feedback Enhanced HTTP Server",
                "version": __version__,
                "status": "running",
                "endpoints": {
                    "mcp": "/mcp",
                    "session": "/session/{session_id}",
                    "health": "/health"
                }
            }
        
        @app.get("/health")
        async def health_check():
            """健康检查"""
            return {
                "status": "healthy",
                "version": __version__,
                "active_sessions": len(self.session_manager.list_sessions())
            }
        
        @app.get("/session/{session_id}")
        async def session_page(
            session_id: str,
            token: Optional[str] = Query(None, description="安全令牌")
        ):
            """会话页面"""
            # 验证会话访问权限
            if not validate_session_access(session_id, token):
                raise HTTPException(status_code=403, detail="Access denied")
            
            # 检查会话是否存在
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            
            # 重定向到 Web UI，并传递会话信息
            web_ui_manager = get_web_ui_manager()
            
            # 确保 Web UI 服务器正在运行
            if not web_ui_manager.server_thread or not web_ui_manager.server_thread.is_alive():
                web_ui_manager.start_server()
            
            # 设置当前会话
            web_ui_manager.set_current_session_by_id(session_id)
            
            # 重定向到 Web UI 根路径
            web_ui_url = web_ui_manager.get_server_url()
            return RedirectResponse(url=web_ui_url)
        
        @app.get("/sessions")
        async def list_sessions():
            """列出所有会话"""
            sessions = self.session_manager.list_sessions()
            return {"sessions": sessions}
    
    async def _handle_mcp_method(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 MCP 方法调用"""
        request_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})
        
        if not method:
            return self._create_error_response(
                request_id, MCPError.INVALID_REQUEST, "Missing method"
            )
        
        try:
            if method == "initialize":
                result = await self._handle_initialize(params)
            elif method == "tools/list":
                result = await self._handle_tools_list(params)
            elif method == "tools/call":
                result = await self._handle_tools_call(params)
            else:
                return self._create_error_response(
                    request_id, MCPError.METHOD_NOT_FOUND, f"Method not found: {method}"
                )
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
        except Exception as e:
            debug_log(f"方法 {method} 执行错误: {e}")
            debug_log(f"错误详情: {traceback.format_exc()}")
            return self._create_error_response(
                request_id, MCPError.INTERNAL_ERROR, str(e)
            )
    
    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理初始化请求"""
        debug_log("处理 MCP 初始化请求")
        
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "mcp-feedback-enhanced-http",
                "version": __version__
            },
            "capabilities": {
                "tools": {
                    "listChanged": True
                }
            }
        }
    
    async def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具列表请求"""
        debug_log("处理工具列表请求")
        
        return {
            "tools": [
                {
                    "name": "interactive_feedback",
                    "description": "收集用户的互动回饋，支援文字和圖片。返回交互 URL 供用户访问。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "project_directory": {
                                "type": "string",
                                "description": "專案目錄路徑",
                                "default": "."
                            },
                            "summary": {
                                "type": "string",
                                "description": "AI 工作完成的摘要說明",
                                "default": "我已完成了您請求的任務。"
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "等待用戶回饋的超時時間（秒）",
                                "default": 600
                            }
                        }
                    }
                }
            ]
        }
    
    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具调用请求"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        debug_log(f"处理工具调用: {tool_name}")
        
        if tool_name == "interactive_feedback":
            return await self._handle_interactive_feedback(arguments)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    async def _handle_interactive_feedback(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """处理交互式回饋工具调用"""
        project_directory = arguments.get("project_directory", ".")
        summary = arguments.get("summary", "我已完成了您請求的任務。")
        timeout = arguments.get("timeout", 600)
        
        debug_log(f"创建交互式回饋会话: {project_directory}")
        
        # 创建会话
        session_id = self.session_manager.create_session(
            project_directory=project_directory,
            summary=summary,
            timeout=timeout
        )
        
        # 生成会话 URL
        session_url = self.url_generator.generate_session_url(session_id)
        
        # 更新会话状态为活跃
        self.session_manager.update_session_status(session_id, SessionStatus.ACTIVE)
        
        debug_log(f"会话已创建: {session_id}")
        debug_log(f"会话 URL: {session_url}")
        
        # 返回 URL 和会话信息
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"交互式回饋会话已创建。\n\n请访问以下 URL 进行交互：\n{session_url}\n\n会话 ID: {session_id}\n项目目录: {project_directory}\n超时时间: {timeout} 秒"
                }
            ],
            "session_info": {
                "session_id": session_id,
                "url": session_url,
                "project_directory": project_directory,
                "summary": summary,
                "timeout": timeout
            }
        }
    
    def _create_error_response(self, request_id: Optional[Union[str, int]], 
                             error_code: int, error_message: str) -> Dict[str, Any]:
        """创建错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": error_code,
                "message": error_message
            }
        }
    
    async def start(self):
        """启动服务器"""
        if self.server_task and not self.server_task.done():
            debug_log("HTTP MCP 服务器已在运行")
            return
        
        self.app = self.create_app()
        
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info" if os.getenv("MCP_DEBUG") else "warning",
            access_log=bool(os.getenv("MCP_DEBUG"))
        )
        
        server = uvicorn.Server(config)
        
        debug_log(f"启动 HTTP MCP 服务器: http://{self.host}:{self.port}")
        
        # 在后台任务中运行服务器
        self.server_task = asyncio.create_task(server.serve())
        
        # 等待服务器启动
        await asyncio.sleep(1)
        
        debug_log("HTTP MCP 服务器启动完成")
    
    async def stop(self):
        """停止服务器"""
        if self.server_task and not self.server_task.done():
            debug_log("停止 HTTP MCP 服务器")
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
            self.server_task = None
        
        # 清理资源
        self.session_manager.shutdown()
    
    def is_running(self) -> bool:
        """检查服务器是否正在运行"""
        return self.server_task is not None and not self.server_task.done()


# 全局服务器实例
_http_server: Optional[HTTPMCPServer] = None


def get_http_server() -> HTTPMCPServer:
    """获取全局 HTTP 服务器实例"""
    global _http_server
    if _http_server is None:
        host = os.getenv('MCP_HTTP_HOST', 'localhost')
        port = int(os.getenv('MCP_HTTP_PORT', '8766'))
        _http_server = HTTPMCPServer(host=host, port=port)
    return _http_server


async def start_http_server():
    """启动 HTTP 服务器"""
    server = get_http_server()
    await server.start()
    return server


async def stop_http_server():
    """停止 HTTP 服务器"""
    global _http_server
    if _http_server:
        await _http_server.stop()
        _http_server = None


def main():
    """主函数，用于独立运行 HTTP 服务器"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Feedback Enhanced HTTP Server")
    parser.add_argument("--host", default="localhost", help="服务器主机地址")
    parser.add_argument("--port", type=int, default=8766, help="服务器端口")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    
    args = parser.parse_args()
    
    if args.debug:
        os.environ["MCP_DEBUG"] = "true"
    
    async def run_server():
        server = HTTPMCPServer(host=args.host, port=args.port)
        await server.start()
        
        try:
            # 保持服务器运行
            while server.is_running():
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            debug_log("收到中断信号")
        finally:
            await server.stop()
    
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        debug_log("服务器已停止")


if __name__ == "__main__":
    main() 