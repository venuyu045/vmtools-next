# MCC 能力验证文档

> 验证日期：2026-07-28
> 目的：确认 MCC MCP Plugin 在 bot 进入服务器后可用的数据采集能力，为后续功能开发提供依据。

---

## 1. 实时背包物品数据

### 结论：✅ 可以，已有完整实现

### MCP 工具（8 个物品栏方法）

| 方法名 | 功能 | 状态 |
|--------|------|------|
| `GetInventorySnapshot(inventoryId=0)` | 获取指定物品栏快照（id=0=玩家背包） | ✅ 已实现 |
| `ListInventories` | 列出所有可用物品栏 | ✅ 已实现 |
| `SearchInventories` | 跨所有物品栏搜索物品 | ✅ 已实现 |
| `OpenContainerAt` | 在指定坐标打开容器 | ✅ 已实现 |
| `CloseContainer` | 关闭容器 | ✅ 已实现 |
| `InventoryWindowAction` | 物品栏槽位操作（LeftClick/RightClick/ShiftClick/Drop） | ✅ 已实现 |
| `WithdrawContainerItem` | 从容器提取物品 | ✅ 已实现 |
| `DepositContainerItem` | 向容器存入物品 | ✅ 已实现 |
| `DropInventoryItem` | 丢弃物品 | ✅ 已实现 |

### 现有封装

**文件：** `backend/src/vmtools_next/core/inventory_scanner.py`

```python
class InventoryScanner:
    async def scan(self) -> dict[str, int]:
        """扫描玩家背包，返回 {item_id: count}"""
        result = await self._mcc.get_inventory_snapshot(inventory_id=0)
        items = {}
        for slot in result.get("items", []):
            item_type = slot.get("type", "")
            count = slot.get("count", 0)
            if item_type and item_type != "minecraft:air" and count > 0:
                items[item_type] = items.get(item_type, 0) + count
        return items
```

### 现有集成

- `BuildStateMachine.CHECK_INVENTORY` 阶段已使用此扫描器
- `WarehouseScanner` 用于仓库容器批量扫描（Semaphore(16) 控制 NBT 背压）

### 缺失

- 没有直接面向前端的 REST API 端点
- 没有 Socket.IO 实时推送事件

---

## 2. 周围方块实时数据

### 结论：⚠️ 部分可用，但有限制

### MCP 工具（3 个方块查询方法）

| 方法名 | 功能 | 参数 | 状态 |
|--------|------|------|------|
| `GetWorldBlockAt` | 查询单个坐标的方块 | `(x, y, z)` | ✅ 已验证 |
| `ScanNearbyBlocks` | 扫描周围方块 | `(radius=16, maxCount=100, materialFilter?)` | ⚠️ 未验证 |
| `FindBlocks` | 搜索特定类型方块 | `(query?, radius=32, maxCount=100, exactMatch?)` | ⚠️ 未验证 |

### GetWorldBlockAt — 已验证可用

**文件：** `backend/src/vmtools_next/adapters/mcc/mcc_litematica.py`

`MccLitematicaAdapter` 已在建造验证流程中大量使用此方法：

```python
# 逐块验证投影中的方块是否已正确放置
actual = await self._mcc.get_world_block_at(x, y, z)
# 返回: {"success": True, "name": "minecraft:stone", ...}
```

**限制：** 单坐标查询，多方块需循环调用（`get_extra_block_count` 限制 256 次/调用）。

### ScanNearbyBlocks — 存在但未测试

```python
async def scan_nearby_blocks(self, radius: int = 16, max_count: int = 100,
                              material_filter: Optional[str] = None) -> dict:
```

**⚠️ 关键限制：**
- `max_count` 默认 100，可能无法覆盖大范围内的所有方块
- 该 MCP 工具在项目中**没有任何调用记录**（grep 仅命中方法定义）
- 底层依赖 MCC 的 `Terrain and Movements` 配置必须为 `enabled`
- MCC WebSocket API 官方文档**不包含**此命令，说明它是 MCP Plugin 的扩展功能

### FindBlocks — 存在但未测试

```python
async def find_blocks(self, query: Optional[str] = None, radius: int = 32,
                       max_count: int = 100, exact_match: bool = False) -> dict:
```

**设计用途：** 按类型搜索方块（如搜索所有箱子），**不适用于**获取范围内全部方块。

### 底层依赖

MCC 的"区块 → 方块"映射取决于：
1. `TerrainAndMovements` 在 `MinecraftClient.ini` 中设置为 `true`
2. 目标坐标所在 chunk 已被服务器发送到客户端（bot 需要在范围内或移动过）
3. 范围扫描的性能受网络延迟和服务器视距限制

---

## 3. 其他已验证的 MCP 能力

| 类别 | 方法 | 状态 |
|------|------|------|
| 玩家状态 | `GetPlayerState` | ✅ |
| 世界状态 | `GetWorldState` | ✅ |
| 聊天 | `SendChat` / `RunInternalCommand` | ✅ |
| 移动 | `MoveTo` / `LookAt` | ✅ |
| 实体 | `ListEntities` / `GetEntityInfo` | ✅ |
| 方块操作 | `PlaceBlock` / `DigBlock` | ✅ |
| 玩家列表 | `GetPlayersList` / `GetPlayersDetailed` | ✅ |
| 物品映射 | `GetItemTypeMappings` / `GetBlockTypesList` | ✅ |
| 断开 | `DisconnectClient` / `Respawn` | ✅ |

---

## 4. 待验证项

| 序号 | 待验证能力 | 优先级 | 验证方式 |
|------|-----------|--------|----------|
| 1 | `ScanNearbyBlocks` 能否实际返回范围内所有方块（非空气） | 🔴 高 | 实际调用 + 对比游戏内 F3 信息 |
| 2 | `ScanNearbyBlocks` 的 `max_count` 上限是多少 | 🔴 高 | 逐步增大 radius 测试截断点 |
| 3 | `ScanNearbyBlocks` 性能：radius=16 需要多少 ms | 🟡 中 | 计时 + 记录 |
| 4 | 未加载 chunk 的查询行为（超时？空？报错？） | 🟡 中 | 传送到远处后立即查询 |
| 5 | `FindBlocks` 搜索所有方块（query=""）是否等价于全范围扫描 | 🟢 低 | 对比 ScanNearbyBlocks 结果 |

---

## 5. 架构备注

MCC → 后端的数据通道是**双通道**：

```
通道 A（MCP HTTP API）── 结构化 JSON 数据
  ↓ 用于：物品栏、方块、实体、玩家状态等结构化查询
  ↓ 协议：JSON-RPC 2.0 over HTTP POST
  ↓ 客户端：backend/src/vmtools_next/adapters/mcc/mcc_mcp_client.py（65 个方法）

通道 B（stdout PIPE）── 人类可读文本日志
  ↓ 用于：断联检测、玩家上下线、终端展示
  ↓ 协议：逐行 stdout → 脱敏 → Socket.IO 推送
  ↓ 管理：backend/src/vmtools_next/core/mcc_process_manager.py
```

**重要设计原则：** 结构化数据永远走通道 A（MCP），终端日志仅用于事件检测和展示。
