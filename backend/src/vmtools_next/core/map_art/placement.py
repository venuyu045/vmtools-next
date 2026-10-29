"""单格放置语义 —— 两套引擎（strip / column）共用的唯一实现。

重构前 ``_place_row``（strip）与 ``build_column``（column）各写了一遍
「移动站立点 → 脚下实体校验 → 已验证跳过 → 选物品 → 放置重试 → 记录进度」，
两份逻辑已经开始漂移（列式那份漏了 `_update_place_interval` 采样、
strip 那份漏了透明格跨越）。这里抽成两个自由函数：

  - ``ensure_stand``  把 bot 挪到指定站立点并校验脚下实体（返回 ok/gap/fail）
  - ``place_cell``    对一个目标格执行「验证 → 选物品 → 放置 → 记账」

引擎只负责「按什么顺序遍历格子」与「站立点如何推导」，放置语义只有这一份。
依赖 ``BotRuntime`` 的公开能力（``_verify_block`` / ``_ensure_item_in_hand`` /
``_place_with_retry`` / ``_activity`` / ``_pending_gaps`` / ``_db_updates`` /
``_placed_coords`` / ``progress`` / ``origin``），便于用 FakeAgent 单测。
"""

from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.core.map_art.types import (
    STATE_OFFLINE,
    CellResult,
    world_of,
)

logger = logging.getLogger("vmtools.map_art.placement")


async def ensure_stand(rt, stand: tuple[int, int, int], label: str = "") -> str:
    """把 bot 移动到站立点并校验脚下实体。

    返回：
      - ``"ok"``  已到位且脚下实体
      - ``"gap"`` 站立点脚下非实体（上一格没放成功）→ 调用方跳过该格并记待补
      - ``"fail"`` 移动失败（bot 被传送/卡走）→ 调用方决定传送兜底或收工
    """
    mv = await rt._move_to_step(stand[0], stand[1], stand[2],
                               label=label or f"stand({stand[0]},{stand[2]})")
    if mv == "gap":
        return "gap"
    if not mv:
        # 站立点不可达 → 传送兜底一次再试
        if await rt._try_teleport_home("站立点移动失败"):
            if not await rt._move_to(stand[0], stand[1], stand[2], max_offset=1,
                                     label=f"stand retry({stand[0]},{stand[2]})",
                                     verify_height=True):
                rt.progress.state = STATE_OFFLINE
                return "fail"
        else:
            rt.progress.state = STATE_OFFLINE
            return "fail"
    if not await rt._stand_solid(stand[0], stand[1], stand[2]):
        return "gap"
    return "ok"


async def place_cell(rt, x_rel: int, z_rel: int, block_id: str,
                     *, label: str = "") -> CellResult:
    """对相对坐标 ``(x_rel, z_rel)`` 执行放置，并完成进度记账。

    顺序与历史行为一致（Via 代理下的容错语义不变）：
      1. 世界读回已是期望方块 → ``verified``（跳过放置，仍算完成）
      2. 手持物品就绪失败 → ``no_material``（记待补，绝不手持错物品放）
      3. 放置重试（内部含弱确认/错色重试）→ ``placed``
      4. 失败 → ``failed``（记待补）
    """
    wx, wy, wz = world_of((rt.origin_x, rt.origin_y, rt.origin_z), x_rel, z_rel)
    expected = block_id

    # 1) 已放且正确 → 直接记账（踩上由调用方处理）
    if await rt._verify_block(wx, wy, wz, expected):
        res = CellResult(x_rel, z_rel, block_id, "verified")
        _record(rt, res, wx, wy, wz)
        return res

    # 2) 选物品（失败显式跳过，防手持错物品）
    if not await rt._ensure_item_in_hand(block_id):
        res = CellResult(x_rel, z_rel, block_id, "no_material",
                         detail=rt._normalize_item_id(block_id))
        _record(rt, res, wx, wy, wz)
        return res

    # 3) 放置（含放置后分层校验）
    if await rt._place_with_retry(wx, wy, wz, block_id):
        res = CellResult(x_rel, z_rel, block_id, "placed")
        _record(rt, res, wx, wy, wz)
        return res

    # 4) 失败
    res = CellResult(x_rel, z_rel, block_id, "failed", detail=label)
    _record(rt, res, wx, wy, wz)
    return res


def _record(rt, res: CellResult, wx: int, wy: int, wz: int) -> None:
    """把结果写入进度/待补/待落库集合（两引擎统一）。"""
    if res.ok:
        rt.progress.record_place()
        if res.outcome == "placed":
            rt._new_placed = getattr(rt, "_new_placed", 0) + 1
        rt.progress.last_completed_x = res.x_rel
        rt._db_updates.append((wx, wy, wz, res.block_id))
        rt._placed_coords.add((wx, wy, wz))
        if res.outcome == "verified":
            rt._activity("debug", f"({wx},{wz}) 已放置，跳过")
        else:
            rt._activity("debug", f"放置成功 ({wx},{wz}) {rt._normalize_item_id(res.block_id)}")
        return

    # 失败/缺料/缺口 → 待补清单（下次续建/完成前对账兜底）
    rt._pending_gaps.append((wx, wy, wz, res.block_id))
    if res.outcome == "no_material":
        rt._activity("warn", f"无法获取材料 {rt._normalize_item_id(res.block_id)}，跳过放置 ({wx},{wz})")
    elif res.outcome == "failed":
        rt._activity("warn",
                     f"放置失败 ({wx},{wz}) {rt._normalize_item_id(res.block_id)}"
                     f"（重试{getattr(rt, '_place_retries', 3)}次仍失败）")


def next_stand_from_cell(origin: tuple[int, int, int], x_rel: int, z_rel: int) -> tuple[int, int, int]:
    """「边放边踩」：下一格站立点 = 本格方块顶（脚 y = origin_y + 1）。"""
    return (origin[0] + x_rel, origin[1] + 1, origin[2] + z_rel)


def stand_of_previous(origin: tuple[int, int, int],
                      prev: Optional[tuple[int, int]], 
                      fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    """上一格存在 → 站其顶；否则用 fallback（行首北缘 / 起始条）。"""
    if prev is None:
        return fallback
    return next_stand_from_cell(origin, prev[0], prev[1])
