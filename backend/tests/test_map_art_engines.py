"""地图画引擎回归测试 —— FakeAgent 驱动列式 / strip / 整编排三条主链路。

迁移自 Lead 的手工验证脚本（``/tmp/ma_stub/test_engines.py``、``test_squad.py``），
并补上「列式 0-based 坐标」与「整编排 4×3 双 bot」的回归断言。

回归的三条（对应设计契约 §三 坐标铁律 + §七 验收清单）：

1. **列式 0-based**：``column_x`` 是 0-based，``world_x == origin_x + column_x``。
   首列（``column_x=0``）必须落在 ``origin_x`` 上 —— 旧实现 ``range(1, n+1)`` 会整体 +1。
2. **strip 蛇形**：偶数行 x 升序、奇数行 x 降序；两行坐标不得有 1 格偏移。
3. **整编排 4×3 双 bot**：连接条 → 就位 → 排内并行 → 排尾同步 → 蛇形掉头 → 收尾；
   12 格全部建成、重复放置 0 次、终态 completed、列池清空。

跑法::

    python3 -m unittest discover -s backend/tests -p 'test_map_art_*.py' -v

注意：整编排用例走真实节流间隔（``column_place_interval`` / 就位 0.6s / 排尾轮询 2s），
单跑约 15–20s，属预期（不去掉 sleep，避免掩盖时序 bug）。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import fast_teleport_settle, install, quiet_stub_noise  # noqa: E402

install()
quiet_stub_noise()

from fake_agent import FakeAgent  # noqa: E402

from vmtools_next.core.map_art import (  # noqa: E402
    ColumnBuildLoop,
    ColumnRegion,
    MultiBotCoordinator,
    Region,
    SquadAssignment,
    SquadPlan,
    StripBuildLoop,
)
from vmtools_next.core.map_art.settings import MapArtSettings  # noqa: E402
from vmtools_next.core.map_art.types import (  # noqa: E402
    STATE_OFFLINE,
    STATE_PLACING,
    STATE_WAITING,
)

WHITE = "minecraft:white_wool"
BLACK = "minecraft:black_wool"
RED = "minecraft:red_wool"


def enable_fast_teleport(testcase) -> None:
    """在用例生命周期内跳过「传送后等落地」的 3.5s/次（用例结束自动还原）。

    覆盖整个用例（含 start() 之后才真正跑起来的 loop 任务），否则只包住 start()
    那一行是没有效果的——loop 的 startup 在 start() 返回后才执行。
    """
    cm = fast_teleport_settle()
    cm.__enter__()
    testcase.addCleanup(cm.__exit__, None, None, None)


async def wait_done_sampling(coord, timeout: float = 120.0) -> list[int]:
    """等收尾，同时按 50ms 采样 ``placed_blocks``（用于断言进度单调不回退）。"""
    samples: list[int] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        samples.append(coord._aggregate().placed_blocks)
        if coord._completion_notified:
            return samples
        await asyncio.sleep(0.05)
    return samples


async def wait_until(predicate, timeout: float = 120.0, interval: float = 0.05) -> bool:
    """轮询等待条件成立（超时返回最后一次结果）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


class TestColumnEngineCoords(unittest.IsolatedAsyncioTestCase):
    """列式引擎：0-based 列号 → 世界坐标。"""

    async def test_first_column_world_x_equals_origin(self):
        """首列（column_x=0）必须落在 origin_x 上，不得 +1。"""
        origin_x, origin_y, origin_z = 100, 64, 200
        matrix = {(0, 0): WHITE, (0, 1): BLACK, (0, 2): WHITE}
        agent = FakeAgent("b1")
        loop = ColumnBuildLoop(
            bot_id="b1", bot_name="B1", task_id="t-first-col", block_matrix=matrix,
            origin_x=origin_x, origin_y=origin_y, origin_z=origin_z, mcp=agent,
            settings=MapArtSettings(), column_region=ColumnRegion(0, 0, 2, 1),
        )
        # 走 assign_squad 路径（协调器真实调用顺序），顺带验证 SquadAssignment 0-based
        await loop.assign_squad(SquadAssignment("b1", 0, 1, 0, 2), 1)
        await loop.build_column()

        xs = {x for x, _y, _z, _b in agent.placed}
        self.assertEqual(xs, {origin_x},
                         f"首列 world_x 必须 == origin_x={origin_x}，实际 {xs}")
        self.assertEqual(sorted((z, b) for _x, _y, z, b in agent.placed),
                         [(200, "white_wool"), (201, "black_wool"), (202, "white_wool")])
        self.assertEqual(loop.progress.blocks_placed, 3)

    async def test_second_column_offsets_by_one_only(self):
        """column_x=1 → world_x = origin_x + 1（不是 +2）。"""
        matrix = {(1, z): WHITE for z in range(3)}
        agent = FakeAgent("b2")
        loop = ColumnBuildLoop(
            bot_id="b2", bot_name="B2", task_id="t-second-col", block_matrix=matrix,
            origin_x=100, origin_y=64, origin_z=200, mcp=agent,
            settings=MapArtSettings(), column_region=ColumnRegion(1, 0, 2, 1),
        )
        await loop.build_column()

        self.assertEqual({x for x, _y, _z, _b in agent.placed}, {101})
        self.assertEqual({z for _x, _y, z, _b in agent.placed}, {200, 201, 202})

    async def test_reverse_direction_builds_whole_column(self):
        """反向排（z_start=size-1 / z_end=0）整列都要建 —— Lead 修过的空列表 bug。"""
        matrix = {(0, z): WHITE for z in range(4)}
        agent = FakeAgent("b3")
        loop = ColumnBuildLoop(
            bot_id="b3", bot_name="B3", task_id="t-rev-col", block_matrix=matrix,
            origin_x=10, origin_y=70, origin_z=20, mcp=agent,
            settings=MapArtSettings(), column_region=ColumnRegion(0, 3, 0, -1),
        )
        await loop.assign_squad(SquadAssignment("b3", 0, -1, 3, 0), 2)
        await loop.build_column()

        zs = [z for _x, _y, z, _b in agent.placed]
        self.assertEqual(len(zs), 4, f"反向列一格都没建（z_order 空列表 bug）：{zs}")
        self.assertEqual(zs, [23, 22, 21, 20], "反向排必须沿 z- 建造（倒序）")


class TestStripEngineCoords(unittest.IsolatedAsyncioTestCase):
    """strip 引擎：行式蛇形，两行坐标不得有 1 格偏移。"""

    async def test_serpentine_two_rows(self):
        matrix = {(0, 0): WHITE, (1, 0): BLACK, (0, 1): BLACK, (1, 1): WHITE}
        agent = FakeAgent("s1")
        loop = StripBuildLoop(
            bot_id="s1", bot_name="S1", task_id="t-strip", block_matrix=matrix,
            origin_x=10, origin_y=70, origin_z=20, mcp=agent,
            settings=MapArtSettings(), region=Region(0, 1, 0, 1),
        )
        await loop._place_row(0, 20)
        await loop._place_row(1, 21)

        seq = [(x, z) for x, _y, z, _b in agent.placed]
        # 第 0 行 x 升序；第 1 行 x 降序（蛇形，省回程）
        self.assertEqual(seq, [(10, 20), (11, 20), (11, 21), (10, 21)],
                         f"蛇形顺序/坐标错误：{seq}")
        self.assertEqual(set(seq), {(10, 20), (11, 20), (10, 21), (11, 21)})
        # 颜色也对上（防 x/z 交换）
        self.assertEqual({(x, z): b for x, _y, z, b in agent.placed},
                         {(10, 20): "white_wool", (11, 20): "black_wool",
                          (11, 21): "white_wool", (10, 21): "black_wool"})


class TestSquadOrchestration(unittest.IsolatedAsyncioTestCase):
    """整编排回归：4×3 双 bot，两排（蛇形掉头）建完。"""

    SX, SZ = 4, 3
    OX, OY, OZ = 500, 64, 700

    def _make_matrix(self):
        matrix = {}
        colors = [WHITE, BLACK, RED]
        for x in range(self.SX):
            for z in range(self.SZ):
                matrix[(x, z)] = colors[(x + z) % 3]
        return matrix

    def _make_coord(self, matrix):
        return MultiBotCoordinator(
            task_id="tsq",
            projection_data={
                "layers": {0: [(x, 0, z, b) for (x, z), b in matrix.items()]},
                "regions": {"Main": {"size": {"x": self.SX, "z": self.SZ}}},
            },
            origin_x=self.OX, origin_y=self.OY, origin_z=self.OZ,
        )

    async def test_two_bots_build_4x3(self):
        matrix = self._make_matrix()
        shared_world: dict = {}
        agents = {
            "mf-001": FakeAgent("mf-001", world=shared_world),
            "mf-002": FakeAgent("mf-002", world=shared_world),
        }
        coord = self._make_coord(matrix)
        # 映射自检（四角测试方块）单独验证，这里跳过以免干扰编排计时
        coord._map_self_check = lambda: asyncio.sleep(0, result=True)
        enable_fast_teleport(self)

        try:
            await coord.start({bid: (bid.upper(), ag) for bid, ag in agents.items()})

            # 等「收尾完成」——注意 _completion_notified 在 finish_task **开头**就置 True，
            # 只等它会在对账/落库之前就继续，属于竞态；等收尾日志出现才稳。
            finished = await wait_until(
                lambda: any(e["message"].startswith("任务结束")
                            for e in coord.activity.recent(300)), timeout=120.0)
            self.assertTrue(finished,
                            "排级循环未结束（可能卡在就位 / 排尾同步）")

            # ① 12 格全部建成（且首末格都在，排除整体偏移 1 格）
            placed_cells = set()
            all_places = []
            for agent in agents.values():
                all_places.extend(agent.placed)
                placed_cells |= agent.placed_cells()
            want_cells = {(self.OX + x, self.OZ + z)
                          for x in range(self.SX) for z in range(self.SZ)}
            self.assertEqual(placed_cells, want_cells,
                             f"建造坐标不完整/越界：缺 {want_cells - placed_cells} "
                             f"多 {placed_cells - want_cells}")
            self.assertIn((self.OX, self.OZ), placed_cells, "首格 (origin) 未建 —— 整体偏移 1 格？")
            self.assertIn((self.OX + self.SX - 1, self.OZ + self.SZ - 1), placed_cells)

            # ② 重复放置 0 次
            dup = len(all_places) - len(placed_cells)
            self.assertEqual(dup, 0, f"存在重复放置 {dup} 次（排尾/蛇形重排逻辑问题）")

            # ③ 方块颜色与投影一致（共享世界：后放的必须覆盖成期望色）
            for (x, z), block_id in matrix.items():
                got = shared_world.get((self.OX + x, self.OY, self.OZ + z))
                self.assertEqual(got, block_id.split(":")[-1],
                                 f"({x},{z}) 期望 {block_id} 实际 {got}")

            # ④ 终态 completed + 列池清空
            self.assertEqual(coord._compute_status(), "completed")
            # 各 bot 进度之和 == 总块数（聚合口径见 TestProgressAccounting 的已知问题）
            self.assertEqual(sum(l.progress.blocks_placed for l in coord._loops.values()),
                             self.SX * self.SZ)
            self.assertEqual(len(coord._column_pool), 0, "列池未清空（仍有未建列）")
            self.assertFalse(any("失败" in e["message"] for e in coord.activity.recent(300)
                                 if e["level"] == "error"),
                             "日志里出现错误级条目")
            self.assertTrue(any(e["message"].startswith("任务结束：完成")
                                for e in coord.activity.recent(300)),
                            "收尾日志未记录「任务结束：完成」")

            # ⑤ 两排都跑过（4 列 / 2 bot → 2 排），蛇形掉头方向出现过 -1
            self.assertGreaterEqual(coord._squad.squad_index, 2)
            log_text = " ".join(e["message"] for e in coord.activity.recent(300))
            self.assertIn("方向 z-", log_text, "蛇形掉头未发生（第二排没反向）")
        finally:
            await coord.stop()


class TestProgressAccounting(unittest.IsolatedAsyncioTestCase):
    """进度口径回归：连接条铺好的格子必须计入任务级进度，且不能双计。

    背景（QA 2026-10-28 实测 + Lead 修复）：开路者 ``_place_connector_row`` 直接
    ``_place_with_retry`` 铺真实方块（不走 ``place_cell``），随后该列 bot 建这一格时
    ``place_cell`` 判为 ``verified`` → 两边都不进 ``_new_placed`` → 任务级进度长期
    少算「每列起点那 1 格」（3 列任务 6 格建成却只显示 3）。

    修复：连接条铺完调用 ``BotRuntime.note_external_placement`` 显式记账；
    列 bot 后续 verified **不再**重复计数（避免与 DB 基线/连接条双计）。
    """

    async def test_connector_cell_counts_once(self):
        """连接条记账一次；列 bot 再 verified 同一格不得重复计数。"""
        agent = FakeAgent("b1")
        loop = ColumnBuildLoop(
            bot_id="b1", bot_name="B1", task_id="t-progress",
            block_matrix={(0, 0): WHITE}, origin_x=0, origin_y=64, origin_z=0,
            mcp=agent, settings=MapArtSettings(),
            column_region=ColumnRegion(0, 0, 0, 1),
        )
        # ① 开路者铺连接条 → 显式记账
        agent.world[(0, 64, 0)] = "white_wool"
        loop.note_external_placement(0, 64, 0, WHITE)
        self.assertEqual(loop._new_placed, 1, "连接条格子必须计入本次新增")
        self.assertIn((0, 64, 0, WHITE), loop._db_updates, "连接条格子必须待落库")

        # ② 该列 bot 建到同一格 → verified（世界已有正确方块），不得再加一次
        res = await loop.place_cell(0, 0, WHITE)
        self.assertEqual(res.outcome, "verified", "该格应被判为已建成（verified）")
        self.assertEqual(loop._new_placed, 1, "verified 不得重复计入（会与连接条/DB 基线双计）")

    async def test_placed_cell_counts_toward_task_progress(self):
        """对照组：真正新放置的格子必须计入本次新增。"""
        agent = FakeAgent("b1")
        loop = ColumnBuildLoop(
            bot_id="b1", bot_name="B1", task_id="t-progress2",
            block_matrix={(0, 0): WHITE}, origin_x=0, origin_y=64, origin_z=0,
            mcp=agent, settings=MapArtSettings(),
            column_region=ColumnRegion(0, 0, 0, 1),
        )
        res = await loop.place_cell(0, 0, WHITE)
        self.assertEqual(res.outcome, "placed")
        self.assertEqual(loop._new_placed, 1)
        self.assertEqual(loop.progress.blocks_placed, 1)

    async def test_squad_task_progress_equals_built_cells(self):
        """端到端：3 列 × 2 行双 bot 任务，聚合进度必须等于实际建成格数（6）。"""
        from vmtools_next.core.map_art import MultiBotCoordinator

        sx, sz = 3, 2
        colors = ["minecraft:white_wool", "minecraft:black_wool", "minecraft:red_wool"]
        matrix = {(x, z): colors[(x + z) % 3] for x in range(sx) for z in range(sz)}
        shared_world = {}
        agents = {"mf-001": FakeAgent(), "mf-002": FakeAgent()}
        for ag in agents.values():
            ag.world = shared_world
        coord = MultiBotCoordinator(
            task_id="t-progress-e2e",
            projection_data={
                "layers": {0: [(x, 0, z, b) for (x, z), b in matrix.items()]},
                "regions": {"Main": {"size": {"x": sx, "z": sz}}},
            },
            origin_x=100, origin_y=64, origin_z=200,
        )
        coord._map_self_check = lambda: asyncio.sleep(0, result=True)
        try:
            await coord.start({b: (b.upper(), a) for b, a in agents.items()})
            for _ in range(800):
                await asyncio.sleep(0.02)
                if coord._completion_notified:
                    break
            state = coord._aggregate()
            built = len(shared_world)
            self.assertEqual(built, sx * sz, f"实际建成格数不对：{sorted(shared_world)}")
            self.assertEqual(state.placed_blocks, built,
                             f"聚合进度 {state.placed_blocks} != 实际建成 {built}"
                             "（连接条格子被漏计或双计）")
            self.assertEqual(state.total_blocks, sx * sz)
        finally:
            await coord.stop()


class _RecordingColumnLoop(ColumnBuildLoop):
    """记录每次 ``build_column()`` 用的列号（开工信号 latch 回归用）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.built_columns: list[int] = []
        self.build_event = asyncio.Event()

    async def build_column(self) -> None:
        self.built_columns.append(self.column_x)
        self.progress.state = STATE_PLACING
        self.build_event.set()


class TestSignalGoLatch(unittest.IsolatedAsyncioTestCase):
    """回归：上一排 ``signal_go`` 的 latch 必须被消费，不得用旧列号重复建。

    Lead 修复的真实 bug：``run()`` 里只 clear ``_squad_assigned`` 而没 clear
    ``_build_ready`` → 排尾等待时被上一排残留的开工信号立刻唤醒，用**旧列号**再建一遍
    （实测：排 1 建两次、排 2 的列永远不建）。
    """

    async def test_stale_signal_does_not_rebuild_previous_column(self):
        matrix = {(0, 0): WHITE, (1, 0): WHITE}
        loop = _RecordingColumnLoop(
            bot_id="b1", bot_name="B1", task_id="t-latch", block_matrix=matrix,
            origin_x=0, origin_y=64, origin_z=0, mcp=FakeAgent("b1"),
            settings=MapArtSettings(), column_region=ColumnRegion(0, 0, 0, 1),
        )
        enable_fast_teleport(self)
        task = asyncio.create_task(loop.run())
        try:
            # 第 1 排：列 0
            await loop.assign_squad(SquadAssignment("b1", 0, 1, 0, 0), 1)
            await loop.signal_go()
            self.assertTrue(await wait_until(lambda: loop.built_columns == [0], 30.0),
                            f"第 1 排没建：{loop.built_columns}")

            # 关键断言：此时 loop 在等下一排分配，残留的开工信号不得让它再建一遍
            await asyncio.sleep(1.0)
            self.assertEqual(loop.built_columns, [0],
                             f"开工信号 latch 残留：用旧列号重复建 {loop.built_columns}")
            self.assertEqual(loop.progress.state, STATE_WAITING)

            # 第 2 排：列 1（新信号 → 建新列）
            loop.build_event.clear()
            await loop.assign_squad(SquadAssignment("b1", 1, 1, 0, 0), 2)
            await loop.signal_go()
            self.assertTrue(await wait_until(lambda: loop.built_columns == [0, 1], 30.0),
                            f"第 2 排没建 / 建错列：{loop.built_columns}")
            await asyncio.sleep(0.6)
            self.assertEqual(loop.built_columns, [0, 1],
                             f"第 2 排重复建造：{loop.built_columns}")
        finally:
            await loop.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


class _StubLoop:
    """只满足 ``_wait_squad_done`` / ``_compute_status`` 读字段的最小 loop 替身。"""

    def __init__(self, state: str = STATE_PLACING):
        self.bot_name = "stub"
        self.progress = _StubProgress(state)

    def is_stopping(self) -> bool:
        return False

    def status_extra(self) -> dict:
        return {}


class _StubProgress:
    def __init__(self, state: str):
        self.state = state
        self.blocks_placed = 0
        self.blocks_total = 0
        self.current_row = -1
        self.place_rate = 0.0


class TestSquadWaitAssignedOnly(unittest.IsolatedAsyncioTestCase):
    """回归：排尾同步只等「本排被分配的 bot」。

    Lead 修复的真实 bug：``_wait_squad_done`` 用「全部活跃 bot」判定 → 运行中
    ``add_bot`` 新增的 bot 本排没有列、永远等不完 → 整排卡死。
    """

    def _coord(self) -> MultiBotCoordinator:
        return MultiBotCoordinator(
            task_id="t-wait", projection_data={}, origin_x=0, origin_y=64, origin_z=0)

    async def test_wait_ignores_bots_without_column_this_squad(self):
        coord = self._coord()
        coord._loops = {"a": _StubLoop(), "b": _StubLoop()}
        coord._active_bot_ids = ["a", "b"]     # b 是本排之后才加入的（本排没列）
        coord._squad.bot_done = {"a"}
        plan = SquadPlan(
            squad_index=1, direction=1,
            assignments=[SquadAssignment("a", 0, 1, 0, 1)],
            col_start=0, col_end=0, total_columns=4, total_rows=2,
            remaining_columns=3,
        )
        # 旧实现会在这里挂住（等 b，轮询 2s 起步）→ wait_for 超时即失败
        await asyncio.wait_for(coord._wait_squad_done(plan), timeout=1.5)

    async def test_wait_returns_when_all_offline(self):
        coord = self._coord()
        coord._loops = {"a": _StubLoop(STATE_OFFLINE)}
        coord._active_bot_ids = ["a"]
        coord._squad.offline_bots = ["a"]
        coord._squad.bot_done = set()
        plan = SquadPlan(
            squad_index=1, direction=1,
            assignments=[SquadAssignment("a", 0, 1, 0, 1)],
            col_start=0, col_end=0, total_columns=4, total_rows=2,
        )
        await asyncio.wait_for(coord._wait_squad_done(plan), timeout=1.5)


class TestAddRemoveBotMidRun(unittest.IsolatedAsyncioTestCase):
    """回归：运行中 add_bot / remove_bot（用户需求「任何时候都能调整」）。

    用 3×2（6 格）：两种场景都只需 2 排，既覆盖「新增 bot 从下一排参与」「移除 bot
    的列回列池由他人接手」，又不会把用例拖到 4 排（每排真实节流 ≈4s）。
    """

    SX, SZ = 3, 2

    def _make_coord(self, task_id: str):
        colors = [WHITE, BLACK, RED]
        matrix = {(x, z): colors[(x + z) % 3]
                  for x in range(self.SX) for z in range(self.SZ)}
        coord = MultiBotCoordinator(
            task_id=task_id,
            projection_data={
                "layers": {0: [(x, 0, z, b) for (x, z), b in matrix.items()]},
                "regions": {"Main": {"size": {"x": self.SX, "z": self.SZ}}},
            },
            origin_x=0, origin_y=64, origin_z=0,
        )
        coord._map_self_check = lambda: asyncio.sleep(0, result=True)
        return coord, matrix

    def _want_cells(self):
        return sorted((x, z) for x in range(self.SX) for z in range(self.SZ))

    async def test_add_bot_mid_run(self):
        world: dict = {}
        a1 = FakeAgent("mf-001", world=world)
        coord, _matrix = self._make_coord("t-add")
        added = {"done": False}

        orig_cb = coord._on_column_done

        def on_done(bot_id):
            orig_cb(bot_id)
            if not added["done"]:
                added["done"] = True
                a2 = FakeAgent("mf-002", world=world)
                asyncio.create_task(coord.add_bot("mf-002", "MF-002", a2))

        coord._on_column_done = on_done
        enable_fast_teleport(self)
        try:
            await coord.start({"mf-001": ("MF-001", a1)})
            samples = await wait_done_sampling(coord, 120.0)
            self.assertTrue(coord._completion_notified, "未结束")
            self.assertIn("mf-002", coord._loops, "新增 bot 未加入 loops")
            cells = sorted((x, z) for (x, _y, z) in world)
            self.assertEqual(cells, self._want_cells(), f"漏建：{cells}")
            self.assertEqual(coord._compute_status(), "completed")
            # 进度不回退（Lead 修过：旧口径用 loop.blocks_placed，增删 bot 会凭空减少）
            self.assertEqual(samples, sorted(samples), f"进度出现回退：{samples}")
        finally:
            await coord.stop()

    async def test_remove_bot_mid_run(self):
        world: dict = {}
        a1 = FakeAgent("mf-001", world=world)
        a2 = FakeAgent("mf-002", world=world)
        coord, _matrix = self._make_coord("t-remove")
        removed = {"done": False}

        orig_cb = coord._on_column_done

        def on_done(bot_id):
            orig_cb(bot_id)
            if bot_id == "mf-002" and not removed["done"]:
                removed["done"] = True
                asyncio.create_task(coord.remove_bot("mf-002"))

        coord._on_column_done = on_done
        enable_fast_teleport(self)
        try:
            await coord.start({"mf-001": ("MF-001", a1), "mf-002": ("MF-002", a2)})
            samples = await wait_done_sampling(coord, 120.0)
            self.assertTrue(coord._completion_notified, "未结束")
            self.assertNotIn("mf-002", coord._loops, "移除后仍在 loops")
            # 移除时必须能立刻从排尾同步集合收敛，否则本排等不完
            self.assertNotIn("mf-002", coord._squad.bot_done)
            cells = sorted((x, z) for (x, _y, z) in world)
            self.assertEqual(cells, self._want_cells(), f"漏建：{cells}")
            # 移除 bot 后进度不得回退（_placed_seed + Σ _new_placed 口径）
            self.assertEqual(samples, sorted(samples), f"移除 bot 后进度回退：{samples}")
        finally:
            await coord.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
