#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 版本的 Interactive Feedback 工具
====================================

为 HTTP MCP 服务器提供的 interactive_feedback 工具实现。
与原版不同，此版本创建会话并返回 URL，而不是直接处理用户交互。

主要功能：
- 创建交互会话
- 生成安全的访问 URL
- 返回会话信息
- 支持会话状态管理
"""

import os
from typing import List, Dict, Any
from mcp.types import TextContent

from .debug import debug_log
from .session_manager import get_session_manager, SessionStatus
from .url_generator import get_url_generator


async def http_interactive_feedback(
    project_directory: str = ".",
    summary: str = "我已完成了您請求的任務。",
    timeout: int = 600
) -> Dict[str, Any]:
    """
    HTTP 版本的交互式回饋工具
    
    创建会话并返回交互 URL，而不是直接处理用户交互。
    
    Args:
        project_directory: 專案目錄路徑
        summary: AI 工作完成的摘要說明
        timeout: 等待用戶回饋的超時時間（秒）
        
    Returns:
        Dict[str, Any]: 包含 URL 和会话信息的响应
    """
    debug_log(f"HTTP 交互式回饋工具调用: {project_directory}")
    
    try:
        # 确保项目目录存在
        if not os.path.exists(project_directory):
            project_directory = os.getcwd()
        project_directory = os.path.abspath(project_directory)
        
        # 获取会话管理器和 URL 生成器
        session_manager = get_session_manager()
        url_generator = get_url_generator()
        
        # 创建会话
        session_id = session_manager.create_session(
            project_directory=project_directory,
            summary=summary,
            timeout=timeout
        )
        
        # 生成会话 URL
        session_url = url_generator.generate_session_url(session_id)
        
        # 更新会话状态为活跃
        session_manager.update_session_status(session_id, SessionStatus.ACTIVE)
        
        debug_log(f"HTTP 会话已创建: {session_id}")
        debug_log(f"HTTP 会话 URL: {session_url}")
        
        # 构建响应内容
        response_text = f"""交互式回饋会话已创建。

请访问以下 URL 进行交互：
{session_url}

会话 ID: {session_id}
项目目录: {project_directory}
超时时间: {timeout} 秒

💡 提示：
• 在浏览器中打开上述 URL 即可开始交互
• 您可以提供文字回饋、上传图片、执行命令等
• 会话将在 {timeout} 秒后自动超时
• 完成回饋后请点击"提交回饋"按钮"""
        
        # 返回标准的 MCP 工具响应格式
        return {
            "content": [
                {
                    "type": "text",
                    "text": response_text
                }
            ],
            "session_info": {
                "session_id": session_id,
                "url": session_url,
                "project_directory": project_directory,
                "summary": summary,
                "timeout": timeout,
                "status": "active"
            }
        }
        
    except Exception as e:
        error_msg = f"创建交互式回饋会话失败: {str(e)}"
        debug_log(f"HTTP 交互式回饋工具错误: {e}")
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": error_msg
                }
            ],
            "error": {
                "type": "session_creation_failed",
                "message": str(e)
            }
        }


async def wait_for_session_completion(session_id: str, timeout: int = None) -> Dict[str, Any]:
    """
    等待会话完成（可选功能）
    
    Args:
        session_id: 会话 ID
        timeout: 超时时间（秒）
        
    Returns:
        Dict[str, Any]: 会话结果
    """
    session_manager = get_session_manager()
    
    try:
        result = await session_manager.wait_for_completion(session_id, timeout)
        
        if result:
            debug_log(f"会话 {session_id} 完成，结果: {result}")
            return {
                "status": "completed",
                "result": result
            }
        else:
            debug_log(f"会话 {session_id} 超时或失败")
            return {
                "status": "timeout_or_failed",
                "result": None
            }
            
    except Exception as e:
        debug_log(f"等待会话完成时发生错误: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def get_session_status(session_id: str) -> Dict[str, Any]:
    """
    获取会话状态
    
    Args:
        session_id: 会话 ID
        
    Returns:
        Dict[str, Any]: 会话状态信息
    """
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    
    if session:
        return {
            "exists": True,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "project_directory": session.project_directory,
            "summary": session.summary,
            "timeout_seconds": session.timeout_seconds,
            "feedback_text": session.feedback_text,
            "command_logs_count": len(session.command_logs),
            "images_count": len(session.images),
            "error_message": session.error_message
        }
    else:
        return {
            "exists": False,
            "status": "not_found"
        } 