# MiniHUD × Servux：不开容器读取容器内容 实现分析

> 分析对象：`sakura-ryoko/minihud` 仓库 `26.2` 分支（HEAD `0272ad4`）
> 分析日期：2026-08-05
> 所有结论均经源码交叉验证，证据见文末「验证记录」章节。

---

## 1. 核心结论

MiniHUD 的"容器预览（Inventory Preview）"功能可以在**不打开容器 GUI** 的前提下读取容器内容：

- 客户端**从不发送右键打开容器的数据包**（不触发 `OpenScreen`、不改变容器 `opened` 状态）；
- 而是通过 Fabric 自定义 Payload 通道 **`servux:entity_data`**，按 `BlockPos` 直接向服务端请求该**方块实体（BlockEntity）的完整 NBT**（含 `Items` 物品列表）；
- 服务端 **Servux 插件**返回 NBT 后，客户端解析为 `Container` 并以**悬浮物品栏（Overlay）**渲染；
- 无 Servux 时可降级为**原版 NBT Query**（`/data` 查询协议），但需要 OP 权限。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  渲染/触发层  renderer/InventoryOverlayHandler.java              │
│  - 准星指向容器 → 请求 NBT → 解析 Container → 悬浮渲染            │
│  - 通过 IInventoryOverlayHandler（malilib）接口接入               │
├─────────────────────────────────────────────────────────────────┤
│  数据管理层  data/EntityDataManager.java                          │
│  - 实现 IDataSyncer + IClientTickHandler（malilib）               │
│  - 握手协商 / 请求队列 / 每 tick 限速 / 缓存 / 失败熔断           │
├─────────────────────────────────────────────────────────────────┤
│  协议层  network/ServuxEntitiesHandler.java                       │
│          network/ServuxEntitiesPacket.java                        │
│  - 通道 servux:entity_data，PROTOCOL_VERSION = 2                  │
│  - 包类型定义与编解码                                              │
├─────────────────────────────────────────────────────────────────┤
│  服务端  Servux 插件（sakura-ryoko/servux，外部依赖）              │
│  - 响应 BlockEntity.saveWithFullMetadata()（完整 NBT 含 Items）   │
└─────────────────────────────────────────────────────────────────┘
```

MiniHUD 侧实现代码分布在 3 个 Java 文件 + 1 个外部接口依赖（malilib）：

| 文件 | 职责 |
|---|---|
| `renderer/InventoryOverlayHandler.java` | 触发、NBT→Container 解析、刷新 |
| `data/EntityDataManager.java` | 数据同步中枢（握手/队列/限速/缓存） |
| `network/ServuxEntitiesHandler.java` | payload 收发 |
| `network/ServuxEntitiesPacket.java` | 协议包编解码 |
| malilib `IDataSyncer` / `IInventoryOverlayHandler` | 外部接口默认实现（查缓存/入队/写缓存） |

---

## 3. 完整请求链路（时序）

```
① 加入服务器
   EntityDataManager.onClientTick（每 50ms 一次）
     └─ 首次：注册接收器 + 发 C2S_METADATA_REQUEST {version:2}
   Servux 服务端 ──S2C_METADATA {version:2, servux:"servux-fabric-<MC版本>"}──▶ 客户端
     客户端校验 version==2 且前缀匹配 → servuxServer=true（标记可用）

② 玩家准星指向箱子，按住"容器预览"键（默认 LEFT_ALT，且 inventoryPreviewEnabled=true）
   RenderHandler.onExtractGuiOverlayPost
     └─ InventoryOverlayHandler.getRenderContext(ctx, profiler)
          └─ getTargetInventory(mc)          ← 射线命中方块
               └─ requestBlockEntityAt(world, pos)   ← IInventoryOverlayHandler 默认实现
                    └─ IDataSyncer.requestBlockEntity(world, pos)
                         ├─ 查 EntityDataCache → 命中且超过 refreshTime(0.25s) → 重新入队
                         └─ miss → requestTracker.schedulePendingBlockEntity(pos) 入队

③ EntityDataManager 每 tick 消费队列（限速 serverNbtRequestRate，默认 2 个/tick）
     └─ requestServuxBlockEntityData(pos)
          └─ C2S_BLOCK_ENTITY_REQUEST {BlockPos}            (type=3)

④ Servux 服务端
     └─ 序列化方块实体 NBT（saveWithFullMetadata，含 Items 列表）
          └─ S2C_BLOCK_NBT_RESPONSE_SIMPLE {pos + NBT}      (type=5)

⑤ 客户端 ServuxEntitiesHandler.decodeClientData
     └─ EntityDataManager.handleBlockEntityData(pos, nbt)   ← IDataSyncer 默认实现
          └─ 写入 EntityDataCache（remove + add）

⑥ 下一帧渲染
   InventoryOverlayHandler.getTargetInventoryFromBlock
     └─ IDataSyncer.getBlockInventory(world, pos, false)
          └─ 缓存命中 → InventoryUtils.getDataInventory(nbt, size, registryAccess)
               └─ 解析 Items 槽位 → SimpleContainer → InventoryOverlayScreen 悬浮渲染（不开 GUI）
```

**实体类容器**（村民/马/猪灵/末影箱等）走同构链路：

```
C2S_ENTITY_REQUEST {entityId} (type=4) → S2C_ENTITY_NBT_RESPONSE_SIMPLE (type=6) → handleEntityData → getEntityInventory
```

**末影箱特例**：请求**玩家自己的实体 NBT**，取 `EnderItems` 标签构造 `PlayerEnderChestContainer`（`InventoryOverlayHandler.java:421-449`）。

---

## 4. 协议规范

### 4.1 通道与版本

- 通道 ID：`servux:entity_data`（`ServuxEntitiesHandler.java:32`）
- 协议版本：`PROTOCOL_VERSION = 2`（`ServuxEntitiesPacket.java:26`）
- 包体 = `writeVarInt(type)` + 载荷

### 4.2 包类型（`ServuxEntitiesPacket.java:468-482`）

| type | 方向 | 载荷 | 用途 |
|---|---|---|---|
| 1 | S2C | NBT `{version, servux}` | 握手元数据响应 |
| 2 | C2S | NBT `{version:2}` | 握手请求 |
| 3 | C2S | `BlockPos` | 请求方块实体 NBT（**容器内容请求**） |
| 4 | C2S | `VarInt entityId` | 请求实体 NBT |
| 5 | S2C | `BlockPos + NBT` | 方块实体响应 |
| 6 | S2C | `VarInt + NBT` | 实体响应 |
| 7 | C2S | NBT | 协议不匹配时取消注册 |
| 10/11 | S2C | 分片 START/DATA | Packet Splitter 超大 NBT（>32KB）拆包 |
| 12/13 | C2S | 分片 START/DATA | 同上（反向） |

### 4.3 握手流程（`EntityDataManager.java:380-426`）

1. 客户端发 `C2S_METADATA_REQUEST`，NBT 携带 `version: 2`；
2. 服务端回 `S2C_METADATA`，NBT 携带 `version` 与 `servux`（形如 `servux-fabric-1.21.x`）；
3. 客户端双重校验：`version == PROTOCOL_VERSION` 且 `servux` 前缀为 `servux-<modType>-<MC版本>`；
4. 匹配 → `setIsServuxServer()` 标记可用；不匹配 → 发 `UnregisterReply` + 取消注册 + 禁用功能。

---

## 5. 关键机制设计

### 5.1 请求限速（防滥用）
每 tick（50ms）最多消费 `serverNbtRequestRate`（默认 **2**）个待请求项（`EntityDataManager.java:131-165`），防止请求轰炸拖垮服务器。

### 5.2 两级缓存
- `EntityDataCache`：超时 `entityDataSyncCacheTimeout`（默认 2.75s，备份模式 ×5），刷新间隔 `entityDataSyncCacheRefresh`（默认 0.25s）；
- 缓存 miss 时**不阻塞**：先入队请求并返回 null，下一帧数据到达后再渲染；
- 命中但超时 → 重新入队刷新（`IDataSyncer.requestBlockEntity` 317 行附近）。

### 5.3 大包分片（Packet Splitter）
NBT 超过 MC 数据包大小上限（32767B）时，用 `PACKET_*_NBT_RESPONSE_START(10/12)` + `PACKET_*_NBT_RESPONSE_DATA(11/13)` 切片传输，接收端重组（`ServuxEntitiesPacket.java:104-133`）。

### 5.4 失败熔断
发送 payload 连续失败超过 `maxFailures` → `unregisterPlayReceiver` + `EntityDataManager.onPacketFailure()`（自动禁用 `entityDataSync`），避免反复轰炸（`ServuxEntitiesHandler.java:145-165`）。

### 5.5 备份方案（无 Servux 时）
`entityDataSyncBackup=true` 时降级到原版 NBT Query：`DebugQueryHandler.queryBlockEntityTag/queryEntityTag`（`EntityDataManager.java:445-477`）。**需要 OP 权限**，且服务端 `ENTITY_DATA_SYNC_BACKUP_OPEN_TO_LAN` 可扩展 LAN 场景。

### 5.6 特殊容器合并
- **大箱子**（`ChestType.LEFT/RIGHT`）：自动请求相邻方块实体，合并为 `CompoundContainer`（`IDataSyncer.getBlockInventory` 624 行附近）；
- **Carpet TIS 大木桶**：同样处理相邻方块合并；
- 服务端 NBT 会**直接 load 进客户端本地 BlockEntity**（`handleBlockEntityData` 中 `loadContainerBlockEntities()` 为 true 时执行 `be.loadWithComponents`），连本地 BE 数据都被服务器 NBT 覆盖。

### 5.7 刷新机制
`InventoryOverlayHandler.Refresher.onContextRefresh`（616-638 行）：每次刷新对当前目标重新发起请求（缓存过期后），保持悬浮栏数据实时。

---

## 6. 配置项（`Configs.java`）

| 配置 | 类型/默认 | 说明 |
|---|---|---|
| `entityDataSync` | BooleanHotkeyed / **false** | Servux 实体数据同步总开关 |
| `entityDataSyncBackup` | Boolean / false | 无 Servux 时用原版 NBT Query（需 OP） |
| `entityDataSyncBackupOpenToLan` | Boolean / false | LAN 场景 Backup 包处理覆盖 |
| `entityDataSyncCacheRefresh` | Float / 0.25s | 缓存刷新间隔 |
| `entityDataSyncCacheTimeout` | Float / 2.75s | 缓存超时 |
| `serverNbtRequestRate` | Integer / **2** | 每 tick 最大请求数 |
| `inventoryPreview` | Hotkey / **LEFT_ALT** | 容器预览触发键 |
| `inventoryPreviewEnabled` | Boolean / false | 容器预览总开关（需配合按键） |
| `inventoryPreviewToggleScreen` | Hotkey / BUTTON_3 | 固定悬浮屏开关 |
| `shulkerBoxPreview` | Boolean / false | 潜影盒悬浮预览 |
| `shulkerDisplayEnderChest` | Boolean / false | 末影箱内容预览（经玩家实体 NBT） |

---

## 7. 服务端要求与可移植性

### 服务端要求
- 服务端必须安装 **Servux 插件**（sakura-ryoko/servux，与 MiniHUD 同作者/同协议）并允许实体数据同步；
- 服务端响应体就是标准 `BlockEntity NBT`（`saveWithFullMetadata`），无需额外定制。

### 对 bot 系统（如 vmtools-next 的 MCC/mineflayer 适配）的参考价值
任何能序列化方块实体 NBT 的**服务端插件**都可实现同款协议，让 bot"不开容器查询容器内容"：

```
C2S: {type:3, BlockPos}         → 服务端查该坐标方块实体
S2C: {type:5, BlockPos, NBT}    → 返回完整 NBT（含 Items）
```

关键参考点：
1. **请求按坐标**而非按交互，天然规避"打开容器"；
2. **限速 + 缓存 + 熔断**三件套保证多 bot 并发安全；
3. 协议带**版本握手**，升级兼容性好。

---

## 8. 验证记录（事实 ↔ 源码证据）

| # | 分析结论 | 证据位置（本仓库） |
|---|---|---|
| 1 | 通道为 `servux:entity_data` | `network/ServuxEntitiesHandler.java:32` `CHANNEL_ID` |
| 2 | 协议版本 = 2 | `network/ServuxEntitiesPacket.java:26` |
| 3 | 包类型枚举 1-7 / 10-13 | `network/ServuxEntitiesPacket.java:468-482` |
| 4 | 握手请求携带 version | `data/EntityDataManager.java:380-389` `requestMetadata()` |
| 5 | 握手校验（版本+servux 前缀） | `data/EntityDataManager.java:397-426` `receiveServuxMetadata()` |
| 6 | 每 tick 限速（默认 2） | `data/EntityDataManager.java:131-165`；`config/Configs.java:122` |
| 7 | 方块实体请求 C2S type=3 | `data/EntityDataManager.java:479-485`；`network/ServuxEntitiesPacket.java:90-95` |
| 8 | 实体请求 C2S type=4 | `data/EntityDataManager.java:487-493`；`network/ServuxEntitiesPacket.java:97-102` |
| 9 | 响应分发到 cache | `network/ServuxEntitiesHandler.java:83-87`；malilib `IDataSyncer.java:903-947` |
| 10 | 备份方案（原版 NBT Query，需 OP） | `data/EntityDataManager.java:445-477` |
| 11 | 预览触发条件（按键+开关） | `event/RenderHandler.java:174-178`；`config/Configs.java:90-91` |
| 12 | 容器请求入口 | `renderer/InventoryOverlayHandler.java:226, 406, 415` |
| 13 | `requestBlockEntityAt` 默认实现（委托 IDataSyncer + 双箱） | malilib `IInventoryOverlayHandler.java:131-151` |
| 14 | `getBlockInventory`（缓存→Container，miss→入队） | malilib `IDataSyncer.java:624-773` |
| 15 | 末影箱经玩家实体 NBT 取 EnderItems | `renderer/InventoryOverlayHandler.java:421-449` |
| 16 | 刷新机制 Refresher | `renderer/InventoryOverlayHandler.java:616-638` |
| 17 | 大包分片 | `network/ServuxEntitiesPacket.java:104-133, 259-270, 360-383` |
| 18 | 失败熔断 | `network/ServuxEntitiesHandler.java:145-165`；`data/EntityDataManager.java:428-433` |
| 19 | 相关配置项 | `config/Configs.java:76-93, 122` |
| 20 | MiniHUD 本地旧实现（@Deprecated，与接口方法独立） | `event/RenderHandler.java:1865-1867` |

---

## 9. 参考资料

- MiniHUD 仓库：<https://github.com/sakura-ryoko/minihud>（分支 26.2）
- Servux 服务端插件：<https://github.com/sakura-ryoko/servux>
- malilib 库（接口默认实现来源）：<https://github.com/sakura-ryoko/malilib>
  - `interfaces/IDataSyncer.java`
  - `interfaces/IInventoryOverlayHandler.java`
