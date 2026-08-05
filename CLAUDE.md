# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**VMTools-Web（vmtools-next）** 是一个基于无头 Minecraft Console Client (MCC) / Mineflayer 运行的 Minecraft bot 远程管理平台。用户无需 SSH 登录服务器，在浏览器中即可完成：

- **MCC/Mineflayer 多实例管理** — 创建、启动/停止、账号配置、Web 终端、在线文件编辑
- **自动化物流** — 仓库、路径点、任务模板配置，自动化取放任务 (Logistics Runner)
- **自动化建造** — Litematica 投影解析、自动分层建造、缺失方块验证
- **像素画/地图画构建** — 多机器人协作的大型二维平面分区构建系统
- **BlueMap 监控** — 轮询地图 API，检测 bot 与玩家上下线状态
- **即时通知** — 上下线/崩溃/重连事件通过 QQ / Discord 实时推送

运行在 Linux 服务器上（Ubuntu 20.04+ / Debian 11+），服务端与之配套的移动端/桌面端为 [VMTools v3](../README.md)。

### 技术栈

| 层 | 技术选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy · SQLite (生产中可用 PostgreSQL) |
| 实时通信 | python-socketio (WebSocket) |
| 前端 | Vue 3 · TypeScript · Vite · Element Plus |
| 终端 | @xterm/xterm（前端）+ ConPTY/PTY（后端） |
| 图表/3D | ECharts · Three.js |
| 部署 | Docker · Docker Compose · Systemd · Nginx |

---

## 常用命令

### 后端开发

```bash
cd backend

# 安装依赖（含 dev 依赖）
pip install -e ".[dev]"

# 初始化数据库
python -m vmtools_next.data.db init_db        # 或直接运行 main.py

# 启动开发服务器（热重载）
python -m vmtools_next.main
# 或
uvicorn main:app --host 0.0.0.0 --port 9090 --reload

# 运行测试
pytest tests/ -q
```

### 前端开发

```bash
cd frontend

npm install
npm run dev          # 开发服务器
npm run build        # 生产构建 → 输出到 backend/static/
```

### 生产部署

```bash
# Docker Compose
docker compose up -d --build

# 或 Systemd（见 deploy/systemd/）
# sudo cp deploy/systemd/vmtools-next.service /etc/systemd/system/
# sudo systemctl enable vmtools-next && systemctl start vmtools-next
```

**注意：** 前端构建产物输出到 `backend/static/`，由后端服务。改完前端需重新 `npm run build` 才生效。

---

## ⚠️ 关键注意事项（务必阅读）

### 1. SQLite 数据库路径 = 启动目录决定数据归属

数据库是**相对路径** `vmtools-next.db`，取决于你从哪个目录启动 uvicorn：

| 启动目录 | 数据库位置 | 结果 |
|---|---|---|
| `vmtools-next/`（项目根）✅ | `vmtools-next/vmtools-next.db` | **正确，含真实生产数据 (89MB)** |
| `backend/` ❌ | `backend/vmtools-next.db` | **空库！等于数据全丢** |

> **所有启动/重启命令必须从项目根目录执行**，否则会新建空数据库导致配置和实例数据"丢失"。详见 `docs/server-ops-guide.md`。

### 2. 不要在建造中的 bot 上手动输入终端命令

正在参与建造任务的 bot 若被玩家通过终端手动干扰（移动/操作），可能破坏建造一致性。相关逻辑见 `docs/dev/prompt-building-system.md` 需求八。

### 3. MCC `.ini` 前置配置

建造/物流功能依赖 MCC MCP Plugin，需在实例的 `MinecraftClient.ini` 中启用：

```ini
[InventoryHandling]
enabled = true      # 物品栏操作（物流/建造硬前提）

[TerrainAndMovements]
enabled = true      # 地形/移动/方块扫描（方块扫描硬前提）

[McpPlugin]
enabled = true      # MCP 插件本身
```

若未启用，MCP 的物品栏和方块方法全部不可用。

---

## 项目结构

```
vmtools-next/
├── backend/                        # Python FastAPI 后端
│   ├── src/vmtools_next/           # 核心源码
│   │   ├── api/
│   │   │   ├── routers/            # REST API 路由
│   │   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   │   ├── deps.py             # 依赖注入
│   │   │   └── socketio_handlers.py# Socket.IO 事件处理
│   │   ├── core/                   # 核心业务逻辑
│   │   │   ├── mcc_process_manager.py    # MCC 进程守护+终端管理 (55KB，最复杂)
│   │   │   ├── mineflayer_process_manager.py
│   │   │   ├── mcc_instance_service.py
│   │   │   ├── logistics_runner.py       # 物流自动化引擎
│   │   │   ├── task_engine.py            # 通用任务引擎
│   │   │   ├── build_engine.py           # 建造引擎
│   │   │   ├── build_state_machine.py    # 建造状态机 (18 状态)
│   │   │   ├── map_art_coordinator.py    # 像素画/地图画多 bot 协调器
│   │   │   ├── warehouse_scanner.py      # 仓储扫描器
│   │   │   ├── inventory_scanner.py      # 背包扫描器
│   │   │   ├── material_calculator.py    # 材料计算
│   │   │   ├── bluemap_monitor.py        # BlueMap 上下线监控
│   │   │   ├── mcc_file_service.py       # 实例文件管理
│   │   │   ├── conpty.py                 # PTY 终端实现
│   │   │   ├── qqbot_notify.py           # QQ 通知
│   │   │   ├── safety_manager.py         # 安全防护
│   │   │   └── dataclasses.py            # 数据类定义
│   │   ├── adapters/               # 适配器层
│   │   │   ├── abstract/           # 抽象接口 (AbstractBotAgent 等)
│   │   │   ├── mcc/                # MCC 适配器
│   │   │   │   ├── mcc_mcp_client.py  # MCP JSON-RPC 客户端 (65+ 方法)
│   │   │   │   ├── mcc_session_pool.py# MCP 会话池
│   │   │   │   ├── mcc_printer.py     # 逐块放置
│   │   │   │   ├── mcc_litematica.py  # 投影解析+方块验证
│   │   │   │   ├── mcc_baritone.py    # Baritone 寻路
│   │   │   │   └── mcc_minihud.py
│   │   │   ├── mineflayer/         # Mineflayer 适配器 (WebSocket Bridge)
│   │   │   ├── litematica/         # .litematic NBT 解析
│   │   │   └── qqbot/              # QQ bot 通知
│   │   ├── plugins/                # 插件系统
│   │   │   ├── builtin/            # 内置插件 (自动补货/Discord 通知)
│   │   │   └── manager.py          # 插件管理器
│   │   ├── data/                   # 数据层
│   │   │   ├── db.py               # SQLAlchemy + Socket.IO 实例
│   │   │   ├── models/             # ORM 模型
│   │   │   └── migration/          # Alembic 迁移
│   │   ├── infra/                  # 基础设施
│   │   ├── config.py               # Pydantic Settings 配置
│   │   ├── main.py                 # FastAPI 应用入口
│   │   └── __init__.py
│   ├── config/                     # YAML 配置文件
│   ├── static/                     # 前端构建产物（被打包+服务）
│   ├── tests/                      # pytest 测试
│   ├── alembic/                    # 数据库迁移
│   ├── main.py
│   └── pyproject.toml              # 依赖与打包
├── frontend/                       # Vue 3 + TS 前端
│   ├── src/
│   │   ├── views/                  # 页面视图
│   │   ├── components/             # 公共组件
│   │   ├── composables/            # 组合式函数 (含 useSocketIO.ts)
│   │   ├── stores/                 # Pinia 状态
│   │   ├── api/                    # Axios 接口封装
│   │   ├── router/                 # 路由
│   │   └── ...
│   └── package.json
├── mineflayer-bots/                # Mineflayer bot 脚本 (Node.js)
│   ├── bot_main.js
│   ├── mineflayer_bot.js
│   ├── handlers/
│   ├── ws_protocol.js              # WebSocket 桥接协议
│   ├── pathfinder_setup.js
│   └── test_mock_ws_server.js
├── mcc/                            # MCC 实例数据与日志 (!!!! 注意: 仓库提示不追踪本目录 !!!!)
├── deploy/                         # 部署脚本 (install.sh / nginx / systemd)
├── docs/                           # 项目文档
│   ├── dev/
│   │   ├── mcc-capability-verification.md   # MCC MCP 能力验证
│   │   └── prompt-building-system.md        # 地图画建造系统开发提示词
│   ├── mcc-deployment-guide.md     # MCC 部署与运维指南
│   └── server-ops-guide.md         # 服务器运维协作指南
├── mineflayer-bots/
├── .env.example                    # 环境变量模板
├── docker-compose.yml
├── Dockerfile
└── start.sh
```

---

## 架构与数据流

### 双通道 MCC 数据交互

```
                    ┌────────────────────────────────────────────┐
前端 (Vue) ←→ FastAPI 后端                                        │
                    │                                            │
                    ├─ 通道 A: MCP HTTP API (JSON-RPC 2.0)       │
                    │   结构化数据：物品栏/方块/实体/玩家状态      │
                    │   客户端: adapters/mcc/mcc_mcp_client.py   │
                    │                                            │
                    ├─ 通道 B: stdout PIPE (进程日志)             │
                    │   人类可读文本：断联/上下线/终端展示          │
                    │   管理: core/mcc_process_manager.py        │
                    │                                            │
                    └──→ MCC 子进程 (实际控制 Minecraft bot)     │
                    └──→ Mineflayer 子进程 (WebSocket 桥接)      │
                        └───────────────┘
```

> **重要设计原则：** 结构化数据永远走通道 A（MCP），终端日志仅用于事件检测与展示。不要用终端输出解析结构化数据。

### 地图画多 bot 建造流程

```
上传 .litematic → 解析投影 → 二维矩阵 {x,z: block_id}
→ 按 Z 轴分区给 N 个 bot (partition_rectangular)
→ 每个 bot 独立 BotBuildLoop (逐行 Z，站在北边缘向南放置，按颜色分组)
→ 进度每 2s 或每 10 块经 Socket.IO 推送 (room: "build_{task_id}")
```

关键模块：`core/map_art_coordinator.py`（协调器+BotBuildLoop）、`adapters/mcc/mcc_litematica.py`（解析+验证）、`adapters/mcc/mcc_printer.py`（放置）、`core/material_calculator.py`（材料）。

---

## 环境变量

在 `.env` 中配置（模板见 `.env.example`）：

| 变量 | 描述 | 默认值 |
|---|---|---|
| `VMT_SECRET_KEY` | **必须修改** JWT 签名密钥（≥32 字符） | - |
| `VMT_PORT` | Web 服务端口 | 8080 |
| `SITE_ADMIN_GAME_ID` | 初始管理员游戏 ID | admin |
| `SITE_ADMIN_PASSWORD` | 初始管理员密码（MD5/SHA256 校验） | - |
| `MCC_RUNTIME_PATH` | MCC 程序 (exe/dll) 所在目录 | /opt/vmtools/mcc-runtime |
| `MCC_INSTANCE_ROOT` | 实例数据存储根目录 | /opt/vmtools/mcc-instances |
| `MCC_PORT_RANGE` | MCP 协议端口分配范围 | 33333-33352 |
| `VMT_MCC__MAX_INSTANCES` | 最大实例数 | 20 |
| `VMT_MCC__LOG_RETENTION_DAYS` | 终端日志保留天数 | 14 |

后端所有配置通过 Pydantic Settings 读取（`backend/src/vmtools_next/config.py`），命名采用 `VMT_<SECTION>__<KEY>` 双下划线分隔。

---

## 关键实现要点

### MCC MCP 客户端 (`adapters/mcc/mcc_mcp_client.py`)
- 基于 JSON-RPC 2.0 over HTTP POST，封装 **65+ 方法**
- 常用方法：`get_inventory_snapshot`、`place_block`、`move_to`、`look_at`、`send_chat`、`open_container_at`、`withdraw_container_item`、`scan_nearby_blocks`、`get_world_block_at`、`list_entities` 等
- `mcc_session_pool.py` 提供会话池复用/并发管理

### 建造状态机 (`core/build_state_machine.py`)
- 18 状态状态机（`CHECK_INVENTORY → ... → BUILD_LAYER → VERIFY` 等）
- 状态常量以 `Xxx.STATE` 形式定义，用 `BuildStateMachine` 类维护

### 地图画协调器 (`core/map_art_coordinator.py`)
- `partition_rectangular(width, depth, n)`：按 Z 轴切成 N 条等宽 strip，每 bot 覆盖完整 X 范围
- `BotBuildLoop`：单 bot 独立循环，站在行北边缘（z-1）向南放置，按颜色分组减少换手
- 补货：使用 EssentialsX 传送点（`WAREHOUSE_HOME="mdssj"` 仓库、`TEMP_HOME="gzqy"` 建造点），`/esethome` → `/ehomes` 往返，通过 `scan_nearby_blocks` 找箱子后 `open_container_at` + `withdraw_container_item`
- `_active_coordinators` 全局注册表管理活跃任务

### Socket.IO 实时事件
- 全局实例：`vmtools_next.data.db.sio`
- 建造房间：`build_{task_id}`
- 关键事件：`build_progress`、`build_bot_status`、`build_map_init`、`bot_status_update`、`sync_update`
- 处理逻辑见 `api/socketio_handlers.py`

### BlueMap 监控 (`core/bluemap_monitor.py`)
- 轮询 BlueMap 地图 API（**BlueMap 5.16 新端点**），精确检测 bot/玩家上下线
- 端点：`/maps/{world}/live/players.json`（玩家，5s）、`/maps/{world}/live/markers.json`（标记，30s）
- **解析全部 6 个标记集**：Residences（领地）、folia-regions（区域性能 TPS/MSPT）、markers（行政）、mangopassport-landmarks（服务器地标，含类型）、folia-metro-lines（地铁线路）、folia-metro-stations（地铁站点）
- 通过 `/settings.json` 动态发现世界列表（不硬编码）
- 缓存落库 `bluemap_cache` 表，Socket.IO 推送 `regions_update` / `residences_update` / `markers_update` / `landmarks_update` / `metro_lines_update` / `metro_stations_update`
- 相关路由 `api/routers/bluemap_api.py`（含 `/landmarks`、`/metro-lines`、`/metro-stations`、`/worlds`）、`api/routers/player_tracking.py`
- 地标类型从 detail HTML 提取（正则 `类型[:：]([^<，,]+?)(?=<br|坐标|$)`），`lineColor` 用 `_rgba_to_css` 转 CSS 颜色

---

## 测试

- 后端测试用 pytest，`asyncio_mode = "auto"`（pytest-asyncio）
- 测试路径：`backend/tests/`
- 相关依赖：`respx`（mock HTTP）、`httpx`
- 运行：`cd backend && pytest tests/ -q`

---

## 代码风格约定

- 后端遵循 Python 类型注解，使用 dataclass 定义领域模型（见 `core/dataclasses.py`）
- MCP 返回结构统一为 `{"data": ..., ...}`，解析时用 `result.get("data", result)` 兼容两种形态
- 日志使用 `loguru`（生产）与内置 `logging`（部分模块）
- 前端使用 Vue 3 `<script setup>` + TypeScript + Pinia stores + axios 封装 + socket.io-client
- 所有影响实例/配置/终端/文件的操作都应写审计日志（`core/mcc_audit_log_service.py`）

---

## 前端页面速查

| 路由/文件 | 功能 |
|---|---|
| `DashboardView.vue` | 仪表盘 |
| `BotManageView.vue` | Bot 管理主页（实例卡片+终端+账号+文件三合一） |
| `MccInstanceListView.vue` | MCC 实例列表 |
| `MccTerminalView.vue` / `MccFileManagerView.vue` | 全屏终端 / 文件管理器 |
| `BuildTaskListView.vue` / `BuildTaskDetailView.vue` | 建造任务列表 / 详情 |
| `MapArtTaskList.vue` / `MapArtBuildView.vue` | 地图画任务 / 地图画 3D 构建视图 |
| `LogisticsWaypointView.vue` / `WarehouseListView.vue` / `LogisticsRunView.vue` 等 | 物流系统页面 |
| `PlayerTrackingView.vue` | 玩家追踪 |
| `MonitorView.vue` | 系统监控 |
| `MiaomiaoView.vue` | （喵喵）工具页：领地排行榜 / 标记点目录 / **服务器地标（按类型分类）** / **地铁线路+站点** / MSPT排行榜 |
| `PluginView.vue` / `ConfigView.vue` | 插件 / 配置 |