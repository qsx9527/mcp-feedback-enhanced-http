#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP MCP 客户端使用示例
======================

演示如何通过 HTTP API 调用 MCP Feedback Enhanced 服务。

使用方法：
1. 启动 HTTP MCP 服务器：
   python -m mcp_feedback_enhanced http-server --host 127.0.0.1 --port 8767

2. 运行此示例：
   python examples/http_mcp_client_example.py
"""

import json
import requests
from typing import Dict, Any


class HTTPMCPClient:
    """HTTP MCP 客户端"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8767"):
        self.base_url = base_url
        self.mcp_endpoint = f"{base_url}/mcp"
        self.request_id = 1
    
    def _make_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送 JSON-RPC 请求"""
        payload = {
            "jsonrpc": "2.0",
            "id": str(self.request_id),
            "method": method,
            "params": params or {}
        }
        
        self.request_id += 1
        
        try:
            response = requests.post(
                self.mcp_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": f"请求失败: {e}"}
    
    def initialize(self) -> Dict[str, Any]:
        """初始化 MCP 连接"""
        return self._make_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {
                "name": "http-mcp-client-example",
                "version": "1.0.0"
            }
        })
    
    def list_tools(self) -> Dict[str, Any]:
        """获取可用工具列表"""
        return self._make_request("tools/list")
    
    def call_interactive_feedback(
        self,
        project_directory: str = ".",
        summary: str = "AI 工作完成的摘要",
        timeout: int = 600
    ) -> Dict[str, Any]:
        """调用交互式回饋工具"""
        return self._make_request("tools/call", {
            "name": "interactive_feedback",
            "arguments": {
                "project_directory": project_directory,
                "summary": summary,
                "timeout": timeout
            }
        })
    
    def check_health(self) -> Dict[str, Any]:
        """检查服务器健康状态"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": f"健康检查失败: {e}"}


def main():
    """主函数 - 演示 HTTP MCP 客户端使用"""
    print("🚀 HTTP MCP 客户端示例")
    print("=" * 50)
    
    # 创建客户端
    client = HTTPMCPClient()
    
    # 1. 检查服务器健康状态
    print("\n1️⃣ 检查服务器健康状态...")
    health = client.check_health()
    if "error" in health:
        print(f"❌ 服务器不可用: {health['error']}")
        print("\n💡 请确保 HTTP MCP 服务器正在运行：")
        print("   python -m mcp_feedback_enhanced http-server --host 127.0.0.1 --port 8767")
        return
    
    print(f"✅ 服务器健康: {health}")
    
    # 2. 初始化 MCP 连接
    print("\n2️⃣ 初始化 MCP 连接...")
    init_result = client.initialize()
    if "error" in init_result:
        print(f"❌ 初始化失败: {init_result['error']}")
        return
    
    print(f"✅ 初始化成功: {init_result.get('result', {}).get('serverInfo', {})}")
    
    # 3. 获取工具列表
    print("\n3️⃣ 获取可用工具...")
    tools_result = client.list_tools()
    if "error" in tools_result:
        print(f"❌ 获取工具失败: {tools_result['error']}")
        return
    
    tools = tools_result.get("result", {}).get("tools", [])
    print(f"✅ 可用工具数量: {len(tools)}")
    for tool in tools:
        print(f"   • {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}")
    
    # 4. 调用交互式回饋工具
    print("\n4️⃣ 调用交互式回饋工具...")
    feedback_result = client.call_interactive_feedback(
        project_directory="/home/qinsx/Project/MCP/mcp-feedback-enhanced-2",
        summary="""🎉 HTTP MCP 客户端示例测试

✅ 测试内容：
• HTTP MCP 协议通信
• 工具调用和响应
• 会话创建和 URL 生成
• 客户端集成示例

请在返回的 URL 中提供您的回饋！""",
        timeout=300
    )
    
    if "error" in feedback_result:
        print(f"❌ 调用失败: {feedback_result['error']}")
        return
    
    result = feedback_result.get("result", {})
    content = result.get("content", [])
    session_info = result.get("session_info", {})
    
    print("✅ 交互式回饋工具调用成功！")
    
    # 显示返回的文本内容
    if content:
        print(f"\n📝 返回内容:")
        for item in content:
            if item.get("type") == "text":
                print(item.get("text", ""))
    
    # 显示会话信息
    if session_info:
        print(f"\n📊 会话信息:")
        print(f"   • 会话 ID: {session_info.get('session_id', 'N/A')}")
        print(f"   • 交互 URL: {session_info.get('url', 'N/A')}")
        print(f"   • 项目目录: {session_info.get('project_directory', 'N/A')}")
        print(f"   • 超时时间: {session_info.get('timeout', 'N/A')} 秒")
        print(f"   • 状态: {session_info.get('status', 'N/A')}")
    
    print(f"\n🎯 使用说明:")
    print(f"1. 复制上面的交互 URL")
    print(f"2. 在浏览器中打开 URL")
    print(f"3. 在 Web 界面中提供回饋")
    print(f"4. 点击'提交回饋'完成交互")
    
    print(f"\n✨ HTTP MCP 客户端示例完成！")


if __name__ == "__main__":
    main() 