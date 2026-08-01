

# VenusMcTools-Web

Minecraft Console Client (MCC) 一站式远程管理平台。无需 SSH 登录服务器，打开浏览器即可完成 MCC 多实例创建、账号配置、启动/停止、实时终端、在线文件编辑，以及在线监控与消息通知等全部操作。

> 本平台是 [VMTools v3](../README.md) 项目的服务端部分，基于无头的 MCC/Mineflayer 运行在 Linux 服务器上。

## 特性

*   **多实例隔离管理** — 独立目录、端口、日志，支持同时管理多个 MCC/Mineflayer 实例。
*   **Web Terminal** — 基于 ConPTY 与 xterm.js 的真实终端体验，支持 ANSI 颜色渲染。
*   **自动化物流** — 完整的仓库、路径点配置，支持自动化取放任务 (Logistics Runner)。
*   **自动化建造** — 支持 Litematica 投影解析、自动层建造、缺失方块验证。
*   **像素画构建** — 多机器人协作的大型像素画分区构建系统。
*   **BlueMap 监控** — 实时轮询地图 API，精确检测机器人与玩家的上下线状态。
*   **即时通知** — 实例上线、下线、崩溃、自动重连事件通过 QQ / Discord 实时推送。
*   **安全审计** — 完整的 JWT 认证体系与操作审计日志。

## 技术栈

| 层 | 技术选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy · SQLite |
| 实时通信 | python-socketio (WebSocket) |
| 前端 | Vue 3 · TypeScript · Vite · Element Plus |
| 终端 | @xterm/xterm · ConPTY |
| 图表 | ECharts |
| 部署 | Docker · Docker Compose |

## 快速开始

### 1. 准备环境

确保已安装 Python 3.11+ 和 Node.js 20+。

### 2. 准备 MCC 程序

```bash
# 创建运行时目录
mkdir -p /opt/vmtools/mcc-runtime
# 将 MinecraftClient.exe/dll 放入该目录 (确保 MCP 协议端口开放)
```

### 3. 配置与启动

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置 (必须修改 VMT_SECRET_KEY)
vim .env

# 启动服务 (会自动初始化数据库)
chmod +x start.sh
./start.sh
```

浏览器打开 `http://<服务器IP>:8080` 即可访问。

> **⚠️ 生产环境注意**：数据库默认为相对路径的 SQLite。请务必从项目根目录启动 `uvicorn`，否则会新建一个空数据库，导致所有配置和实例数据丢失。详细运维手册见 [`docs/server-ops-guide.md`](./docs/server-ops-guide.md)。

## 项目结构

```
vmtools-next/
├── backend/                      # Python FastAPI 后端
│   ├── src/vmtools_next/         # 核心源码
│   │   ├── api/routers/          # REST API 路由 (auth/mcc_instances/logistics/build…)
│   │   ├── core/                 # 核心业务逻辑
│   │   │   ├── mcc_process_manager.py # 进程守护与终端管理
│   │   │   ├── logistics_runner.py    # 物流自动化引擎
│   │   │   ├── build_state_machine.py # 建造状态机
│   │   │   ├── warehouse_scanner.py   # 仓储扫描器
│   │   │   └── map_art_coordinator.py # 像素画协调器
│   │   ├── adapters/             # 适配器层
│   │   │   ├── mcc/              # MCC 适配器 (McpClient, SessionPool)
│   │   │   ├── mineflayer/       # Mineflayer 适配器 (WebSocket Bridge)
│   │   │   └── qqbot/            # QQ Bot 通知适配器
│   │   ├── plugins/              # 插件系统
│   │   │   ├── builtin/          # 内置插件 (自动补货/Discord通知)
│   │   │   └── manager.py        # 插件管理器
│   │   └── data/                 # 数据模型 (SQLAlchemy Models)
│   ├── config/                   # YAML 配置文件
│   ├── static/                   # 前端构建产物
│   ├── tests/                    # 单元测试
│   └── pyproject.toml            # 依赖管理
├── frontend/                     # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── views/                # 页面视图 (Terminal/Dashboard/Logistics…)
│   │   ├── components/           # 公共组件
│   │   └── api/                  # Axios 接口封装
│   └── package.json
├── mcc/                          # MCC 实例数据与日志
├── deploy/                       # 部署脚本与配置
│   ├── install.sh                # 一键安装脚本
│   ├── nginx/                    # Nginx 配置
│   └── systemd/                  # Systemd 服务单元
├── .env.example                  # 环境变量模板
├── docker-compose.yml            # Docker 编排配置
└── README.md
```

## 环境变量说明

在 `.env` 文件中配置：

| 变量 | 描述 | 默认值 |
|---|---|---|
| `VMT_SECRET_KEY` | **必须修改。** 用于 JWT 签名加密。 | - |
| `VMT_PORT` | Web 服务端口 | 8080 |
| `SITE_ADMIN_GAME_ID` | 初始管理员游戏ID | admin |
| `SITE_ADMIN_PASSWORD` | 初始管理员密码 (MD5/SHA256 校验) | - |
| `MCC_RUNTIME_PATH` | MCC 程序 (exe/dll) 所在目录 | /opt/vmtools/mcc-runtime |
| `MCC_INSTANCE_ROOT` | 实例数据存储根目录 | /opt/vmtools/mcc-instances |
| `MCC_PORT_RANGE` | MCP 协议端口分配范围 | 33333-33352 |

## 开发指南

### 后端开发

```bash
cd backend

# 安装依赖
pip install -e ".[dev]"

# 初始化数据库
python -m vmtools_next.data.db init_db  # 或直接运行 main.py

# 启动开发服务器 (热重载)
python -m vmtools_next.main
# 或指定端口
uvicorn main:app --host 0.0.0.0 --port 9090 --reload

# 运行测试
pytest tests/ -q
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本 (输出到 backend/static)
npm run build
```

## 功能模块详解

### 1. 实例管理 (Instances)
支持通过 API 创建、启动、停止 MCC 实例。进程管理器会自动处理崩溃重启，并监听 MCP 端口以实现重连后的数据同步。

### 2. 物流系统 (Logistics)
*   **Waypoints (路径点):** 定义常用的传送坐标。
*   **Warehouses (仓库):** 配置物流中心坐标，用于存放材料。
*   **Task Templates (任务模板):** 定义自动化逻辑，如“从仓库取64个石头放到建造点”。

### 3. 建造系统 (Building)
*   **Projection (投影):** 上传 Litematica 投影文件，系统会自动解析所需材料。
*   **Printer (打印):** 根据投影逐层打印，自动补充缺失方块。
*   **Verification (验证):** 对比当前世界与投影，报告缺失或错误的方块。

### 4. 机器人 (Bots)
除了 MCC，还支持 **Mineflayer** 机器人。通过 WebSocket 桥接协议连接，支持与 MCC 类似的操作（移动、放置、交互、物品栏管理）。

## 部署建议

*   **生产环境**: 推荐使用 Docker 或 Systemd 服务。
    ```bash
    # 使用 Docker Compose
    docker-compose up -d

    # 或使用 Systemd (见 deploy/systemd/)
    # sudo cp deploy/systemd/vmtools-next.service /etc/systemd/system/
    # sudo systemctl enable vmtools-next && sudo systemctl start vmtools-next
    ```
*   **反向代理**: 推荐使用 Nginx 监听 80/443 端口，并将请求转发至 8080 端口。

## 许可证

本项目遵循 MIT 许可证开源，详见 [LICENSE](LICENSE) 文件。