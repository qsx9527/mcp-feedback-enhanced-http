#!/bin/bash

echo "🔍 查找正在运行的 start_http_server.py 进程..."

PIDS=$(ps aux | grep start_http_server.py | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "✅ 没有找到运行中的 start_http_server.py 进程。"
else
    echo "⚠️ 找到以下进程: $PIDS"
    echo "⛔ 正在尝试终止这些进程..."
    kill -9 $PIDS
    echo "✅ 所有进程已终止。"
fi
