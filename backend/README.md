# VMTools Next

> VMTools-v3 客户端 Mod → 基于 MCC MCP 的 Linux 服务器端自动化方案

## 概述

VMTools Next 是 VMTools-v3 客户端 Fabric Mod 的服务器端重构版本，基于 MCC (Minecraft Console Client) 的 MCP HTTP API 实现仓库扫描、材料管理、货运物流和投影建造的完整自动化能力。

## 技术栈

- **后端**: Python 3.11+ / FastAPI / Socket.IO / SQLAlchemy
- **MCC 集成**: 纯 MCP HTTP API (http://127.0.0.1:33333/mcp)
- **投影解析**: nbtlib 解析 .litematic 文件
- **部署**: Docker / systemd / Nginx

## 快速开始

### 开发环境

```bash
# 安装依赖
pip install -e ".[dev]"

# 初始化数据库
alembic upgrade head

# 启动服务
python -m vmtools_next.main
```

### Docker 部署

```bash
cd deploy
docker-compose up -d
```

## 配置

主配置文件: `config/config.yaml`
环境变量覆盖: `VMT_*` 前缀 (如 `VMT_SERVER_PORT=9090`)

## 文档

- 架构设计: `../C:\Users\35359\.workbuddy\plans\swift-beacon-lovelace.md`
- MCC MCP 接口: `../Minecraft-Console-Client-master/MinecraftClient/Mcp/IMccMcpCapabilities.cs`

## License

MIT
