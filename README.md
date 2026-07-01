# VMTools Next

Minecraft Console Client (MCC) 一站式远程管理平台。无需 SSH 登录服务器，打开浏览器即可完成 MCC 多实例创建、账号配置、启动/停止、实时终端、在线文件编辑等全部操作。

## 快速开始

```bash
# 1. 准备 MCC 程序
mkdir -p /opt/vmtools/mcc-runtime
# 将 MinecraftClient.exe/dll 放入该目录

# 2. 配置并启动
cp .env.example .env
# 编辑 .env，设置 VMT_SECRET_KEY

chmod +x start.sh
./start.sh
```

浏览器打开 `http://<服务器IP>:8080` 即可使用。

## 目录结构

```
VMTools_NEXT/
├── backend/                  # Python FastAPI 后端
│   ├── src/vmtools_next/     # 源码
│   ├── config/               # 配置文件
│   ├── static/               # 前端构建产物（自动生成）
│   └── pyproject.toml        # Python 依赖
├── frontend/                 # Vue 3 前端源码
│   ├── src/                  # TypeScript/Vue 源码
│   └── package.json          # Node 依赖
├── Dockerfile                # 多阶段构建
├── docker-compose.yml        # Docker 编排
├── .env.example              # 环境变量模板
├── start.sh                  # 一键部署脚本
├── docs/                     # 文档
│   └── mcc-deployment-guide.md
└── README.md
```

## 功能

- MCC 进程生命周期管理（启动/停止/重启）
- 多实例隔离（独立目录、端口、日志）
- 账号配置管理（离线/Microsoft/Yggdrasil）
- Web Terminal 实时终端（xterm + ANSI 渲染）
- 在线文件管理（浏览/编辑/上传/下载/删除）
- CRT 像素风 Web UI
- JWT 认证 + Socket.IO 安全校验
- 操作审计日志

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy + SQLite |
| 实时通信 | python-socketio + Socket.IO |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus |
| 终端 | @xterm/xterm |
| 部署 | Docker + Docker Compose |

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VMT_SECRET_KEY` | JWT 签名密钥（**必须修改**） | - |
| `VMT_PORT` | HTTP 端口 | 8080 |
| `SITE_ADMIN_GAME_ID` | 管理员账号 | admin |
| `SITE_ADMIN_PASSWORD` | 管理员密码 | - |
| `MCC_RUNTIME_PATH` | MCC 程序目录 | /opt/vmtools/mcc-runtime |
| `MCC_INSTANCE_ROOT` | 实例数据目录 | /opt/vmtools/mcc-instances |
| `MCC_PORT_RANGE` | MCP 端口范围 | 33333-33352 |

完整配置见 `.env.example` 和 `docs/mcc-deployment-guide.md`。

## 开发

```bash
# 后端
cd backend
pip install -e ".[dev]"
python -m vmtools_next.main

# 前端（开发服务器）
cd frontend
npm install
npm run dev

# 测试
cd backend
pytest tests/ -q
```
