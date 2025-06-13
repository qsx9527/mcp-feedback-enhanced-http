#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Interactive Feedback Enhanced - 主程式入口
==============================================

此檔案允許套件透過 `python -m mcp_feedback_enhanced` 執行。

使用方法:
  python -m mcp_feedback_enhanced        # 啟動 MCP 伺服器
  python -m mcp_feedback_enhanced test   # 執行測試
"""

import sys
import argparse
import os

def main():
    """主程式入口點"""
    parser = argparse.ArgumentParser(
        description="MCP Feedback Enhanced Enhanced - 互動式回饋收集 MCP 伺服器"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 伺服器命令（預設）
    server_parser = subparsers.add_parser('server', help='啟動 MCP 伺服器（預設）')
    
    # HTTP 伺服器命令
    http_parser = subparsers.add_parser('http-server', help='啟動 HTTP MCP 伺服器')
    http_parser.add_argument('--host', default='localhost', help='服務器主機地址')
    http_parser.add_argument('--port', type=int, default=8766, help='服務器端口')
    http_parser.add_argument('--debug', action='store_true', help='啟用調試模式')
    
    # 測試命令
    test_parser = subparsers.add_parser('test', help='執行測試')
    test_parser.add_argument('--web', action='store_true', help='測試 Web UI (自動持續運行)')
    test_parser.add_argument('--gui', action='store_true', help='測試 Qt GUI (快速測試)')
    test_parser.add_argument('--enhanced', action='store_true', help='執行增強 MCP 測試 (推薦)')
    test_parser.add_argument('--scenario', help='運行特定的測試場景')
    test_parser.add_argument('--tags', help='根據標籤運行測試場景 (逗號分隔)')
    test_parser.add_argument('--list-scenarios', action='store_true', help='列出所有可用的測試場景')
    test_parser.add_argument('--report-format', choices=['html', 'json', 'markdown'], help='報告格式')
    test_parser.add_argument('--timeout', type=int, help='測試超時時間 (秒)')
    
    # 版本命令
    version_parser = subparsers.add_parser('version', help='顯示版本資訊')
    
    args = parser.parse_args()
    
    if args.command == 'test':
        run_tests(args)
    elif args.command == 'version':
        show_version()
    elif args.command == 'server':
        run_server()
    elif args.command == 'http-server':
        run_http_server(args)
    elif args.command is None:
        run_server()
    else:
        # 不應該到達這裡
        parser.print_help()
        sys.exit(1)

def run_server():
    """啟動 MCP 伺服器"""
    from .server import main as server_main
    return server_main()

def run_http_server(args):
    """啟動 HTTP MCP 伺服器"""
    if args.debug:
        os.environ["MCP_DEBUG"] = "true"
    
    # 設置環境變數
    os.environ["MCP_HTTP_HOST"] = args.host
    os.environ["MCP_HTTP_PORT"] = str(args.port)
    
    # 直接导入并运行 HTTP 服务器
    import asyncio
    from .http_server import HTTPMCPServer
    
    async def run_server():
        server = HTTPMCPServer(host=args.host, port=args.port)
        await server.start()
        
        try:
            # 保持服务器运行
            while server.is_running():
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("收到中断信号")
        finally:
            await server.stop()
    
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("服务器已停止")

def run_tests(args):
    """執行測試"""
    # 啟用調試模式以顯示測試過程
    os.environ["MCP_DEBUG"] = "true"

    if args.enhanced or args.scenario or args.tags or args.list_scenarios:
        # 使用新的增強測試系統
        print("🚀 執行增強 MCP 測試系統...")
        import asyncio
        from .test_mcp_enhanced import MCPTestRunner, TestConfig

        # 創建配置
        config = TestConfig.from_env()
        if args.timeout:
            config.test_timeout = args.timeout
        if args.report_format:
            config.report_format = args.report_format

        runner = MCPTestRunner(config)

        async def run_enhanced_tests():
            try:
                if args.list_scenarios:
                    # 列出測試場景
                    tags = args.tags.split(',') if args.tags else None
                    runner.list_scenarios(tags)
                    return True

                success = False

                if args.scenario:
                    # 運行特定場景
                    success = await runner.run_single_scenario(args.scenario)
                elif args.tags:
                    # 根據標籤運行
                    tags = [tag.strip() for tag in args.tags.split(',')]
                    success = await runner.run_scenarios_by_tags(tags)
                else:
                    # 運行所有場景
                    success = await runner.run_all_scenarios()

                return success

            except Exception as e:
                print(f"❌ 增強測試執行失敗: {e}")
                return False

        success = asyncio.run(run_enhanced_tests())
        if not success:
            sys.exit(1)

    elif args.web:
        print("🧪 執行 Web UI 測試...")
        from .test_web_ui import test_web_ui, interactive_demo
        success, session_info = test_web_ui()
        if not success:
            sys.exit(1)
        # Web UI 測試自動啟用持續模式
        if session_info:
            print("📝 Web UI 測試完成，進入持續模式...")
            print("💡 提示：服務器將持續運行，可在瀏覽器中測試互動功能")
            print("💡 按 Ctrl+C 停止服務器")
            interactive_demo(session_info)
    elif args.gui:
        print("🧪 執行 Qt GUI 測試...")
        from .test_qt_gui import test_qt_gui
        if not test_qt_gui():
            sys.exit(1)
    else:
        # 默認執行增強測試系統的快速測試
        print("🧪 執行快速測試套件 (使用增強測試系統)...")
        print("💡 提示：使用 --enhanced 參數可執行完整測試")

        import asyncio
        from .test_mcp_enhanced import MCPTestRunner, TestConfig

        config = TestConfig.from_env()
        config.test_timeout = 60  # 快速測試使用較短超時

        runner = MCPTestRunner(config)

        async def run_quick_tests():
            try:
                # 運行快速測試標籤
                success = await runner.run_scenarios_by_tags(["quick"])
                return success
            except Exception as e:
                print(f"❌ 快速測試執行失敗: {e}")
                return False

        success = asyncio.run(run_quick_tests())
        if not success:
            sys.exit(1)

        print("🎉 快速測試通過！")
        print("💡 使用 'test --enhanced' 執行完整測試套件")

def show_version():
    """顯示版本資訊"""
    from . import __version__, __author__
    print(f"MCP Feedback Enhanced Enhanced v{__version__}")
    print(f"作者: {__author__}")
    print("GitHub: https://github.com/Minidoracat/mcp-feedback-enhanced")

if __name__ == "__main__":
    main() 