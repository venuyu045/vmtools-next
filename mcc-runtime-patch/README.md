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
