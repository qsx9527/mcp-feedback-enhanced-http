#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP MCP 服务器启动脚本
======================

简化的启动脚本，用于快速启动 HTTP MCP 服务器。

使用方法:
  python start_http_server.py                           # 默认配置启动
  python start_http_server.py --host 0.0.0.0 --port 8767 --debug  # 自定义配置
"""

import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from mcp_feedback_enhanced.http_server import main

if __name__ == "__main__":
    main() 