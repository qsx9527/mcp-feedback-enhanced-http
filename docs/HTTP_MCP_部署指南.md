# HTTP MCP 服务部署指南

## 概述

MCP Feedback Enhanced 现在支持两种运行模式：

1. **Stdio MCP 模式**（原有模式）：通过标准输入输出与 AI 客户端通信
2. **HTTP MCP 模式**（新增模式）：通过 HTTP API 提供 MCP 服务，支持多用户并发访问

## HTTP MCP 模式特点

### 优势
- ✅ **多用户支持**：支持多个用户同时访问
- ✅ **公开部署**：可部署为公开服务
- ✅ **URL 返回**：调用工具时返回交互 URL，用户可复制访问
- ✅ **会话管理**：自动管理用户会话，支持超时清理
- ✅ **安全性**：URL 包含安全令牌，防止未授权访问
- ✅ **易于集成**：标准 HTTP API，易于与各种客户端集成

### 工作流程
1. AI 客户端调用 `interactive_feedback` 工具
2. HTTP MCP 服务器创建会话并返回交互 URL
3. 用户在浏览器中打开 URL 进行交互
4. 用户完成回饋后，结果返回给 AI 客户端

## 部署步骤

### 1. 启动 HTTP MCP 服务器

#### 方法一：使用启动脚本（推荐）
```bash
# 基本启动（仅本地访问）
python start_http_server.py

# 启动并允许外部访问（推荐用于云服务器）
uv run python start_http_server.py --host 0.0.0.0 --port 8769 --debug

# 绑定到特定IP
uv run python start_http_server.py --host 172.16.0.3 --port 8769 --debug

# 仅本地访问
uv run python start_http_server.py --host 127.0.0.1 --port 8769 --debug
```

#### 方法二：使用 Python 命令行
```bash
# 直接调用（适用于开发环境）
python -c "from src.mcp_feedback_enhanced.http_server import main; main()" --host 127.0.0.1 --port 8769 --debug

# 使用模块方式启动（需要先安装包）
python -m mcp_feedback_enhanced http-server --host 0.0.0.0 --port 8767 --debug
```

#### 方法三：使用 Python 脚本启动
```python
import asyncio
from mcp_feedback_enhanced.http_server import HTTPMCPServer

async def main():
    server = HTTPMCPServer(host="0.0.0.0", port=8767)
    await server.start()
    
    try:
        while server.is_running():
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

#### 方法四：使用 Docker 部署
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e .

EXPOSE 8767
CMD ["python", "-m", "mcp_feedback_enhanced", "http-server", "--host", "0.0.0.0", "--port", "8767"]
```

### 2. 配置 AI 客户端

#### Cursor IDE 配置
在 `~/.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "mcp-feedback-enhanced-http": {
      "command": "curl",
      "args": [
        "-X",
        "POST",
        "http://localhost:8767/mcp",
        "-H",
        "Content-Type: application/json",
        "-d",
        "@-"
      ],
      "timeout": 30
    }
  }
}
```

#### 其他 MCP 客户端配置
对于支持 HTTP MCP 的客户端，直接配置 HTTP 端点：
```
HTTP MCP Endpoint: http://localhost:8767/mcp
```

### 3. IP地址配置

#### 自动检测本机IP
```bash
# 获取主要内网IP
INTERNAL_IP=$(hostname -I | awk '{print $1}')
echo "内网IP: $INTERNAL_IP"

# 获取所有网卡IP（排除回环）
ip addr show | grep -E "inet [0-9]" | grep -v "127.0.0.1" | awk '{print $2}' | cut -d'/' -f1
```

#### 云服务器配置说明
```bash
# 云服务器常见情况：
# - 公网IP: 117.72.114.36 (外部访问地址)
# - 内网IP: 172.16.0.3 (服务器实际绑定地址)

# 推荐配置：绑定到 0.0.0.0 监听所有接口
uv run python start_http_server.py --host 0.0.0.0 --port 8769 --debug

# 访问地址：
# - 内网访问: http://172.16.0.3:8769
# - 公网访问: http://117.72.114.36:8769 (需要防火墙开放端口)
# - 本地访问: http://localhost:8769
```

### 4. 环境变量配置

```bash
# 服务器配置
export MCP_HTTP_HOST=0.0.0.0          # 服务器主机地址（0.0.0.0 监听所有接口）
export MCP_HTTP_PORT=8769              # 服务器端口
export MCP_USE_HTTPS=false             # 是否使用 HTTPS

# 调试配置
export MCP_DEBUG=true                  # 启用调试模式

# Web UI 配置
export MCP_WEB_PORT=8766              # Web UI 端口（与 HTTP MCP 端口不同）
```

## 使用示例

### 1. 测试服务器连接

```bash
# 测试健康检查
curl -s http://localhost:8769/health
# 响应: {"status":"healthy","version":"2.3.0","active_sessions":0}

# 测试初始化
curl -X POST http://localhost:8769/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }'

# 测试工具列表
curl -X POST http://localhost:8769/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "tools/list",
    "params": {}
  }'

# 云服务器外部访问测试（替换为你的公网IP）
curl -s http://117.72.114.36:8769/health
```

### 2. 调用交互式回饋工具

```bash
curl -X POST http://localhost:8769/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "tools/call",
    "params": {
      "name": "interactive_feedback",
      "arguments": {
        "project_directory": "/path/to/project",
        "summary": "AI 工作摘要",
        "timeout": 600
      }
    }
  }'
```

响应示例：
```json
{
  "jsonrpc": "2.0",
  "id": "3",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "交互式回饋会话已创建。\n\n请访问以下 URL 进行交互：\nhttp://localhost:8767/session/session_abc123?token=xyz789\n\n..."
      }
    ],
    "session_info": {
      "session_id": "session_abc123",
      "url": "http://localhost:8767/session/session_abc123?token=xyz789",
      "project_directory": "/path/to/project",
      "summary": "AI 工作摘要",
      "timeout": 600
    }
  }
}
```

## 云服务器部署

### 快速部署指南

#### 方法一：使用自动配置脚本（推荐）
```bash
# 进入项目目录
cd /root/project/mcp/mcp-feedback-enhanced-http

# 运行自动配置脚本
bash scripts/setup_cloud_server.sh
```

自动配置脚本将：
- ✅ 自动检测内网IP地址
- ✅ 配置系统防火墙（UFW/FirewallD）
- ✅ 安装项目依赖
- ✅ 生成启动命令
- ✅ 提供访问地址信息

#### 方法二：手动配置

##### 1. 检测并配置IP
```bash
# 进入项目目录
cd /root/project/mcp/mcp-feedback-enhanced-http

# 检测本机IP
INTERNAL_IP=$(hostname -I | awk '{print $1}')
echo "检测到内网IP: $INTERNAL_IP"
echo "公网IP: 请在云服务商控制台查看"

# 安装依赖
uv sync

# 启动服务（推荐绑定到 0.0.0.0）
uv run python start_http_server.py --host 0.0.0.0 --port 8769 --debug
```

##### 2. 防火墙配置
```bash
# Ubuntu/Debian 系统
sudo ufw allow 8769
sudo ufw reload

# CentOS/RHEL 系统  
sudo firewall-cmd --permanent --add-port=8769/tcp
sudo firewall-cmd --reload

# 检查端口是否开放
netstat -tlnp | grep 8769
```

##### 3. 云服务商安全组配置
在云服务商控制台添加安全组规则：
- **协议**: TCP
- **端口范围**: 8769
- **源地址**: 0.0.0.0/0 (允许所有IP) 或特定IP段
- **描述**: MCP HTTP Server

##### 4. 访问测试
```bash
# 本地测试
curl -s http://localhost:8769/health

# 内网测试
curl -s http://172.16.0.3:8769/health

# 公网测试（从其他机器）
curl -s http://117.72.114.36:8769/health
```

##### 5. 创建系统服务（可选）
```bash
# 创建服务文件
sudo tee /etc/systemd/system/mcp-http.service > /dev/null <<EOF
[Unit]
Description=MCP Feedback Enhanced HTTP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/project/mcp/mcp-feedback-enhanced-http
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/root/.local/bin/uv run python start_http_server.py --host 0.0.0.0 --port 8769
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启用并启动服务
sudo systemctl daemon-reload
sudo systemctl enable mcp-http
sudo systemctl start mcp-http

# 检查服务状态
sudo systemctl status mcp-http
```

## 生产环境部署

### 1. 使用反向代理

#### Nginx 配置示例
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /mcp {
        proxy_pass http://localhost:8769;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /session/ {
        proxy_pass http://localhost:8769;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        proxy_pass http://localhost:8766;  # Web UI 静态文件
    }
}
```

### 2. 使用 HTTPS

```bash
# 设置 HTTPS
export MCP_USE_HTTPS=true
export MCP_HTTP_HOST=your-domain.com
export MCP_HTTP_PORT=443
```

### 3. 使用进程管理器

#### systemd 服务配置
```ini
[Unit]
Description=MCP Feedback Enhanced HTTP Server
After=network.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/opt/mcp-feedback-enhanced
Environment=MCP_HTTP_HOST=0.0.0.0
Environment=MCP_HTTP_PORT=8769
Environment=MCP_DEBUG=false
ExecStart=/opt/mcp-feedback-enhanced/.venv/bin/uv run python start_http_server.py --host 0.0.0.0 --port 8769
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 监控和维护

### 1. 健康检查

```bash
# 检查服务器状态
curl http://localhost:8769/health

# 检查活跃会话
curl http://localhost:8769/sessions

# 云服务器公网访问检查
curl http://117.72.114.36:8769/health
```

### 2. 日志监控

```bash
# 启用调试日志
export MCP_DEBUG=true

# 查看服务器日志
tail -f /var/log/mcp-feedback-enhanced.log
```

### 3. 会话管理

- 会话自动超时清理
- 支持手动清理过期会话
- 内存使用监控

## 故障排除

### 启动方式选择

根据您的环境选择合适的启动方式：

1. **云服务器部署（推荐）**：绑定到所有接口
   ```bash
   uv run python start_http_server.py --host 0.0.0.0 --port 8769 --debug
   ```

2. **本地开发环境**：仅本地访问
   ```bash
   uv run python start_http_server.py --host 127.0.0.1 --port 8769 --debug
   ```

3. **指定内网IP**：绑定到特定网卡
   ```bash
   uv run python start_http_server.py --host 172.16.0.3 --port 8769 --debug
   ```

4. **直接调用方式**：适用于需要自定义 Python 路径的情况
   ```bash
   python -c "from src.mcp_feedback_enhanced.http_server import main; main()" --host 0.0.0.0 --port 8769 --debug
   ```

### 常见问题

1. **模块无法识别 http-server 命令**
   - 问题：`python -m mcp_feedback_enhanced http-server` 报错 "unrecognized arguments"
   - 解决：使用 `start_http_server.py` 或直接调用方式

2. **端口冲突**
   ```bash
   # 检查端口占用
   netstat -tlnp | grep 8769
   
   # 使用不同端口
   uv run python start_http_server.py --host 0.0.0.0 --port 8768
   ```

3. **权限问题**
   ```bash
   # 确保用户有权限访问项目目录
   chmod 755 /path/to/project
   ```

4. **防火墙设置**
   ```bash
   # Ubuntu/Debian 开放端口
   sudo ufw allow 8769
   
   # CentOS/RHEL 开放端口
   sudo firewall-cmd --permanent --add-port=8769/tcp
   sudo firewall-cmd --reload
   ```

5. **模块导入错误**
   - 问题：`ModuleNotFoundError: No module named 'mcp_feedback_enhanced'`
   - 解决：确保在项目根目录运行，或使用 `start_http_server.py`

## 性能优化

### 1. 并发设置

```python
# 在 http_server.py 中调整 uvicorn 配置
config = uvicorn.Config(
    self.app,
    host=self.host,
    port=self.port,
    workers=4,  # 增加工作进程
    loop="uvloop"  # 使用更快的事件循环
)
```

### 2. 会话清理策略

```python
# 调整会话清理间隔
session_manager.cleanup_interval = 30  # 30秒清理一次
```

## 安全考虑

1. **URL 令牌**：每个会话 URL 包含唯一的安全令牌
2. **会话超时**：自动清理过期会话
3. **访问控制**：可配置 IP 白名单
4. **HTTPS 支持**：生产环境建议使用 HTTPS
5. **输入验证**：所有输入都经过验证和清理

## 总结

HTTP MCP 模式为 MCP Feedback Enhanced 提供了更强大的部署选项，支持多用户并发访问和公开部署。通过返回交互 URL 的方式，用户可以方便地在浏览器中进行回饋交互，同时保持了原有的所有功能特性。 