#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URL 生成器
==========

负责生成安全的会话 URL 和管理 URL 路由。

主要功能：
- 生成唯一的会话 URL
- URL 安全性验证
- 路由管理
- 域名和端口配置
"""

import os
import hashlib
import secrets
from typing import Optional, Dict, Any
from urllib.parse import urljoin, urlparse

from .debug import debug_log


class URLGenerator:
    """URL 生成器"""
    
    def __init__(self, base_host: str = "localhost", base_port: int = 8766, use_https: bool = False):
        """
        初始化 URL 生成器
        
        Args:
            base_host: 基础主机地址
            base_port: 基础端口
            use_https: 是否使用 HTTPS
        """
        self.base_host = base_host
        self.base_port = base_port
        self.use_https = use_https
        self._url_tokens: Dict[str, str] = {}  # session_id -> token 映射
        
    @property
    def base_url(self) -> str:
        """获取基础 URL"""
        scheme = "https" if self.use_https else "http"
        if (not self.use_https and self.base_port == 80) or (self.use_https and self.base_port == 443):
            return f"{scheme}://{self.base_host}"
        else:
            return f"{scheme}://{self.base_host}:{self.base_port}"
    
    def generate_session_url(self, session_id: str, include_token: bool = True) -> str:
        """
        生成会话 URL
        
        Args:
            session_id: 会话 ID
            include_token: 是否包含安全令牌
            
        Returns:
            str: 会话 URL
        """
        if include_token:
            token = self._generate_session_token(session_id)
            self._url_tokens[session_id] = token
            url_path = f"/session/{session_id}?token={token}"
        else:
            url_path = f"/session/{session_id}"
        
        full_url = urljoin(self.base_url, url_path)
        debug_log(f"生成会话 URL: {session_id} -> {full_url}")
        return full_url
    
    def validate_session_access(self, session_id: str, token: Optional[str] = None) -> bool:
        """
        验证会话访问权限
        
        Args:
            session_id: 会话 ID
            token: 安全令牌
            
        Returns:
            bool: 是否有访问权限
        """
        # 如果没有设置令牌，允许访问（向后兼容）
        if session_id not in self._url_tokens:
            debug_log(f"会话 {session_id} 没有设置令牌，允许访问")
            return True
        
        # 验证令牌
        expected_token = self._url_tokens.get(session_id)
        if not expected_token:
            debug_log(f"会话 {session_id} 令牌不存在")
            return False
        
        if not token:
            debug_log(f"会话 {session_id} 缺少令牌")
            return False
        
        is_valid = secrets.compare_digest(expected_token, token)
        debug_log(f"会话 {session_id} 令牌验证: {'通过' if is_valid else '失败'}")
        return is_valid
    
    def revoke_session_token(self, session_id: str):
        """
        撤销会话令牌
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._url_tokens:
            del self._url_tokens[session_id]
            debug_log(f"撤销会话 {session_id} 的令牌")
    
    def generate_api_url(self, endpoint: str) -> str:
        """
        生成 API URL
        
        Args:
            endpoint: API 端点路径
            
        Returns:
            str: 完整的 API URL
        """
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        
        return urljoin(self.base_url, endpoint)
    
    def _generate_session_token(self, session_id: str) -> str:
        """
        生成会话安全令牌
        
        Args:
            session_id: 会话 ID
            
        Returns:
            str: 安全令牌
        """
        # 使用会话 ID 和随机数生成令牌
        random_bytes = secrets.token_bytes(16)
        token_data = f"{session_id}:{random_bytes.hex()}"
        
        # 使用 SHA-256 生成最终令牌
        token_hash = hashlib.sha256(token_data.encode()).hexdigest()
        return token_hash[:32]  # 取前32位作为令牌
    
    @classmethod
    def from_env(cls) -> 'URLGenerator':
        """
        从环境变量创建 URL 生成器
        
        Returns:
            URLGenerator: URL 生成器实例
        """
        host = os.getenv('MCP_HTTP_HOST', 'localhost')
        port = int(os.getenv('MCP_HTTP_PORT', '8766'))
        use_https = os.getenv('MCP_USE_HTTPS', '').lower() in ('true', '1', 'yes')
        
        return cls(base_host=host, base_port=port, use_https=use_https)
    
    def get_config_info(self) -> Dict[str, Any]:
        """
        获取配置信息
        
        Returns:
            Dict[str, Any]: 配置信息
        """
        return {
            "base_host": self.base_host,
            "base_port": self.base_port,
            "use_https": self.use_https,
            "base_url": self.base_url,
            "active_tokens": len(self._url_tokens)
        }


# 全局 URL 生成器实例
_url_generator: Optional[URLGenerator] = None


def get_url_generator() -> URLGenerator:
    """获取全局 URL 生成器实例"""
    global _url_generator
    if _url_generator is None:
        _url_generator = URLGenerator.from_env()
    return _url_generator


def set_url_generator(generator: URLGenerator):
    """设置全局 URL 生成器实例"""
    global _url_generator
    _url_generator = generator


def generate_session_url(session_id: str, include_token: bool = True) -> str:
    """
    便捷函数：生成会话 URL
    
    Args:
        session_id: 会话 ID
        include_token: 是否包含安全令牌
        
    Returns:
        str: 会话 URL
    """
    return get_url_generator().generate_session_url(session_id, include_token)


def validate_session_access(session_id: str, token: Optional[str] = None) -> bool:
    """
    便捷函数：验证会话访问权限
    
    Args:
        session_id: 会话 ID
        token: 安全令牌
        
    Returns:
        bool: 是否有访问权限
    """
    return get_url_generator().validate_session_access(session_id, token) 