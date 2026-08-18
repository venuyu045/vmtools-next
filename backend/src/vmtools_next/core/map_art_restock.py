"""map_art_restock.py — 地图画补货决策与执行模块（2026-08-15 第一批重构）

迁移 playercontrolpp AutoRestockFeature 的 target/have 缺料模型与
ContainerOpener / ItemTransferExecutor 的执行模式，配合现有 BotBuildLoop：

- RestockPlanner：target/have 缺料计算
  target = min(区域剩余需求, stacks×64)（stacks 默认 4，config.map_art_restock_stacks）
  have  = 背包散装数量；need ⟺ have < target
  未配置潜影盒坐标的材料：记录但不取（用户确认：提示跳过）
  取料顺序：满足度（have/target）最低优先（round-robin，防一种材料塞满背包）
- ShulkerRestocker：一次"寻路→开箱→取货→关箱→背包确认"的执行器
  dryTicks 取空记忆（本轮已判定无货的坐标跳过，防重复开空盒）
  背包满检查；withdraw 后背包轮询确认（防假成功）

依赖注入（不依赖 BotBuildLoop 内部）：
  mcp            — mineflayer 客户端（move_to/open_container_at/withdraw_container_item/close_container）
  check_inventory— async (clean_id: str) -> int，背包散装量查询（调用方实现）
  move_to_cb     — async (x, y, z) -> bool，仓库内寻路（调用方包装，allow_scaffold=False）
  activity_cb    — (level, message) -> None，活动日志回调
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("vmtools.map_art_restock")

# 单次取货量（一组）
STACK_SIZE = 64
# withdraw 后背包确认轮询次数/间隔
CONFIRM_ROUNDS = 10
CONFIRM_INTERVAL_S = 0.3


@dataclass
class Need:
    """一种需要补货的材料。"""

    item_id: str                      # 归一化（无 minecraft: 前缀、无 [ 后缀）
    target: int                       # 目标持有量 min(区域剩余需求, N组×64)
    have: int                         # 当前背包散装量
    boxes: list = field(default_factory=list)  # 潜影盒坐标列表（空 = 未配置）

    @property
    def ratio(self) -> float:
        """满足度：越小越缺（补货优先级越高）。"""
        return (self.have / self.target) if self.target > 0 else 1.0

    @property
    def missing(self) -> int:
        return max(0, self.target - self.have)


class RestockPlanner:
    """target/have 缺料计算（对齐 playercontrolpp readMaterialList + ItemTransferStrategy）。

    决策（用户 2026-08-15 确认）：
    - 每种材料补到 target = min(区域剩余需求, stacks×64)，stacks 默认 4
    - 未配置潜影盒坐标的材料：记录（boxes 空）并提示跳过，不取
    - 取料顺序：满足度最低优先
    """

    def __init__(self, stacks_per_item: int = 4):
        self.stacks_per_item = max(1, min(16, int(stacks_per_item)))

    @staticmethod
    def normalize(item_id: str) -> str:
        """去 minecraft: 前缀 + 去 [ 后缀（与 BotBuildLoop._normalize_item_id 一致）。"""
        if not item_id:
            return ""
        item_id = str(item_id).split("[")[0].strip()
        if item_id.startswith("minecraft:"):
            item_id = item_id[len("minecraft:"):]
        return item_id

    @staticmethod
    def region_material_count(block_matrix: dict, region, origin_x: int, origin_z: int) -> dict:
        """统计本 bot 区域各材料需求块数（归一化 key）。O(区域) 一次，调用方缓存。

        block_matrix: {(x, z) -> block_id}（全图）；region: 带 x_start/x_end/z_start/z_end 的对象。
        注意：block_matrix 的 key 是投影相对坐标（x=0..w-1, z=0..d-1），区域也是相对坐标。
        """
        counts: dict[str, int] = {}
        for (rx, rz), bid in block_matrix.items():
            if not (region.x_start <= rx <= region.x_end and region.z_start <= rz <= region.z_end):
                continue
            clean = RestockPlanner.normalize(bid)
            if clean and clean != "air":
                counts[clean] = counts.get(clean, 0) + 1
        return counts

    @staticmethod
    def plan_target(needed_total: int, stacks_per_item: int = 4, stack_max: int = STACK_SIZE) -> int:
        """目标持有量 = min(剩余需求, N组×最大堆叠)，至少 1。"""
        return max(1, min(needed_total, stack_max * max(1, stacks_per_item)))

    def compute_needs(self, region_materials: dict, have_counts: dict,
                      supply_boxes: dict) -> list[Need]:
        """计算缺料清单（按满足度升序 = 最缺的在前）。

        region_materials: {归一化 item_id: 区域需求块数}（region_material_count 产出）
        have_counts:      {归一化 item_id: 背包散装量}
        supply_boxes:     {item_id(任意格式): [坐标...]}（任务级+全局仓库合并后）

        ⚠️ 2026-08-18 用户要求（每种超64仍补货）：【哪种用完只拿哪种，每种只补一组】——
        - 背包还有该材料（have > 0）→ 不补（此前 have<target(256) 就补 → 没用完也拿 → 超64）
        - 完全用完（have == 0）→ 补一组（target = min(64, 区域需求)，不再补 4 组=256）
        """
        needs: list[Need] = []
        for item_id, needed in region_materials.items():
            if have_counts.get(item_id, 0) > 0:
                continue  # 2026-08-18：背包还有 → 不补（用户：没用完的不要拿）
            target = max(1, min(64, needed))  # 2026-08-18：只补一组（64），区域需求不足 64 则按需求
            have = 0
            boxes = []
            for key, box_list in supply_boxes.items():
                if self.normalize(key) == item_id and box_list:
                    boxes = box_list
                    break
            needs.append(Need(item_id=item_id, target=target, have=have, boxes=boxes))
        # 满足度最低优先（最缺的在前）；同满足度按名称稳定排序
        needs.sort(key=lambda n: (n.ratio, n.item_id))
        return needs

    def needs_with_boxes(self, needs: list[Need]) -> list[Need]:
        """仅返回已配置潜影盒坐标的缺料（未配置的由调用方提示后跳过）。"""
        return [n for n in needs if n.boxes]


class ShulkerRestocker:
    """一次"寻路→开箱→取货→关箱→背包确认"的执行器。

    容错（对齐 playercontrolpp ContainerOpener + ItemTransferExecutor）：
    - dryTicks：本轮已判定取空/无货的坐标记入 _drained，后续跳过（防重复开空盒）
    - 开箱失败重试 1 次；withdraw 失败尝试下一坐标
    - 背包满检查：取货前确认有空槽
    - withdraw 后背包轮询确认（最多 3s），未确认视为假成功 → 尝试下一坐标
    """

    def __init__(self, mcp, check_inventory: Callable, move_to_cb: Callable,
                 activity_cb: Optional[Callable] = None, log_prefix: str = ""):
        self._mcp = mcp
        self._check_inventory = check_inventory      # async (clean_id) -> int
        self._move_to_cb = move_to_cb                # async (x, y, z) -> bool
        self._activity = activity_cb or (lambda lv, msg: None)
        self._prefix = log_prefix
        self._drained: set[tuple[int, int, int]] = set()  # 本轮已判定无货坐标

    def reset_drained(self) -> None:
        """新一次补货旅程开始时清空取空记忆。"""
        self._drained.clear()

    async def restock_material(self, clean_id: str, target_count: int, boxes: list) -> int:
        """按坐标列表取货直到背包 ≥ target_count（或坐标取尽）。

        Returns: 背包确认后的实际持有量（>0 表示有收获；可能 < target_count）。
        """
        if not boxes:
            self._activity("warn", f"{clean_id} 任务需要但未配置潜影盒坐标，跳过补货")
            return await self._check_inventory(clean_id)

        for (bx, by, bz) in boxes:
            key = (bx, by, bz)
            if key in self._drained:
                continue
            # 背包已达标 → 提前结束（后续坐标不用再试）
            have = await self._check_inventory(clean_id)
            if have >= target_count:
                return have
            if not await self._has_free_slot():
                self._activity("warn", "背包已满，暂停补货（请先清理背包空间）")
                return have

            got = await self._restock_from_one(clean_id, target_count, bx, by, bz)
            if got > 0:
                return got

        return await self._check_inventory(clean_id)

    # ── 内部 ──

    async def _restock_from_one(self, clean_id: str, target_count: int,
                                bx: int, by: int, bz: int) -> int:
        """单个坐标取货（寻路→开箱→取→关箱→确认）。返回背包确认后的持有量（>0=有收获）。"""
        self._activity("info", f"寻路到潜影盒 ({bx},{by},{bz}) 取 {clean_id}")
        t0 = time.monotonic()
        moved = await self._move_to_cb(bx, by, bz)
        self._activity("debug",
                       f"寻路到 ({bx},{by},{bz}) {'成功' if moved else '失败'}，耗时 {time.monotonic() - t0:.1f}s")
        if not moved:
            # 2026-08-15 P3：寻路失败（客户端 chunk 数据旧/baritone no_path）≠箱子不可达——
            # bot 传送到仓库后可能已在箱子 reach 内，直接尝试开箱（open_container_at
            # 需要靠近才会成功；若太远会失败并返回 0，不影响正确性）。
            self._activity("debug",
                           f"寻路到 ({bx},{by},{bz}) 失败，尝试直接开箱（bot 可能在附近）")
        container_id = await self._open_box(bx, by, bz)
        if not container_id:
            return 0

        # ⚠️ 2026-08-16 修复：Via 不推送窗口/背包更新——容器【打开期间】
        # get_inventory_snapshot 读到的玩家背包恒为空（客户端未同步），
        # 只有【关箱后】服务器才把背包数据同步给客户端。
        # 原实现 with withdraw 后立即 check_inventory（窗口开着）→ 永远读到 0
        # → 明明取到货却误判"未取到"→ 标记 drained → 补货全部失败（真机复现：
        # withdraw success + 关箱后背包有 white_concrete×64，但日志报"未取到"）。
        # 修复：先关箱，再轮询确认背包。
        withdraw_ok = False
        try:
            # 2026-08-15 用户实测纠正：一次只取【一组】（64），不循环到 target——
            # 原循环在背包快照滞后时会把容器搬空（每种颜色拿 256+，背包塞满后续颜色装不下）。
            withdraw_ok = await self._withdraw_once(clean_id, container_id, bx, by, bz)
        finally:
            await self._close_box(container_id)
        # ⚠️ 2026-08-16：关箱是异步（服务器确认窗口关闭后才把背包数据同步给客户端），
        # 立即读背包可能读到【窗口残留数据】→ 误判"取到"（实际背包无货 → 后续 select 失败）。
        # 等 0.8s（Via 关箱同步）再确认。
        await asyncio.sleep(0.8)

        if withdraw_ok:
            # 关箱后（Via 客户端背包已同步）轮询确认
            for _i in range(CONFIRM_ROUNDS):
                await asyncio.sleep(CONFIRM_INTERVAL_S)
                if await self._check_inventory(clean_id) > 0:
                    break
            have = await self._check_inventory(clean_id)
            if have > 0:
                self._activity("info", f"取到 {clean_id} ×{have}（{bx},{by},{bz}）")
                return have
        else:
            # withdraw 返回失败（Node 端找不到物品等）：关箱后仍确认一次背包
            # （防 Node 端误报——点击成功但客户端 selectedItem 未同步）
            have = await self._check_inventory(clean_id)
            if have > 0:
                self._activity("info", f"取到 {clean_id} ×{have}（{bx},{by},{bz}）")
                return have

        # 关箱后确认仍无 → 判定该坐标无货（dryTicks 记忆，本轮跳过）
        self._drained.add((bx, by, bz))
        self._activity("warn", f"{clean_id} 在 ({bx},{by},{bz}) 未取到（可能取空/放错/坐标不符），标记跳过")
        return 0

    async def _move_to_box(self, bx: int, by: int, bz: int) -> bool:
        try:
            return await self._move_to_cb(bx, by, bz)
        except Exception as e:
            self._activity("debug", f"寻路异常：{e}")
            return False

    async def _open_box(self, bx: int, by: int, bz: int) -> str:
        """开箱（失败重试 1 次）。返回 container_id（空=失败）。"""
        for attempt in range(2):
            try:
                open_result = await self._mcp.open_container_at(bx, by, bz, timeout_ms=15000)
            except Exception as e:
                self._activity("debug", f"open_container_at 抛异常：{e}")
                return ""
            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
            cid = (data or {}).get("container_id") or ""
            if cid:
                self._activity("debug",
                               f"开箱成功：{data.get('block_name', '?')} container_id={cid[:8]}.. 槽位={data.get('slot_count', '?')}")
                return cid
            if attempt == 0:
                self._activity("debug", f"开箱失败：{(data or {}).get('error', '?')}，等 1s 重试")
                await asyncio.sleep(1.0)
        self._activity("warn", f"开箱失败（潜影盒 {bx},{by},{bz}），尝试下一个")
        return ""

    async def _withdraw_once(self, clean_id: str, container_id: str, bx: int, by: int, bz: int) -> bool:
        """取一组；成功（背包确认到该材料）返回 True。"""
        try:
            wd = await self._mcp.withdraw_container_item(clean_id, STACK_SIZE, container_id)
        except Exception as e:
            self._activity("warn", f"开箱后取货失败：{e}")
            return False
        if isinstance(wd, dict) and wd.get("success") is False:
            err = wd.get("error", "?")
            c_items = wd.get("container_items") or []
            if c_items:
                self._activity("debug", f"容器内物品（{wd.get('item_count', len(c_items))}种）：{'，'.join(c_items[:15])}")
            self._activity("warn", f"取货失败：{err}，尝试下一个坐标")
            return False
        return True

    async def _close_box(self, container_id: str) -> None:
        try:
            await self._mcp.close_container(container_id)
        except Exception:
            pass

    async def _has_free_slot(self) -> bool:
        """背包是否有空槽（防 withdraw 因背包满失败）。"""
        try:
            snap = await self._mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            # 36 个主背包+快捷栏槽位（0-35）；槽位 36-44 快捷栏已在 0-8 内（归一化后）
            slots = {s.get("slot") for s in items if s.get("count", 0) > 0}
            for i in range(36):
                if i not in slots:
                    return True
            return False
        except Exception:
            return True  # 查询失败不拦截（保持现状行为）
