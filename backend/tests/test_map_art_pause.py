"""暂停语义 + 终态判定回归。

背景（Lead 2026-10-28 修复）：列式引擎里「某个 loop 处于 ``STATE_WAITING``」有两种含义 ——
  - 用户点了暂停 → 期望 ``build_progress.status == "paused"``
  - 本列建完、等下一排分配 → **正常建造间歇，绝不能报 paused**
旧 ``_aggregate`` 用「任一 loop waiting 即 paused」判定（且是死代码），会把正常间歇
误报成暂停。修复后改为协调器级 ``_paused_by_user`` 标志。

本文件锁死三条语义：
  1. ``pause()`` → ``_aggregate().status == "paused"``
  2. ``resume()`` → ``"running"``
  3. loop 处于 waiting 但用户没暂停 → 必须是 ``"running"``（回归防回退）

另外补 Lead 报告的「offline 必须计入失败」终态判定（``_on_loop_done`` + 全员离线）。

跑法::

    python3 -m unittest discover -s backend/tests -p 'test_map_art_*.py' -v
"""

from __future__ import annotations

import asyncio
import os
import sys
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
)
from vmtools_next.core.map_art.types import (  # noqa: E402
    STATE_OFFLINE,
    STATE_PLACING,
    STATE_WAITING,
)

WHITE = "minecraft:white_wool"
BLACK = "minecraft:black_wool"


def make_coord(task_id: str = "tpause", sx: int = 3, sz: int = 2) -> MultiBotCoordinator:
    """3×2 小任务（3 列 2 行）—— 列池非空，保证 ``_compute_status`` 走到暂停判定。"""
    colors = [WHITE, BLACK]
    matrix = {(x, z): colors[(x + z) % 2] for x in range(sx) for z in range(sz)}
    return MultiBotCoordinator(
        task_id=task_id,
        projection_data={
            "layers": {0: [(x, 0, z, b) for (x, z), b in matrix.items()]},
            "regions": {"Main": {"size": {"x": sx, "z": sz}}},
        },
        origin_x=0, origin_y=64, origin_z=0,
    )


def attach_loop(coord: MultiBotCoordinator, bot_id: str,
                column_x: int = 0, agent: FakeAgent | None = None) -> ColumnBuildLoop:
    """把一个真实 ColumnBuildLoop 挂进协调器（不 run，只用于状态判定）。"""
    agent = agent or FakeAgent(bot_id)
    loop = coord._make_loop(
        bot_id, bot_id.upper(), agent, ColumnBuildLoop,
        column_region=ColumnRegion(column_x, 0, coord._size_z - 1, 1),
    )
    coord._loops[bot_id] = loop
    if bot_id not in coord._active_bot_ids:
        coord._active_bot_ids.append(bot_id)
    coord._squad.active_bots = list(coord._active_bot_ids)
    return loop


class TestPauseSemantics(unittest.IsolatedAsyncioTestCase):
    async def test_pause_reports_paused(self):
        coord = make_coord()
        attach_loop(coord, "mf-001")
        self.assertEqual(coord._aggregate().status, "running")

        await coord.pause()
        state = coord._aggregate()
        self.assertEqual(state.status, "paused")
        self.assertEqual(state.to_payload()["status"], "paused")
        self.assertEqual(coord._loops["mf-001"].progress.state, STATE_WAITING)
        # 暂停也必须落盘（DB 里 status=paused），否则前端刷新又变 running
        self.assertTrue(any("任务已暂停" in e["message"]
                            for e in coord.activity.recent(50)))

    async def test_resume_restores_running(self):
        coord = make_coord()
        attach_loop(coord, "mf-001")
        await coord.pause()
        self.assertEqual(coord._aggregate().status, "paused")

        await coord.resume()
        self.assertEqual(coord._aggregate().status, "running")
        self.assertEqual(coord._loops["mf-001"].progress.state, STATE_PLACING)

    async def test_waiting_loop_without_user_pause_is_not_paused(self):
        """回归：列建完等下一排（loop waiting）不是暂停。"""
        coord = make_coord()
        loop = attach_loop(coord, "mf-001")
        # 模拟「本列建完 → 等下一排分配」的真实间歇
        loop.progress.state = STATE_WAITING
        self.assertFalse(coord._paused_by_user)
        self.assertEqual(coord._aggregate().status, "running",
                         "loop waiting 但用户没暂停，被误报成 paused")

    async def test_all_loops_waiting_still_running(self):
        """两排之间所有 bot 都在 waiting —— 仍然不能报 paused。"""
        coord = make_coord()
        loops = [attach_loop(coord, bid, column_x=i)
                 for i, bid in enumerate(("mf-001", "mf-002"))]
        for loop in loops:
            loop.progress.state = STATE_WAITING
        self.assertEqual(coord._aggregate().status, "running")

    async def test_pause_wins_over_waiting(self):
        coord = make_coord()
        loop = attach_loop(coord, "mf-001")
        loop.progress.state = STATE_WAITING
        await coord.pause()
        self.assertEqual(coord._aggregate().status, "paused")
        await coord.resume()
        self.assertEqual(coord._aggregate().status, "running")


class TestFailureTerminalState(unittest.IsolatedAsyncioTestCase):
    """终态判定：offline 也算失败，全员离线一律 failed（不能写 completed）。"""

    async def test_offline_loop_counted_as_failed(self):
        coord = make_coord()
        attach_loop(coord, "mf-001")
        # 走真实路径：loop 判 offline → _on_bot_offline → _mark_offline → _on_loop_done
        coord._mark_offline("mf-001", "test")
        coord._on_loop_done("mf-001")
        self.assertIn("mf-001", coord._failed_loops,
                      "offline 的 loop 没计入 _failed_loops → 任务可能被误判 completed")
        self.assertEqual(coord._compute_status(), "failed")

    async def test_all_offline_finish_marks_failed(self):
        coord = make_coord()
        loop = attach_loop(coord, "mf-001")
        loop.progress.state = STATE_OFFLINE
        with fast_teleport_settle():
            await coord.finish_task(reconcile=False)
        logs = [e["message"] for e in coord.activity.recent(100)]
        self.assertTrue(any(m.startswith("任务结束：失败") for m in logs),
                        f"全员离线却写了成功终态：{logs[-5:]}")
        self.assertTrue(any("全员离线" in m for m in logs),
                        "缺少「全员离线」告警日志")

    async def test_aggregate_status_after_failed_finish(self):
        """失败收尾后，周期推送的 status 必须也是 failed。

        回归（QA 2026-10-28 抓到、Lead 已修）：``finish_task`` 开头就置
        ``_completion_notified = True``，若 ``_compute_status`` 先判它就会恒返回
        ``completed`` —— DB 里是 failed、``_emit_final`` 那一次推送也是 failed，但
        ``_push_loop`` 每 2s 的 ``build_progress`` 会把前端翻回「已完成」。
        修复：新增 ``_final_status``，三处 ``_compute_status`` 先判它。
        """
        coord = make_coord()
        loop = attach_loop(coord, "mf-001")
        loop.progress.state = STATE_OFFLINE
        with fast_teleport_settle():          # 收尾会传送回兜底点，跳过 3.5s 落地等待
            await coord.finish_task(reconcile=False)
        self.assertEqual(coord._aggregate().status, "failed")
        self.assertEqual(coord._final_status, "failed")

    async def test_aggregate_status_after_success_finish(self):
        """对称用例：成功收尾后 status 必须是 completed（且不能被 paused 等覆盖）。"""
        coord = make_coord()
        attach_loop(coord, "mf-001")          # loop 正常在跑（非 offline）
        with fast_teleport_settle():
            await coord.finish_task(reconcile=False)
        self.assertEqual(coord._aggregate().status, "completed")
        self.assertEqual(coord._final_status, "completed")
        logs = [e["message"] for e in coord.activity.recent(100)]
        self.assertTrue(any(m.startswith("任务结束：完成") for m in logs), logs[-5:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
