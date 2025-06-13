#!/bin/bash
# MCP Feedback Enhanced HTTP 云服务器配置脚本
# 用于快速在云服务器上部署 HTTP MCP 服务

set -e

echo "🚀 MCP Feedback Enhanced HTTP 云服务器配置脚本"
echo "================================================"

# 检测系统类型
if command -v ufw >/dev/null 2>&1; then
    FIREWALL_TYPE="ufw"
elif command -v firewall-cmd >/dev/null 2>&1; then
    FIREWALL_TYPE="firewalld"
else
    FIREWALL_TYPE="none"
fi

# 检测IP地址
INTERNAL_IP=$(hostname -I | awk '{print $1}')
echo "🔍 检测到内网IP: $INTERNAL_IP"

# 获取所有网卡IP
echo "📡 所有网卡IP地址："
ip addr show | grep -E "inet [0-9]" | grep -v "127.0.0.1" | awk '{print "   - " $2}' | cut -d'/' -f1

# 设置默认端口
PORT=8769
echo "🌐 使用端口: $PORT"

# 配置防火墙
echo "🛡️  配置防火墙..."
case $FIREWALL_TYPE in
    "ufw")
        echo "检测到 UFW 防火墙"
        sudo ufw allow $PORT/tcp
        sudo ufw --force enable
        echo "✅ UFW 防火墙配置完成"
        ;;
    "firewalld")
        echo "检测到 FirewallD 防火墙"
        sudo firewall-cmd --permanent --add-port=$PORT/tcp
        sudo firewall-cmd --reload
        echo "✅ FirewallD 防火墙配置完成"
        ;;
    "none")
        echo "⚠️  未检测到防火墙管理工具，请手动配置"
        ;;
esac

# 检查 uv 是否安装
if ! command -v uv >/dev/null 2>&1; then
    echo "❌ 未检测到 uv，请先安装 uv 包管理器"
    echo "安装命令: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 进入项目目录
cd "$(dirname "$0")/.."
echo "📁 项目目录: $(pwd)"

# 安装依赖
echo "📦 安装项目依赖..."
uv sync

# 生成启动命令
COMMAND="uv run python start_http_server.py --host 0.0.0.0 --port $PORT --debug"

echo ""
echo "🎉 配置完成！"
echo "================================================"
echo "📋 部署信息："
echo "   - 内网IP: $INTERNAL_IP"
echo "   - 端口: $PORT"
echo "   - 监听地址: 0.0.0.0 (所有接口)"
echo ""
echo "🚀 启动命令："
echo "   $COMMAND"
echo ""
echo "🔗 访问地址："
echo "   - 本地访问: http://localhost:$PORT/health"
echo "   - 内网访问: http://$INTERNAL_IP:$PORT/health"
echo "   - 公网访问: http://[你的公网IP]:$PORT/health"
echo ""
echo "⚠️  注意事项："
echo "   1. 请确保云服务商安全组已开放端口 $PORT"
echo "   2. 如需后台运行，可使用 nohup 或 systemd 服务"
echo "   3. 生产环境建议使用 HTTPS 和反向代理"
echo ""

# 询问是否立即启动
read -p "🚀 是否立即启动服务？(y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔄 启动服务..."
    exec $COMMAND
else
    echo "👋 配置完成，您可以手动运行启动命令"
fi 