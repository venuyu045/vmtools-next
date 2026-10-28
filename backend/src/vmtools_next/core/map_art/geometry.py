"""地图画几何与编排 —— 纯函数层（无 IO / 无框架依赖，可单测）。

包含：
  - ``build_2d_matrix``      投影 layers → 2D 相对坐标矩阵
  - ``partition_rectangular``strip 模式：W×D 按 Z 切 N 条
  - ``assign_supply_boxes``  每个分区北缘中点放补给箱
  - ``plan_squad``           column 模式：一排（n 列）编队计划（0-based）
  - ``column_cells`` / ``region_cells``  工作单元 → 待放置格列表

坐标约定见 ``types.py``：全部 0-based 相对坐标。
"""

from __future__ import annotations

from typing import Iterable, Optional

from vmtools_next.core.map_art.types import (
    ColumnRegion,
    Region,
    SquadAssignment,
    SquadPlan,
)

# 地图画允许的最大边长（防异常投影把编排算爆）
MAX_SIZE = 4096


def build_2d_matrix(layers: dict[int, list[tuple[int, int, int, str]]]) -> dict[tuple[int, int], str]:
    """把 ``layers``（y_offset → [(x, y, z, block_id)]，相对坐标）压平成 2D 矩阵。

    地图画是单层平面，y 丢弃；后写覆盖前写（与历史行为一致）。
    key 为 ``(x_rel, z_rel)``，0-based。
    """
    matrix: dict[tuple[int, int], str] = {}
    for _y_offset, blocks in (layers or {}).items():
        for wx, _wy, wz, block_id in blocks:
            matrix[(int(wx), int(wz))] = block_id
    return matrix


def plane_size(matrix: dict[tuple[int, int], str]) -> tuple[int, int]:
    """从矩阵推算 (size_x, size_z)：``max(index) + 1``（0-based 语义）。"""
    if not matrix:
        return (0, 0)
    return (max(k[0] for k in matrix) + 1, max(k[1] for k in matrix) + 1)


def resolve_size(projection: dict, matrix: dict[tuple[int, int], str]) -> tuple[int, int]:
    """优先用投影声明的尺寸，缺失/异常时用矩阵推算（二者不一致取较大值）。"""
    size_x = size_z = 0
    try:
        size = ((projection or {}).get("regions") or {}).get("Main", {}).get("size") or {}
        size_x = int(size.get("x") or 0)
        size_z = int(size.get("z") or 0)
    except Exception:
        size_x = size_z = 0
    mx, mz = plane_size(matrix)
    size_x = max(size_x, mx)
    size_z = max(size_z, mz)
    # 防御：异常尺寸回退默认 128（历史行为），并夹在合法区间
    size_x = size_x if 1 <= size_x <= MAX_SIZE else 128
    size_z = size_z if 1 <= size_z <= MAX_SIZE else 128
    return size_x, size_z


def partition_rectangular(width: int, depth: int, n: int) -> list[Region]:
    """strip 模式：把 W×D 矩形按 Z 切成 n 条，每条覆盖完整 X ``[0, width-1]``。

    余数分给前 ``depth % n`` 个分区（每区多 1 行）；``n > depth`` 时多出的 bot 不分配
    （返回的分区数可能少于 n，调用方需按 ``len(regions)`` 建 loop）。
    """
    if n <= 0 or width <= 0 or depth <= 0:
        return []
    n = min(n, depth)
    rows_per_bot = depth // n
    remainder = depth % n
    regions: list[Region] = []
    z = 0
    for i in range(n):
        h = rows_per_bot + (1 if i < remainder else 0)
        if h <= 0:
            continue
        regions.append(Region(0, width - 1, z, z + h - 1))
        z += h
    return regions


def assign_supply_boxes(
    regions: list[Region],
    origin_x: int,
    origin_y: int,
    origin_z: int,
    y_offset: int = -1,
) -> list[tuple[int, int, int]]:
    """每个分区北缘中点放一个补给箱（世界坐标）；y = origin_y + y_offset。"""
    boxes: list[tuple[int, int, int]] = []
    for r in regions:
        mid_x = origin_x + (r.x_start + r.x_end) // 2
        box_z = origin_z + r.z_start - 2
        boxes.append((mid_x, origin_y + y_offset, box_z))
    return boxes


# ──────────────────────────────────────────────
# column 模式编排（纯函数，核心可测逻辑）
# ──────────────────────────────────────────────

def plan_squad(
    size_x: int,
    size_z: int,
    bot_ids: list[str],
    squad_index: int = 1,
    direction: int = 1,
    start_column: Optional[int] = None,
) -> SquadPlan:
    """规划第 ``squad_index`` 排（0-based 列号）。

    规则（对齐任务文档「排内并行 → 排尾同步 → 整排推进 → 蛇形掉头」）：
      - 每排宽度 = 当前可用 bot 数 n；列区间 ``[col_start, col_end]``（含端点）
      - 剩余列不足 n 时只启用前 ``n'`` 台 bot（编号靠前者）
      - 方向 1 → 每列从 ``z=0`` 建到 ``z=size_z-1``；方向 -1 → 反向（蛇形掉头）
      - ``start_column`` 用于「运行中增减 bot 后按剩余列重排」的断点
    """
    n = len(bot_ids)
    if size_x <= 0 or size_z <= 0 or n <= 0:
        return SquadPlan(squad_index, direction, [], 0, -1, size_x, size_z, 0, True)

    col_start = (squad_index - 1) * n if start_column is None else max(0, start_column)
    col_end = min(col_start + n - 1, size_x - 1)
    if col_end < col_start:  # 已无剩余列
        return SquadPlan(squad_index, direction, [], col_start, col_start - 1,
                         size_x, size_z, 0, True)

    count = col_end - col_start + 1
    z_start, z_end = (0, size_z - 1) if direction >= 0 else (size_z - 1, 0)
    assignments: list[SquadAssignment] = []
    for i in range(count):
        assignments.append(SquadAssignment(
            bot_id=bot_ids[i],
            column_x=col_start + i,
            direction=direction,
            z_start=z_start,
            z_end=z_end,
        ))
    remaining = size_x - (col_end + 1)
    return SquadPlan(
        squad_index=squad_index,
        direction=direction,
        assignments=assignments,
        col_start=col_start,
        col_end=col_end,
        total_columns=size_x,
        total_rows=size_z,
        remaining_columns=max(0, remaining),
        is_last=remaining <= 0,
    )


def columns_of(plan: SquadPlan) -> list[int]:
    return [a.column_x for a in plan.assignments]


def region_cells(
    matrix: dict[tuple[int, int], str],
    region: Region,
    *,
    skip_air: bool = True,
) -> list[tuple[int, int, str]]:
    """区域内的待放置格 ``[(x_rel, z_rel, block_id)]``（行优先，按 z 升序）。"""
    out: list[tuple[int, int, str]] = []
    for z in range(region.z_start, region.z_end + 1):
        for x in range(region.x_start, region.x_end + 1):
            bid = matrix.get((x, z))
            if skip_air and (not bid or bid == "minecraft:air"):
                continue
            if bid:
                out.append((x, z, bid))
    return out


def column_cells(
    matrix: dict[tuple[int, int], str],
    col: ColumnRegion,
    *,
    skip_air: bool = True,
) -> list[tuple[int, int, str]]:
    """单列待放置格，按建造方向排序。"""
    out: list[tuple[int, int, str]] = []
    for z in col.z_order():
        bid = matrix.get((col.column_x, z))
        if skip_air and (not bid or bid == "minecraft:air"):
            continue
        if bid:
            out.append((col.column_x, z, bid))
    return out


def cells_in_bounds(
    matrix: dict[tuple[int, int], str],
    bounds: tuple[int, int, int, int],
    *,
    skip_air: bool = True,
) -> Iterable[tuple[int, int, str]]:
    """矩形 bounds 内的待放置格（生成器，大图不占内存峰值）。"""
    x0, x1, z0, z1 = bounds
    for z in range(z0, z1 + 1):
        for x in range(x0, x1 + 1):
            bid = matrix.get((x, z))
            if not bid:
                continue
            if skip_air and bid == "minecraft:air":
                continue
            yield (x, z, bid)


def tile_ranges(start: int, end: int, tile: int = 128) -> list[tuple[int, int]]:
    """把一维区间切成 ≤tile 的瓦片（大范围扫描防 WS 大帧）。"""
    if end < start:
        return []
    out: list[tuple[int, int]] = []
    cur = start
    while cur <= end:
        out.append((cur, min(cur + tile - 1, end)))
        cur += tile
    return out
