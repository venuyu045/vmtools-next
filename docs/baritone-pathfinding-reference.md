# Baritone 寻路系统技术文档

> 基于 baritone-1.21.11 源码分析，供 VMTools 后续开发参考

## 1. 核心算法：A* + 自适应代价系数

**源码位置：**
- `baritone/pathing/calc/AStarPathFinder.java` — A* 主循环
- `baritone/pathing/calc/AbstractNodeCostSearch.java` — 基类（超时、最优系数追踪）
- `baritone/pathing/calc/PathNode.java` — 节点（cost, combinedCost, previous）
- `baritone/pathing/calc/openset/BinaryHeapOpenSet.java` — 最小堆开放集

### A* 流程
1. 创建起始 `PathNode`（cost=0, combinedCost=heuristic）
2. 弹出 combinedCost 最小的节点
3. 若 `goal.isInGoal(x,y,z)` → 重建路径
4. 遍历 19 种移动类型（Moves enum），计算邻居代价
5. 代价 ≥ `COST_INF`(1000000) 则跳过
6. 若 `tentativeCost < neighbor.cost - 0.01` → 更新并入堆
7. 同时追踪多个代价系数下的最优节点（bestSoFar）

### 启发函数
**关键文件：** `baritone/api/pathing/goals/GoalXZ.java`

水平分量 = (对角步数 × √2 + 直行步数) × costHeuristic（默认 3.563，匹配冲刺速度）
垂直分量 = 上升用 `JUMP_ONE_BLOCK_COST`/格，下降用 `FALL_N_BLOCKS_COST[2]/2`/格

### 超时与回退
- `primaryTimeoutMS` = 500ms（找到路径时停止）
- `failureTimeoutMS` = 2000ms（没找到继续搜）
- 超时后用递增系数 `{1.5, 2, 2.5, 3, 4, 5, 10}` 选取次优路径

---

## 2. Goal 系统

**源码位置：** `baritone/api/pathing/goals/`

| Goal 类 | 到达条件 | 启发函数 | 用途 |
|---------|---------|---------|------|
| **GoalBlock** | 精确 (x,y,z) | 水平+垂直距离 | 导航到精确方块 |
| **GoalNear** | 欧氏距离² ≤ range² | 同 GoalBlock | "到达附近"（带容差） |
| **GoalXZ** | x匹配 且 z匹配（任意Y） | 水平对角+直行距离 | 不关心高度的远程目标 |
| **GoalYLevel** | y == level | 上升/下降代价 | 挖矿到指定层 |
| **GoalGetToBlock** | 曼哈顿距离 ≤ 1 | 同 GoalBlock | **靠近箱子/门（相邻）** |
| **GoalComposite** | 任意子目标满足 | min(子目标启发) | "到这些钻石矿中任意一个" |
| **GoalRunAway** | 距离所有 `from` ≥ distance | 负启发（越远越好） | 撤退 |

### GoalNear 工作原理（VMTools 最常用）
- `isInGoal`: 欧氏距离² ≤ range² → **球形区域**
- A* 自然收敛到球内最便宜可达点
- **不显式选择最终位置**，A* 找到的第一个球内点就停
- radius=0 → 精确到达；radius=3 → 3格内任意点

### GoalGetToBlock（推荐用于扫描）
- 曼哈顿距离 ≤ 1 → 箱子相邻的4个位置 + 上下
- 比 GoalNear 更精确，确保玩家能与容器交互

---

## 3. 移动代价

**源码位置：** `baritone/api/pathing/movement/ActionCosts.java`

| 动作 | 代价（tick） | 说明 |
|------|-------------|------|
| 步行/格 | 4.633 | 20/4.317 |
| 冲刺/格 | 3.564 | 20/5.612 |
| 水中/格 | 9.091 | 20/2.2 |
| 灵魂沙/格 | 9.266 | 双倍步行 |
| 潜行/格 | 15.385 | 20/1.3 |
| 梯子上 | 8.511 | 20/2.35 |
| 梯子下 | 6.667 | 20/3.0 |
| 走下悬崖 | 3.706 | 步行的80% |
| COST_INF | 1000000 | 不可通行 |

### CalculationContext（代价计算快照）
- `canSprint` — 饱食度 > 6 且 allowSprint
- `hasWaterBucket` — 热键栏有水桶（非下界）
- `hasThrowaway` — allowPlace 且有可放置方块
- `placeBlockCost` — 默认 20 tick
- `breakBlockAdditionalCost` — 默认 2 tick
- `jumpPenalty` — 默认 2 tick

### 19 种移动类型
| Moves | 偏移 | 类型 | 说明 |
|-------|------|------|------|
| TRAVERSE_N/S/E/W | (±1,0,0)/(0,0,±1) | 平走 | 最常用 |
| ASCEND_N/S/E/W | (±1,+1,0)/(0,+1,±1) | 上台阶 | 跳+走 |
| DESCEND_N/S/E/W | (±1,-1,0)/(0,-1,±1) | 下台阶/坠落 | 超过1格变 MovementFall |
| DIAGONAL_NE/NW/SE/SW | (±1,0,±1) | 斜走 | √2 × 步行代价 |
| PILLAR | (0,+1,0) | 搭方块向上 | 放置方块代价 |
| DOWNWARD | (0,-1,0) | 向下挖/跳 | 梯子或破坏方块 |
| PARKOUR_N/S/E/W | (±4,0,0)/(0,0,±4) | 跳跃 | 最远4格，需 allowParkour |

---

## 4. 路径事件

**源码位置：** `baritone/api/event/events/PathEvent.java`

| 事件 | 触发时机 | 含义 |
|------|---------|------|
| `CALC_STARTED` | A* 开始 | 开始计算 |
| `CALC_FINISHED_NOW_EXECUTING` | 找到路径 | 开始执行 |
| `CALC_FAILED` | 找不到路径 | **无路可走** |
| `AT_GOAL` | 路径执行完 且 在目标内 | **到达目的地** |
| `CANCELED` | 取消路径 | 被中断 |
| `CONTINUING_ONTO_PLANNED_NEXT` | 当前段完成，切换到预计算的下一段 | 无缝衔接 |
| `SPLICING_ONTO_NEXT_EARLY` | 当前移动刚结束，提前拼接下一段 | 效率优化 |

**监听方式：**
```java
// VMTools 当前实现（反射）
Object eventBus = baritone.getGameEventHandler();
// 通过 Proxy 实现 IGameEventListener，监听 onPathEvent(PathEvent)
```

---

## 5. 路径行为管理

**源码位置：** `baritone/behavior/PathingBehavior.java`

### 状态
- `current` — 正在执行的路径
- `next` — 预计算的下一段
- `inProgress` — 正在运行的 A* 计算
- `goal` — 当前目标

### Tick 循环
1. 派发排队的路径事件
2. `current.onTick()` 执行当前移动
3. 当前段完成：
   - 在目标内 → 触发 `AT_GOAL`
   - 有预计算的 next → 切换到 next
   - 否则启动新 A* 计算
4. 剩余 tick < 150（7.5秒）且没有 next → 启动前瞻计算

### 取消层级
- `cancelEverything()` — 取消当前 + 所有进程
- `forceCancel()` — 硬取消，包括 inProgress
- `softCancelIfSafe()` — 安全时取消
- `secretInternalSegmentCancel()` — 只取消当前段

---

## 6. 位置定位（GoalNear 如何选最终位置）

**关键理解：Baritone 不显式"选"最终位置。**

- A* 从起点向外扩展，第一个到达 `isInGoal` 为 true 的节点即为终点
- GoalNear 的 `isInGoal` 是球形（欧氏距离² ≤ range²）
- A* 天然收敛到球内**最便宜可达点**
- GoalGetToBlock 用曼哈顿距离 ≤ 1 → 确保玩家与方块相邻

**VMTools 的 navigateToContainer 流程：**
1. 计算箱子在过道上的最近点 P（向量投影）
2. 调用 `baritone.pathToNear(P.x, P.y, P.z, 0)` → GoalNear radius=0
3. 等待 AT_GOAL 事件
4. `lookAt(箱子坐标)` → 触发 MiniHUD 数据同步

---

## 7. 公共 API

### 入口
```java
IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();
Settings settings = BaritoneAPI.getSettings();
```

### IBaritone 关键接口
| 方法 | 返回类型 | 用途 |
|------|---------|------|
| `getCustomGoalProcess()` | ICustomGoalProcess | 设置目标并寻路 |
| `getPathingBehavior()` | IPathingBehavior | 路径执行管理 |
| `getGameEventHandler()` | IEventBus | 事件注册 |
| `getPlayerContext()` | IPlayerContext | 玩家/世界访问 |
| `getInputOverrideHandler()` | IInputOverrideHandler | 输入控制 |

### ICustomGoalProcess（最简单用法）
```java
// 设置目标并开始寻路
baritone.getCustomGoalProcess().setGoalAndPath(new GoalNear(blockPos, radius));
// 只设目标不寻路
baritone.getCustomGoalProcess().setGoal(new GoalBlock(x, y, z));
// 在已有目标上开始寻路
baritone.getCustomGoalProcess().path();
```

### IPathingBehavior
```java
boolean isPathing = baritone.getPathingBehavior().isPathing();
Goal currentGoal = baritone.getPathingBehavior().getGoal();
baritone.getPathingBehavior().cancelEverything();
double eta = baritone.getPathingBehavior().estimatedTicksToGoal();
```

---

## 8. 区块感知

### 计算阶段
- 跳过未加载区块中的移动（`numEmptyChunk` 计数器）
- 目标在未加载区块时，GoalNear/GoalBlock 简化为 GoalXZ（去掉Y约束）

### 执行阶段
- 下一个移动的目标在未加载区块 → 暂停等待
- 路径在已加载区块边界处截断
- 方块状态变化 → 重新验证代价，代价增加过大 → 取消路径

---

## 9. 路径执行

### PathExecutor 每 tick
1. 位置验证（处理回弹/跳过）
2. 偏离检测（>2格 200tick → 取消，>3格 立即取消）
3. 方块变化检测（±10 位置范围）
4. 代价重验证（前5个移动）
5. `movement.update()` → PREPPING/WAITING/RUNNING/SUCCESS/FAILED
6. 超时：移动耗时超过估算 + 100tick → 取消

### Movement.update() 基类
1. 关闭飞行
2. 调用子类 `updateState(currentState)`
3. 在液体中且低于目标 → 强制跳跃
4. 在墙里 → 自动选工具并破坏
5. 应用目标旋转
6. 应用输入覆盖（WASD/跳跃/潜行/冲刺）

---

## 10. VMTools 集成要点

### 当前 BaritoneAdapter 使用方式
```
BaritoneAdapter（反射调用 Baritone API）
├── pathToNear(x, y, z, radius) → GoalNear + setGoalAndPath
├── cancelPathing() → cancelEverything()
├── isPathing() → IPathingBehavior.isPathing()
├── isArrived(x, y, z, radius) → 事件 + 坐标双重检测
└── lookAt(x, y, z) → 设置 yaw/pitch
```

### 可改进方向
1. **用 GoalGetToBlock 替代 GoalNear(radius=0)** — 更精确的相邻检测
2. **监听 PathEvent.CALC_FAILED** — 当前只检测 AT_GOAL/CANCELED，缺 CALC_FAILED 处理
3. **用 IPathingBehavior.estimatedTicksToGoal()** — 超时阈值应动态化，而非固定15秒
4. **PathExecutor 偏离检测** — 可参考 Baritone 的 200tick/3格 规则优化导航超时
5. **前瞻计算** — 当前逐个箱子导航，可预计算下一个箱子的路径
6. **Settings 调优** — allowParkour, allowSprint, jumpPenalty 等可在扫描模式下调优
