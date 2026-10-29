# 地图画（map_art）离线验证套件

2026-10-28 架构重构把 `core/map_art_coordinator.py`（4432 行）与
`core/multi_bot_coordinator.py`（1951 行）拆成 `core/map_art/` 包（12 个模块）。
本目录是该重构的**可离线复跑验证手段**，不依赖 pytest、不依赖已安装的后端依赖、
不连任何服务器。

设计契约见 [`docs/dev/map-art-重构方案-2026-10-28.md`](../../docs/dev/map-art-重构方案-2026-10-28.md)
（§三 坐标铁律、§六 验证手段、§七 验收清单）。

---

## 快速开始

在**仓库根目录**（`vmtools-next/`）执行：

```bash
# 1) 全部地图画单测（54 个用例，约 55s；整编排用例走真实节流间隔）
python3 -m unittest discover -s backend/tests -p 'test_map_art_*.py' -v

# 2) AST 静态一致性检查（秒级；发现问题非零退出）
python3 scripts/check_map_art_attrs.py

# 3) 先验证检查器本身有效（两条规则都能命中故意写错的代码）
python3 scripts/check_map_art_attrs.py --self-test

# 4) 只看统计 / 弱证据明细
python3 scripts/check_map_art_attrs.py -v
```

单文件调试（三个等价写法，任选）：

```bash
python3 -m unittest backend.tests.test_map_art_geometry -v   # 从仓库根
cd backend && python3 -m unittest tests.test_map_art_geometry -v
python3 backend/tests/test_map_art_engines.py                # 直接当脚本跑
```

> 环境要求：Python 3.11+（只用标准库）。**不需要** pip、pytest、fastapi、sqlalchemy。

---

## 文件清单

| 文件 | 作用 |
|---|---|
| `_stub_env.py` | 向 `sys.modules` 注入 fastapi / sqlalchemy / pydantic / socketio / loguru / yaml / nbtlib / **httpx** / **websockets** / **cachetools** / **fastapi.security** 的最小 stub，并把 `backend/src` 加进 `sys.path`。`install()` **幂等**；真依赖已装时只补缺失属性，不覆盖。另提供 `quiet_stub_noise()`（屏蔽 stub 噪音）与 `fast_teleport_settle()`（测试加速，见下）。 |
| `fake_agent.py` | `FakeAgent`：假 MCP 客户端，返回与 `adapters/mineflayer/mineflayer_client.py` 一致的 dict 形态；支持**多 bot 共享 world**、记录 place/dig/chat/move，可注入放置失败 / 弱确认 / 错色。 |
| `test_map_art_imports.py` | import 冒烟：新包 + 两个 shim + `api.routers.build_map_art` + `api.socketio_handlers` + `data.models` + `config`；shim 必须是 re-export（同一对象）。 |
| `test_map_art_geometry.py` | 纯函数：`partition_rectangular` / `build_2d_matrix` / `plan_squad` / `ColumnRegion.z_order` / `region_cells` / 坐标换算。 |
| `test_map_art_engines.py` | FakeAgent 驱动：列式 0-based 坐标、反向排整列、strip 蛇形、4×3 双 bot 整编排、开工信号 latch、排尾同步只等本排 bot、运行中 add/remove bot、进度口径（含 1 个 `expectedFailure`，见下）。 |
| `test_map_art_pause.py` | 暂停语义（`paused` / `running` / waiting 不误报）+ 终态判定（offline 计入失败、全员离线判 failed）。 |
| `../../scripts/check_map_art_attrs.py` | AST 静态检查：规则 A（`self._xxx` 必须有赋值来源）、规则 B（模块级全局名必须可解析）。 |

---

## 用例 ↔ 契约/缺陷对照

| 用例 | 锁住的契约或回归的 bug |
|---|---|
| `TestPlanSquad.test_first_squad_starts_at_column_zero` | 列号 0-based：首排第一列 `column_x == 0`（旧实现 `range(1, n+1)` 整体 +1） |
| `TestColumnEngineCoords.test_first_column_world_x_equals_origin` | `world_x = origin_x + column_x`，首列必须落在 `origin_x` |
| `TestColumnRegionZOrder.test_reversed_squad_params` | 反向排 `z_start=size-1 / z_end=0` 时 `z_order()` 必须**倒序非空**（旧实现 `range(z_start, z_end+1)` 得空列表 → 蛇形第二排整列不建） |
| `TestColumnRegionZOrder.test_plan_squad_reversed_region_is_buildable` | 端到端串起 `plan_squad(direction=-1)` → `ColumnRegion` → `column_cells`，保证反向排真的能建 |
| `TestStripEngineCoords.test_serpentine_two_rows` | 蛇形：偶数行 x 升序、奇数行 x 降序，无 1 格偏移 |
| `TestSquadOrchestration.test_two_bots_build_4x3` | 整编排：12 格全建成 / 重复放置 0 次 / 终态 completed / 列池清空 / 两排蛇形掉头 |
| `TestSignalGoLatch.test_stale_signal_does_not_rebuild_previous_column` | 开工信号 latch 残留：上一排 `signal_go` 未被消费 → 用旧列号重复建（排 1 建两次、排 2 永不建） |
| `TestSquadWaitAssignedOnly` | 排尾同步只等「本排被分配的 bot」；用全部活跃 bot 会在 `add_bot` 后整排卡死 |
| `TestAddRemoveBotMidRun` | 运行中 `add_bot` / `remove_bot`：不漏建、不重复、移除的列回列池 |
| `TestPauseSemantics.test_waiting_loop_without_user_pause_is_not_paused` | 列建完等下一排（loop `waiting`）**不是**暂停；只有 `_paused_by_user` 才算 |
| `TestFailureTerminalState.test_aggregate_status_after_failed_finish` | 失败收尾后周期推送的 `status` 必须是 `failed`（QA 抓到：`_compute_status` 先判 `_completion_notified` → 恒 completed，前端误显示「已完成」；Lead 已加 `_final_status` 修复） |
| `TestFailureTerminalState.test_aggregate_status_after_success_finish` | 对称用例：成功收尾后 `status == "completed"`，且收尾日志为「任务结束：完成」 |
| `TestFailureTerminalState` | `offline` 计入 `_failed_loops`；全员离线一律 failed（不能因为跳过对账写 completed） |
| `TestAddRemoveBotMidRun`（进度采样断言） | 增删 bot 后 `placed_blocks` 单调不回退（DB 基线 + Σ `_new_placed` 口径） |
| `test_map_art_imports.py` | 重构后所有入口仍可 import；shim 是真 re-export（不是第二份实现） |
| `check_map_art_attrs.py` 规则 A | 拆分时属性漏搬（A 类方法用 `self._x`，赋值留在 B 类）→ 运行时 `AttributeError` |
| `check_map_art_attrs.py` 规则 B | 漏 `import` 常量（如 `TASK_COMPLETED`）→ 运行到该分支才 `NameError` |

### 静态检查的两个规则（实现要点）

- **规则 A**：对 `core/map_art/**` 每个类收集所有 `self._xxx` 使用点，沿**同包内可解析的
  父类 MRO** 核对赋值来源：`self._x = ...` / `self._x: T = ...` / `setattr(self, "_x", ...)` /
  `self.__dict__["_x"] = ...` / 类属性 / 方法名 / `__init__` 同名参数（弱证据，单独列出）。
  父类解析不了时降级为「无法确认」告警，不算错误（避免误报）。
- **规则 B**：带词法作用域分析——局部变量、`global`/`nonlocal`、闭包、推导式、
  内置名、`TYPE_CHECKING` 内 import 都正确区分；只报「本模块既没定义也没 import」的 `Name`。

两条规则都有 **`--self-test`**：在临时目录里跑一份故意写错的代码，验证「该抓的抓到、
不该报的不报」。改检查器后务必跑一遍。

**变异验证记录**（证明检查器不是"永远绿"的空壳，2026-10-28 对当时代码实测）：

| 人为制造的缺陷 | 检查器结果 |
|---|---|
| 删掉 `base_coordinator.py` 里 `TASK_COMPLETED` 的 import | 规则B 报 3 处（:120 / :552 / :599），退出码 1 |
| 删掉 `ActivityLog._entries` 的唯一赋值 | 规则A 报 5 处，退出码 1 |
| 未改动代码 | 规则A 0 / 规则B 0，退出码 0 |

---

## 已知问题（用例里用 `expectedFailure` 标注，修好后会变成 unexpected success）

### 1. 任务级进度少算「连接条已铺好的格子」（严重度：中高，用户可见）

- **现象**：3 列 × 2 行任务 6 格全部建成、终态 `completed`，但
  `_aggregate().placed_blocks` 只有 **3**，而 `Σ loop.progress.blocks_placed` = 6
  —— 前端进度条少一半。缺的正好是「每列起点那 1 格」（3 列 → 3 格）。
- **根因**：`placement._record` 只在 `outcome == "placed"` 时累加 `_new_placed`；
  开路者 `_place_connector_row` 直接 `_place_with_retry` 铺真实方块（不走 `place_cell`），
  随后该列 bot 建这格时 `place_cell` 判为 `verified`（世界已有正确方块）→
  只进 `progress.blocks_placed`、不进 `_new_placed` → 任务级聚合永远少算。
- **为什么"verified 不算"在列式模式不成立**：列式 `build_column` 先用
  `_load_placed_set()` 跳过 DB 已建格，能走到 `place_cell` 的 `verified` 一定是
  **DB 基线里没有的新进度**（连接条、或上次弱确认但没落库的格子）。
  注意 strip 引擎没有这个跳过逻辑，直接把 verified 计入会和 DB 基线双计 ——
  两个引擎的语义不同，修法需分开处理。
- **用例**：`test_map_art_engines.TestProgressAccounting.test_verified_cell_counts_toward_task_progress`
  （`expectedFailure`；同类的对照组用例正常通过，证明断言本身没错）。
- **可选修法**：① `place_cell` 加 `count_verified` 参数，列式传 True / strip 传 False；
  ② 连接条铺真实方块后显式记一次进度；③ strip 引擎补 DB 跳过逻辑后两引擎统一口径。

## 已知限制（读测试输出前先看这里）

1. **整编排用例慢（全套约 55s）**：`_position_bots` 0.6s/bot、`_place_connector_row`
   0.3s/列、`_wait_squad_done` 2s 轮询、排间 0.8s 节流都是**真实节流**，故意保留
   （去掉会掩盖时序类 bug）。唯一被加速的是 `_send_teleport` 的 3.5s「等服务器落地」：
   纯网络延迟、FakeAgent 下立即生效，用 `_stub_env.fast_teleport_settle()` 跳过，
   单这一项就省掉 20s+。该 helper 带**漂移守卫**：若 `_send_teleport` 里不再有
   `asyncio.sleep(3.5)` 会直接报错提醒同步更新替身。
2. **stub 没有真 DB**，日志里会刷：
   `query_cells failed: 'NoneType' object has no attribute 'secret_key'`、
   `flush_placed failed (N rows): 'NoneType' object has no attribute 'where'`。
   这是**离线环境的正常噪音**（`MapArtStore` 拿不到真 Session，已内部兜底）。
   测试里默认屏蔽 `vmtools.map_art.store` / `runtime` 的告警；要看全量日志设
   `VMT_TEST_VERBOSE=1`。
3. **`FakeAgent` 不是真服务器**：不模拟 Via 同步延迟、区块未加载、多人推挤；
   放置/读取永远成功（除显式注入故障）。它能锁坐标与编排逻辑，锁不住网络时序。
4. **规则 A 不做数据流分析**：只看「本类/MRO 里是否存在赋值点」，不判断「赋值是否发生在
   使用之前」。例如删掉 `__init__` 里的 `self._x = None` 但 `pause()` 里还有
   `self._x = True`，规则 A 不会报（需要真跑起来才能发现）。
5. **规则 B 只查 `Name` 引用**：`getattr(self, "foo")`、字符串常量里的名字、动态导入查不到。

---

## 新增用例的约定

1. 新测试文件命名 `test_map_art_*.py`（这样 `discover -p 'test_map_art_*.py'` 会自动收）。
2. 文件头三行固定套路（保证从仓库根、`backend/`、直接执行都能跑）：

   ```python
   _HERE = os.path.dirname(os.path.abspath(__file__))
   if _HERE not in sys.path:
       sys.path.insert(0, _HERE)
   from _stub_env import install, quiet_stub_noise
   install()
   quiet_stub_noise()
   ```

3. **所有 `vmtools_next.*` 的 import 必须放在 `install()` 之后**（stub 未装时 import 会炸）。
4. 断言坐标时永远写「世界坐标 = origin + 相对坐标」，不要硬编码期望的 1-based 数字。
5. 编排类用例要 `try/finally: await coord.stop()`，否则后台 task 会在事件循环关闭时告警。
