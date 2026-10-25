# MCC 26.3 适配补丁（client_tick_end）

## 背景

粉丝服 2026-10 维护后升级到 **Minecraft 26.3（协议 777）**。26.3 服务端新增规则：
**每个客户端 tick 只允许一个位移包**，且计数器**只在收到 serverbound `client_tick_end` 包时重置**。

原版客户端自 **1.21.2** 起每个 tick 结束都会发 `client_tick_end`；MCC（Minecraft Console Client）
与 mineflayer 都**从未发送过该包**，因此：

```
You were kicked from main: 收到了包含非法玩家移动的数据包
（multiplayer.disconnect.invalid_player_movement）
```

进入服务器 1~2 秒后必被踢，且 AutoRelog 会不断重连 → 正是公告里说的「重复进出服提示」。

## 修复

在客户端 tick 循环里，每次 `handler.OnUpdate()` 之后补发一个空的 `client_tick_end`（协议 1.21.2–26.2 才发）。

- 补丁文件：`mcc-519-client_tick_end.patch`（相对 MCC tag `20260929-519` 的 `Protocol18.cs`）
- 验证：本机 + 生产机均以 `26.1`/`26.2` 连接 `sy.server.mangocraft.cn:35553`，连续运行 5~6 分钟 **0 次被踢**

## 构建步骤（容器 1.8G 内存也能过）

```bash
# 1) 取源码
curl -sSL -o mcc519.tar.gz https://codeload.github.com/MCCTeam/Minecraft-Console-Client/tar.gz/refs/tags/20260929-519
tar xzf mcc519.tar.gz && cd Minecraft-Console-Client-20260929-519

# 2) 补 ConsoleInteractive 子模块（注意目录要嵌套两层）
curl -sSL -o ci.tgz https://codeload.github.com/breadbyte/ConsoleInteractive/tar.gz/refs/heads/main
mkdir -p ConsoleInteractive && tar xzf ci.tgz -C /tmp/ci
cp -r /tmp/ci/ConsoleInteractive-main/ConsoleInteractive ConsoleInteractive/
mkdir -p ConsoleInteractive/ConsoleInteractive/ConsoleInteractive
mv ConsoleInteractive/ConsoleInteractive/*.cs ConsoleInteractive/ConsoleInteractive/ConsoleInteractive.csproj \
   ConsoleInteractive/ConsoleInteractive/ConsoleInteractive/

# 3) 打补丁
patch -p1 < mcc-519-client_tick_end.patch

# 4) 装 .NET 10 SDK（系统无 libicu 时必须加 DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1）
curl -sSL -o dotnet-sdk.tar.gz https://dotnetcli.azureedge.net/dotnet/Sdk/10.0.100/dotnet-sdk-10.0.100-linux-x64.tar.gz
mkdir -p /tmp/dotnet && tar xzf dotnet-sdk.tar.gz -C /tmp/dotnet
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 PATH=/tmp/dotnet:$PATH

# 5) 还原依赖（NuGet 慢，可加 --disable-parallel）
cd MinecraftClient && dotnet restore

# 6) 发布单文件（必须关分析器 + 单进程，否则 1.8G 机器 OOM）
dotnet publish -c Release -r linux-x64 --self-contained true \
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:EnableCompressionInSingleFile=true -m:1 \
  -p:RunAnalyzers=false -p:EnableNETAnalyzers=false -p:UseSharedCompilation=false \
  -o /tmp/mcc-publish
# 产物：/tmp/mcc-publish/MinecraftClient（约 86 MB）
```

## 部署

```bash
scp -C /tmp/mcc-publish/MinecraftClient root@106.12.180.13:/opt/vmtools-next/mcc-runtime/MinecraftClient-20261025-26.3-linux-x64
ssh root@106.12.180.13 'chmod +x /opt/vmtools-next/mcc-runtime/MinecraftClient-20261025-26.3-linux-x64'
```

各实例的 `mcc_binary_path` / `launch_command_json` 指向新文件（旧 445 二进制保留可回滚）。
⚠️ 该二进制**必须带 libicu 或设 `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`**；生产机有 libicu 74，可直接跑。

## 回滚

把实例的 `mcc_binary_path` 与 `launch_command_json` 指回
`/opt/vmtools-next/mcc-runtime/MinecraftClient-20260523-445-linux-x64`，重启实例即可。

---

## 附：MCC 2.0 迁移结论（2026-10-26 更新 —— 已迁移）

> ⚠️ **本节原写「暂不迁移」，理由「2.0 只有 14 个 MCP 工具」是错的** —— 那 14 个是官方文档里
> 列的示例，实际 `tools/list` 返回 **63 个**，平台 `_TOOL_NAME_MAP` 需要的 **61 个一个不缺**。
> 已纠正并完成迁移，原错误结论保留在 git 历史里供复盘。

### 实测数据

| 项目 | MCC 1.x（519） | MCC 2.0（2.0.0-ea13） |
|---|---|---|
| 协议上限 | 26.2（776），26.3 靠 Velocity 的 Via 翻译 | **26.3（777）原生**（UMPK 协议库） |
| MCP 工具数 | 内置 61 个（平台映射的） | 插件 **63 个**，覆盖平台需要的全部 61 个 |
| 连接表现 | 需 `client_tick_end` 补丁 | 原生支持，无需补丁 |
| 配置格式 | `MinecraftClient.ini` | `configurations/*.toml` |
| MCP | 内置，读 `MCC_MCP_PORT` 环境变量 | 官方 `mcp-server` 插件，读 `settings.toml` 的 `Port` |

实测连接 `sy.server.mangocraft.cn:35553` 输出 `Connecting as: 26.3 (Protocol: 777)`，
`Server was successfully joined`；MCP 端点握手成功，`mcc_session_status` 正常返回。

### 三个必踩的坑（都已实测确认）

1. **`SessionCache` 必须是 `none`** —— 2.0 的会话缓存**不保存 authlib 服务器地址**，
   靠缓存续期会退回 Mojang `sessionserver.mojang.com`，LittleSkin 账号必然
   `Session join was rejected by the session server`。
   （排查提示：curl 直连 LittleSkin 的 `sessionserver/session/minecraft/join` 一直返回 204
   正常，说明不是网络/限流，是 2.0 换了目标地址。）
2. **必须给 stdin 持续喂输入，且断线重连要重喂** —— 控制台读到 EOF 就退出；
   自动重连会**重新提示** Yggdrasil 账号密码。
3. **绝不能预先把账号密码写进 stdin** —— 配置未就绪或已连上时会被 REPL 当成**聊天内容
   发到服务器公屏**（2026-10-25 泄露事故的直接原因）。只在看到 `Yggdrasil username`
   提示时才写。

### 迁移工具

- `scripts/hw/migrate_mcc2.py`（工作区文档仓库）：1.x INI → 2.0 TOML + 插件配置 + 启动命令
- `scripts/hw/start-mcc2.sh`：FIFO 常驻运行，只在认证提示出现时喂密码
- 平台侧：`core/mcc_process_manager.py` 的 `_is_mcc2_binary` / `_prepare_mcc2_mcp_config`
  / `_feed_mcc2_credentials` / `_read_mcc2_credentials`

### 2.0 二进制

`/opt/vmtools-next/mcc-runtime/Mcc-2.0.0-ea13-26.3-linux-x64`（66 MB，
MD5 `26ea73c8744ae169564bc242c728d702`），从 `feat/mcc-2.0` 源码用 .NET 10 自建单文件。
构建注意：`global.json` 要求 SDK 10.0.401，容器里是 10.0.100 → 改 `global.json`；
仍需 `-m:1 -p:RunAnalyzers=false -p:EnableNETAnalyzers=false` 防 Roslyn OOM。
