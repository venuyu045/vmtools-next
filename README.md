# VenusMcTools-Web

Minecraft Console Client (MCC) 一站式远程管理平台。无需 SSH 登录服务器，打开浏览器即可完成 MCC 多实例创建、账号配置、启动/停止、实时终端、在线文件编辑，以及在线监控与消息通知等全部操作。

> 本平台是 [VMTools v3](../README.md) 项目的服务端部分，基于无头的 MCC 运行在 Linux 服务器上；对应的客户端 Mod 见 [`VenusMcTools-Mod/`](../VenusMcTools-Mod/)。

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

> ⚠️ **生产环境启动注意**：数据库为相对路径的 SQLite，若从错误目录启动 uvicorn 会创建一个新的空库，导致机器人、实例、账号等全部数据「消失」。生产环境必须从项目根目录（含真实数据库的目录）启动，详见 [`docs/server-ops-guide.md`](./docs/server-ops-guide.md)。

## 目录结构

```
VenusMcTools-Web/
├── backend/                      # Python FastAPI 后端
│   ├── src/vmtools_next/         # 源码
│   │   ├── api/routers/          # REST 路由（auth/mcc_instances/mcc_bot/monitor…）
│   │   ├── core/                 # 核心服务（进程管理/BlueMap/QQ通知/建造引擎…）
│   │   ├── adapters/             # MCC / QQ Bot / Litematica 适配器
│   │   ├── plugins/builtin/      # 内置插件（自动补货/Discord 通知）
│   │   └── data/                 # 数据模型与迁移
│   ├── config/                   # 配置文件
│   ├── static/                   # 前端构建产物（自动生成）
│   ├── tests/                    # pytest 测试
│   └── pyproject.toml            # Python 依赖
├── frontend/                     # Vue 3 前端源码
│   ├── src/                      # TypeScript/Vue 源码
│   └── package.json              # Node 依赖
├── mcc/                          # MCC 运行时与实例数据
├── Dockerfile                    # 多阶段构建
├── docker-compose.yml            # Docker 编排
├── .env.example                  # 环境变量模板
├── start.sh                      # 一键部署脚本
├── docs/                         # 文档
│   ├── mcc-deployment-guide.md   # 部署指南
│   └── server-ops-guide.md       # 运维手册
└── README.md
```

## 功能

- **MCC 进程生命周期管理** — 启动 / 停止 / 重启 / 自动重连
- **多实例隔离** — 独立目录、端口、日志
- **账号配置管理** — 离线 / Microsoft / Yggdrasil
- **Web Terminal 实时终端** — ConPTY + xterm，ANSI 渲染
- **在线文件管理** — 浏览 / 编辑 / 上传 / 下载 / 删除
- **BlueMap 玩家监控** — 轮询地图 API，检测机器人真实上下线
- **QQ / Discord 通知** — 上线、下线、崩溃、自动重连事件推送
- **仓库 / 材料 / 建造引擎** — 服务端物流与建造调度
- **CRT 像素风 Web UI**
- **JWT 认证 + Socket.IO 安全校验**
- **操作审计日志**

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy · SQLite |
| 实时通信 | python-socketio + Socket.IO |
| 前端 | Vue 3 · TypeScript · Vite · Element Plus |
| 终端 | @xterm/xterm + ConPTY |
| 图表 | ECharts |
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
# 或指定端口运行
.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 9090

# 前端（开发服务器）
cd frontend
npm install
npm run dev

# 前端构建（产物输出到 backend/static/）
cd frontend
npm run build

# 测试
cd backend
pytest tests/ -q
```
