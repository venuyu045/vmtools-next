"""地图画几何 / 编排纯函数单测（0-based 坐标铁律）。

覆盖：
  - ``partition_rectangular``：strip 模式按 Z 切条（含 n>depth、余数分配、全覆蓋不重叠）
  - ``build_2d_matrix``：投影 layers → 2D 矩阵（key 必须是 0-based ``(x_rel, z_rel)``）
  - ``plan_squad``：column 模式排级编队（column_x 从 0 开始；剩余列不足只启用前 n 台）
  - ``ColumnRegion.z_order``：**反向排（z_start=size-1 / z_end=0）必须倒序非空**
    —— 这是 Lead 修过的真实 bug（直接 ``range(z_start, z_end+1)`` 得到空列表，
    蛇形第二排整列一格都不建）

跑法::

    python3 -m unittest discover -s backend/tests -p 'test_map_art_*.py' -v
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import install  # noqa: E402

install()

from vmtools_next.core.map_art import (  # noqa: E402
    ColumnRegion,
    Region,
    build_2d_matrix,
    column_cells,
    partition_rectangular,
    plan_squad,
    region_cells,
    rel_of,
    world_of,
)


class TestPartitionRectangular(unittest.TestCase):
    """strip 模式：W×D 矩形按 Z 切成 n 条。"""

    def test_exact_split(self):
        regions = partition_rectangular(8, 6, 3)
        self.assertEqual(len(regions), 3)
        for r in regions:
            self.assertEqual((r.x_start, r.x_end), (0, 7))  # 每条覆盖完整 X
        self.assertEqual([(r.z_start, r.z_end) for r in regions],
                         [(0, 1), (2, 3), (4, 5)])

    def test_remainder_goes_to_first_regions(self):
        # 10 行 / 3 bot → 4 + 3 + 3（余数 1 给第一个分区）
        regions = partition_rectangular(4, 10, 3)
        self.assertEqual([r.rows for r in regions], [4, 3, 3])
        self.assertEqual([(r.z_start, r.z_end) for r in regions],
                         [(0, 3), (4, 6), (7, 9)])

    def test_remainder_two(self):
        # 8 行 / 3 bot → 3 + 3 + 2
        regions = partition_rectangular(4, 8, 3)
        self.assertEqual([r.rows for r in regions], [3, 3, 2])

    def test_n_greater_than_depth(self):
        # n>depth：多出来的 bot 不分配（min(n, depth)），不产生空分区
        regions = partition_rectangular(5, 2, 5)
        self.assertEqual(len(regions), 2)
        self.assertTrue(all(r.rows == 1 for r in regions))
        self.assertEqual([(r.z_start, r.z_end) for r in regions], [(0, 0), (1, 1)])

    def test_cover_all_rows_without_overlap(self):
        for depth in (1, 2, 3, 7, 13):
            for n in (1, 2, 3, 5, 9):
                regions = partition_rectangular(3, depth, n)
                rows = []
                for r in regions:
                    rows.extend(range(r.z_start, r.z_end + 1))
                self.assertEqual(sorted(rows), list(range(depth)),
                                 f"depth={depth} n={n} 覆盖错误: {rows}")
                self.assertEqual(len(rows), len(set(rows)),
                                 f"depth={depth} n={n} 分区重叠")

    def test_degenerate_inputs(self):
        self.assertEqual(partition_rectangular(0, 5, 2), [])
        self.assertEqual(partition_rectangular(5, 0, 2), [])
        self.assertEqual(partition_rectangular(5, 5, 0), [])
        self.assertEqual(partition_rectangular(5, 5, -1), [])


class TestBuild2dMatrix(unittest.TestCase):
    """投影 layers → 2D 矩阵（0-based 相对坐标）。"""

    def test_flattens_layers_to_relative_keys(self):
        layers = {
            0: [(0, 0, 0, "minecraft:white_wool"), (3, 0, 2, "minecraft:black_wool")],
        }
        matrix = build_2d_matrix(layers)
        self.assertEqual(matrix, {
            (0, 0): "minecraft:white_wool",
            (3, 2): "minecraft:black_wool",
        })

    def test_y_dropped_and_later_layer_wins(self):
        # 地图画是单层平面：y 丢弃；后写覆盖前写
        layers = {
            0: [(1, 5, 1, "minecraft:white_wool")],
            1: [(1, 6, 1, "minecraft:red_wool")],
        }
        self.assertEqual(build_2d_matrix(layers), {(1, 1): "minecraft:red_wool"})

    def test_empty(self):
        self.assertEqual(build_2d_matrix({}), {})
        self.assertEqual(build_2d_matrix(None), {})

    def test_size_inference_is_0_based(self):
        from vmtools_next.core.map_art.geometry import plane_size, resolve_size

        matrix = {(0, 0): "a", (3, 1): "b"}
        self.assertEqual(plane_size(matrix), (4, 2))     # max(index)+1，不是 max(index)
        self.assertEqual(resolve_size({}, matrix), (4, 2))
        # 投影声明更大时取声明值
        projection = {"regions": {"Main": {"size": {"x": 8, "z": 5}}}}
        self.assertEqual(resolve_size(projection, matrix), (8, 5))


class TestPlanSquad(unittest.TestCase):
    """column 模式排级编队 —— 列号必须 0-based。"""

    def test_first_squad_starts_at_column_zero(self):
        plan = plan_squad(5, 4, ["a", "b"], squad_index=1)
        self.assertEqual([a.column_x for a in plan.assignments], [0, 1])
        self.assertEqual((plan.col_start, plan.col_end), (0, 1))
        # 0-based 的根断言：首排第一列 == 0（旧实现 range(1, n+1) 会从 1 开始）
        self.assertEqual(plan.assignments[0].column_x, 0)
        self.assertEqual(plan.remaining_columns, 3)
        self.assertFalse(plan.is_last)

    def test_rows_and_direction(self):
        plan = plan_squad(5, 4, ["a", "b"], squad_index=1, direction=1)
        for a in plan.assignments:
            self.assertEqual((a.z_start, a.z_end), (0, 3))
        plan = plan_squad(5, 4, ["a", "b"], squad_index=2, direction=-1)
        for a in plan.assignments:
            self.assertEqual((a.z_start, a.z_end), (3, 0))   # 蛇形掉头

    def test_columns_advance_per_squad(self):
        plan1 = plan_squad(5, 4, ["a", "b"], squad_index=1)
        plan2 = plan_squad(5, 4, ["a", "b"], squad_index=2)
        plan3 = plan_squad(5, 4, ["a", "b"], squad_index=3)
        self.assertEqual([a.column_x for a in plan1.assignments], [0, 1])
        self.assertEqual([a.column_x for a in plan2.assignments], [2, 3])
        self.assertEqual([a.column_x for a in plan3.assignments], [4])
        self.assertTrue(plan3.is_last)
        self.assertEqual(plan3.remaining_columns, 0)

    def test_remaining_columns_fewer_than_bots(self):
        # 5 列 3 bot：第 2 排只剩 2 列 → 只启用前 2 台 bot（编号靠前者）
        plan = plan_squad(5, 4, ["a", "b", "c"], squad_index=2)
        self.assertEqual(plan.active_bot_ids, ["a", "b"])
        self.assertEqual([a.column_x for a in plan.assignments], [3, 4])
        self.assertTrue(plan.is_last)

    def test_no_remaining_columns(self):
        plan = plan_squad(2, 4, ["a", "b"], squad_index=2)
        self.assertEqual(plan.assignments, [])
        self.assertTrue(plan.is_last)
        self.assertLess(plan.col_end, plan.col_start)

    def test_start_column_breakpoint(self):
        # 运行中增减 bot 后按剩余列重排的断点
        plan = plan_squad(10, 4, ["a"], squad_index=1, start_column=6)
        self.assertEqual([a.column_x for a in plan.assignments], [6])
        self.assertEqual(plan.remaining_columns, 3)

    def test_degenerate_inputs(self):
        self.assertEqual(plan_squad(0, 4, ["a"]).assignments, [])
        self.assertEqual(plan_squad(4, 0, ["a"]).assignments, [])
        self.assertEqual(plan_squad(4, 4, []).assignments, [])


class TestColumnRegionZOrder(unittest.TestCase):
    """``ColumnRegion.z_order`` —— Lead 修过的真实 bug（反向排空列表）。"""

    def test_forward(self):
        self.assertEqual(ColumnRegion(0, 0, 3, 1).z_order(), [0, 1, 2, 3])

    def test_reversed_squad_params(self):
        # 蛇形第二排：调用方传 z_start=size-1, z_end=0 → 必须倒序且非空
        region = ColumnRegion(2, 3, 0, -1)
        order = region.z_order()
        self.assertEqual(order, [3, 2, 1, 0])
        self.assertEqual(len(order), 4)
        self.assertEqual(region.block_count, 4)          # 旧实现 abs 已对，z_order 才是空

    def test_reversed_bounds_normalized(self):
        region = ColumnRegion(2, 3, 0, -1)
        self.assertEqual(region.bounds(), (2, 2, 0, 3))  # lo/hi 归一化
        self.assertEqual(region.world_x_offset, 2)       # 0-based 直接相加

    def test_single_row(self):
        self.assertEqual(ColumnRegion(0, 1, 1, 1).z_order(), [1])
        self.assertEqual(ColumnRegion(0, 1, 1, -1).z_order(), [1])

    def test_plan_squad_reversed_region_is_buildable(self):
        # 端到端串起来：plan_squad(direction=-1) → SquadAssignment → ColumnRegion
        # → column_cells 必须给出全部格子（bug 时这里是空列表，整列不建）
        matrix = {(4, z): "minecraft:white_wool" for z in range(4)}
        plan = plan_squad(5, 4, ["a"], squad_index=1, direction=-1, start_column=4)
        region = plan.assignments[0].to_column_region()
        cells = column_cells(matrix, region)
        self.assertEqual([z for _x, z, _b in cells], [3, 2, 1, 0])
        self.assertEqual(len(cells), 4)

    def test_column_cells_forward(self):
        matrix = {(0, z): "minecraft:white_wool" for z in range(3)}
        cells = column_cells(matrix, ColumnRegion(0, 0, 2, 1))
        self.assertEqual([(x, z) for x, z, _b in cells], [(0, 0), (0, 1), (0, 2)])


class TestRegionCellsAndCoords(unittest.TestCase):
    """region_cells + 坐标铁律（world = origin + rel）。"""

    def test_region_cells_skips_air(self):
        matrix = {(0, 0): "minecraft:white_wool", (1, 0): "minecraft:air",
                  (0, 1): "minecraft:black_wool"}
        cells = region_cells(matrix, Region(0, 1, 0, 1))
        self.assertEqual([(x, z) for x, z, _b in cells], [(0, 0), (0, 1)])
        self.assertEqual(len(region_cells(matrix, Region(0, 1, 0, 1), skip_air=False)), 3)

    def test_world_rel_roundtrip(self):
        origin = (100, 64, 200)
        self.assertEqual(world_of(origin, 0, 0), (100, 64, 200))   # 首格 == origin
        self.assertEqual(world_of(origin, 3, 2), (103, 64, 202))
        self.assertEqual(rel_of(origin, 103, 202), (3, 2))

    def test_region_properties(self):
        region = Region(0, 3, 0, 1)
        self.assertEqual((region.cols, region.rows, region.block_count), (4, 2, 8))
        self.assertTrue(region.contains(3, 1))
        self.assertFalse(region.contains(4, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
