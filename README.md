# VMTools-Web（vmtools-next）

基于无头 **Minecraft Console Client (MCC)** 与 **Mineflayer** 双引擎的 Minecraft Bot 一站式远程管理平台。无需 SSH 登录服务器，在浏览器中即可完成多实例管理、Web 终端、自动化物流、多机器人协作建造等全部操作。

> 本平台是 VMTools v3 项目的服务端部分，运行在 Linux 服务器上（Ubuntu 20.04+ / Debian 11+）。

## 主要特性

- **双引擎多实例管理**：MCC（MCP 协议）与 Mineflayer（WebSocket Bridge）两套 bot 引擎，独立目录/端口/日志，支持同时管理最多 20 个实例；Web 终端（xterm.js + PTY）、在线文件管理、账号配置。
- **自动化物流**：仓库扫描（含潜影盒递归、Servux 直读容器）、路径点、取放点与任务模板配置，Logistics Runner 自动化取放任务。
- **自动化建造**：Litematica 投影解析、材料清单计算、自动分层建造、缺失方块验证与补放。
- **地图画多 Bot 协作**：大型像素画列式/分区两种建造模式，多机器人排内并行、减员容错、断点续建、进度落盘。
- **战斗与挂机**：可配置攻击半径（最高 64 格）、守护/挂机模式、玩家预警与追踪。
- **任务中心**：定时任务调度、任务模板、批量执行。
- **BlueMap 监控**：轮询地图 API，精确检测机器人与玩家上下线状态。
- **即时通知**：实例上下线、崩溃、自动重连事件通过 QQ 机器人实时推送。
- **组织官网**：内置「理想乡」组织主页（介绍 / 成员 / 基地 / 相册），成员头像自动使用其 MC ID 的正版皮肤，自带管理后台。
- **插件系统**：插件启停与在线配置管理。
- **安全**：JWT 认证、角色权限（site_admin / admin / user）、操作审计日志、登录限流。

## 技术栈

| 层级 | 技术选型 |
| :--- | :--- |
| **后端** | Python 3.11+ · FastAPI · SQLAlchemy · SQLite（生产可换 PostgreSQL） |
| **Bot 引擎（Node）** | Node.js 20+ · Mineflayer · 自研 baritone-path 寻路（A* + 分块） |
| **实时通信** | python-socketio (WebSocket) |
| **前端** | Vue 3 · TypeScript · Vite · Element Plus |
| **终端** | @xterm/xterm + PTY |
| **图表 / 3D** | ECharts · Three.js |
| **部署** | Docker · Docker Compose · Systemd · Nginx |

## 快速开始（Docker，推荐）

```bash
# 1. 克隆项目
git clone https://gitee.com/de-spider/vmtools-next.git
cd vmtools-next

# 2. 准备环境变量（必须修改 VMT_SECRET_KEY）
cp .env.example .env
vim .env

# 3. 一键启动（或直接 docker compose up -d --build）
chmod +x start.sh
./start.sh
```

访问 `http://<服务器IP>:8080` 即可使用。

### 环境变量说明（`.env`）

| 变量 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `VMT_SECRET_KEY` | **必须修改。** JWT 签名密钥（≥32 位随机串） | - |
| `VMT_PORT` | Web 服务端口 | 8080 |
| `SITE_ADMIN_GAME_ID` | 初始管理员游戏 ID | admin |
| `SITE_ADMIN_PASSWORD` | 初始管理员密码 | - |
| `MCC_RUNTIME_PATH` | MCC 程序目录（存放 MinecraftClient.exe/dll），挂载为只读 | /opt/vmtools/mcc-runtime |
| `MCC_INSTANCE_ROOT` | MCC 实例数据目录 | /opt/vmtools/mcc-instances |
| `MCC_PORT_RANGE` | MCP 协议端口分配范围 | 33333-33352 |

## 非 Docker 部署（裸机 / systemd）

```bash
# 后端（入口 backend/main.py，从 backend/ 目录启动）
cd backend
pip install -e .
uvicorn main:app --host 0.0.0.0 --port 8080

# 前端构建产物由后端托管，如改过前端需要重新构建
cd ../frontend && npm install && npm run build
```

裸机部署的配置走 YAML：复制 `backend/config/config.yaml.example` 为 `backend/config/config.yaml` 并修改 `server.secret_key`（缺失或为默认值时服务拒绝启动）；可用 `config.dev.yaml` / `config.prod.yaml` 区分环境（`VMT_ENV` 选择），`VMT_` 前缀环境变量优先级最高（如 `VMT_SERVER__SECRET_KEY`）。

Systemd / Nginx / 一键安装脚本见 `backend/deploy/`（`systemd/`、`nginx/`、`install.sh`）。

> **⚠️ SQLite 路径警告**：默认 `database_url: "sqlite:///vmtools-next.db"` 是**相对于启动 uvicorn 时的当前目录**的。请固定用一个启动目录，或生产环境直接在 `config.yaml` 里把 `server.database_url` 改为绝对路径，否则换个目录启动就会新建空库，看起来像配置和实例数据"丢失"。详见 `docs/server-ops-guide.md`。

## 开发指南

```bash
# 后端
cd backend
pip install -e ".[dev]"
pytest tests/ -q                    # 运行测试
python -m vmtools_next.main         # 开发服务器（热重载）

# 前端
cd frontend
npm run dev                         # 开发服务器
npm run build                       # 生产构建 → 输出到 backend/static/（随 git 提交）

# Mineflayer bot 侧
cd mineflayer-bots
npm install
```

> 前端构建产物直接进 git（`backend/static/`），改完前端必须重新 `npm run build` 后提交，服务器拉取即生效。

## 项目结构

```
vmtools-next/
├── backend/                      # Python FastAPI 后端
│   ├── src/vmtools_next/
│   │   ├── api/routers/          # REST API 路由（auth/mcc_instances/logistics/build_map_art/lixiangxiang…）
│   │   ├── core/                 # 核心业务逻辑
│   │   │   ├── mcc_process_manager.py     # MCC 进程守护与终端管理
│   │   │   ├── mineflayer_process_manager.py # Mineflayer 进程守护
│   │   │   ├── logistics_runner.py        # 物流自动化引擎
│   │   │   ├── build_state_machine.py     # 建造状态机
│   │   │   ├── map_art_coordinator.py     # 地图画单 Bot 协调
│   │   │   ├── multi_bot_coordinator.py   # 地图画多 Bot 列式协作
│   │   │   ├── warehouse_scanner.py       # 仓库扫描器（含 Servux 直读）
│   │   │   ├── bluemap_monitor.py         # BlueMap 在线状态监控
│   │   │   └── task_engine.py             # 任务中心引擎
│   │   ├── adapters/             # 适配器层（mcc / mineflayer / qqbot / litematica）
│   │   └── data/                 # SQLAlchemy 数据模型
│   ├── config/                   # YAML 配置（config.yaml 为本地配置，gitignored）
│   ├── deploy/                   # 部署脚本（install.sh / nginx / systemd / Dockerfile）
│   ├── static/                   # 前端构建产物（含 item-icons 1231 张）
│   └── tests/                    # 单元测试
├── frontend/                     # Vue 3 + TypeScript 前端
│   └── src/{views,components,api}/
├── mineflayer-bots/              # Mineflayer bot 进程（Node.js）
│   ├── bot_main.js               # 进程入口（WS Bridge 连接平台）
│   ├── handlers/                 # 行为模块（移动/方块/背包/战斗/睡觉/Servux…）
│   └── baritone-path/            # 自研寻路（A* + executor + world 分类）
├── docs/                         # 运维与部署文档
├── .env.example                  # 环境变量模板
├── docker-compose.yml            # Docker 编排
└── start.sh                      # 一键启动脚本
```

## 相关文档

- [服务器运维手册](docs/server-ops-guide.md)
- [MCC 部署指南](docs/mcc-deployment-guide.md)

## 许可证

本项目遵循 **MIT** 许可证开源，详见 [LICENSE](LICENSE) 文件。
