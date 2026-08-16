"""Map Art Build Coordinator — multi-bot 2D construction engine.

Orchestrates N bots building a single-layer 128×128 (or larger) map art
from a Litematica projection. Each bot gets a rectangular strip of rows
along the Z axis and runs an independent BotBuildLoop.

Key design (per implementation-plan.md Section 3):
  - Strip partition: regions split along Z, each bot covers full X [0, W-1]
  - Edge placement: bot stands z-1 (north edge), places southward
  - Independent loops: no inter-bot coordination needed (no overlapping regions)
  - Progress push: Socket.IO events every 2s or every 10 blocks placed
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.config import get_config
from vmtools_next.core.bluemap_monitor import _point_in_polygon_2d
from vmtools_next.core.map_art_restock import Need, RestockPlanner, ShulkerRestocker
from vmtools_next.data.db import sio

logger = logging.getLogger("vmtools.map_art")


def _restock_serialized(fn):
    """串行化补货协程（2026-08-15 修复并发开箱互相覆盖窗口）。

    主建造循环缺材料、蹲搭前补货、食物监控可能同时触发补货——并发开箱会让
    mineflayer 窗口状态互相覆盖（实测 withdraw 报 Cannot read properties of
    null (reading 'type') + 日志重复出现）。用 per-bot 互斥锁把补货整体串行化。
    """
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        async with self._restock_lock:
            return await fn(self, *args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class Region:
    """Rectangular region assigned to one bot. Coordinates are inclusive."""
    x_start: int
    x_end: int
    z_start: int
    z_end: int

    @property
    def rows(self) -> int:
        return self.z_end - self.z_start + 1

    @property
    def block_count(self) -> int:
        return (self.x_end - self.x_start + 1) * self.rows


@dataclass
class BotProgress:
    """Per-bot runtime progress (in-memory, not DB-persisted every tick)."""
    bot_id: str
    region: Region
    state: str = "idle"           # idle|moving|placing|restocking|completed|offline
    blocks_placed: int = 0
    blocks_total: int = 0
    current_row: int = -1         # the Z-row currently being placed
    last_completed_x: int = -1    # last X placed on current row (for resume)
    place_rate: float = 0.0       # avg blocks/min
    _recent_places: list[float] = field(default_factory=list)  # timestamps for rate calc

    def record_place(self):
        now = time.monotonic()
        self._recent_places.append(now)
        # Keep last 60s
        cutoff = now - 60
        self._recent_places = [t for t in self._recent_places if t > cutoff]
        self.blocks_placed += 1
        if self._recent_places:
            elapsed_min = (now - self._recent_places[0]) / 60
            if elapsed_min > 0:
                self.place_rate = len(self._recent_places) / elapsed_min


@dataclass
class MapArtBuildState:
    """Immutable snapshot of the current build state for Socket.IO push."""
    task_id: str
    status: str
    total_blocks: int
    placed_blocks: int
    bots: list[dict]
    materials: dict[str, dict]    # item_id → {required, placed}
    elapsed_sec: float
    eta_sec: float = 0.0


# ──────────────────────────────────────────────
# Region partition
# ──────────────────────────────────────────────

def partition_rectangular(width: int, depth: int, n: int) -> list[Region]:
    """Split a W×D rectangle into N roughly equal strips along the Z axis.

    Args:
        width: X dimension (usually 128)
        depth: Z dimension (usually 128)
        n: number of bots

    Returns:
        List of Regions, each covering full width [0, width-1]
    """
    if n <= 0:
        return []
    rows_per_bot = depth // n
    remainder = depth % n
    regions = []
    z = 0
    for i in range(n):
        extra = 1 if i < remainder else 0
        h = rows_per_bot + extra
        regions.append(Region(0, width - 1, z, z + h - 1))
        z += h
    return regions


def assign_supply_boxes(
    regions: list[Region],
    origin_x: int, origin_y: int, origin_z: int,
) -> list[tuple[int, int, int]]:
    """Place a supply box at the midpoint of each region's north edge.

    y = origin_y + map_art_supply_box_y_offset（P2-8：默认 -1 把箱放地面层，
    避免悬空；config 可调）。
    Returns list of (x, y, z) for each region's supply box.
    """
    try:
        y_offset = getattr(get_config().mineflayer, "map_art_supply_box_y_offset", -1) or 0
    except Exception:
        y_offset = 0
    boxes = []
    for r in regions:
        mid_x = origin_x + (r.x_start + r.x_end) // 2
        box_z = origin_z + r.z_start - 2  # 2 blocks north of region start
        boxes.append((mid_x, origin_y + y_offset, box_z))
    return boxes


# ──────────────────────────────────────────────
# BotBuildLoop — per-bot independent build loop
# ──────────────────────────────────────────────

class BotBuildLoop:
    """Single bot's independent construction loop.

    Walks rows Z = region.z_start .. region.z_end, placing blocks
    from north edge (standing at Z-1, facing south).
    """

    # EssentialsX传送点（P2-26：从 config 读取，默认 mdssj/gzqy 保持旧行为）
    WAREHOUSE_HOME = "mdssj"
    TEMP_HOME = "gzqy"

    def __init__(
        self,
        bot_id: str,
        bot_name: str,
        task_id: str,
        region: Region,
        block_matrix: dict[tuple[int, int], str],   # (x, z) → block_id
        origin_x: int, origin_y: int, origin_z: int,
        mcp: AbstractBotAgent,
        supply_box: Optional[tuple[int, int, int]] = None,  # 分区补给箱坐标（None→用传送）
        supply_boxes: Optional[dict[str, list[tuple[int, int, int]]]] = None,  # 2026-08-14：材料→潜影盒坐标
        supply_config: Optional[dict] = None,  # 2026-08-14：{go, save, return} 三个传送指令
        food_config: Optional[dict] = None,  # 2026-08-14 模块A：食物配置
        food_boxes: Optional[list[tuple[int, int, int]]] = None,  # 2026-08-14 模块A：猪排潜影盒坐标
        on_done: Optional[callable] = None,  # 正常完成回调（coordinator 用于任务级完成判定）
        on_activity: Optional[callable] = None,  # 2026-08-14 终端：活动日志回调 (bot_id, bot_name, level, message)
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.task_id = task_id
        self.region = region
        self.block_matrix = block_matrix
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.origin_z = origin_z
        self.mcp = mcp

        self.progress = BotProgress(bot_id=bot_id, region=region)
        self.progress.blocks_total = region.block_count
        self._on_done = on_done
        self._on_activity = on_activity  # 2026-08-14 终端：活动日志回调

        self._paused = asyncio.Event()
        self._paused.set()     # start unpaused
        self._stopped = False
        self._current_item: Optional[str] = None  # item currently in hand
        self._current_slot: Optional[int] = None  # 当前手持快捷栏槽位（模块B：动态识别）
        # 2026-08-14 优化：建造区域边界缓存（矩形：cx, cz, half_w, half_h），
        # 首次 _near_build_area 时计算一次（O(N)），之后 O(1)——大尺寸地图画
        # （512/1024+ 格）不能每次全量遍历 block_matrix。
        self._area_bounds: Optional[tuple[float, float, float, float]] = None
        # 2026-08-15 修复：补货互斥锁——防多个协程（主建造循环缺材料 + 蹲搭前补货 +
        # 食物监控）同时触发 _do_full_restock/_do_restock，并发开箱互相覆盖窗口
        # 导致 mineflayer withdraw 读 null selectedItem 崩溃（实测 Cannot read
        # properties of null (reading 'type') + 日志重复出现）。
        self._restock_lock = asyncio.Lock()
        # 2026-08-15 第一批重构（迁移 playercontrolpp target/have 模型）：
        # 补货组数/最小间隔从 config 读取；区域材料需求缓存（懒计算一次）；
        # 零收获计数（连续 N 轮补货无收获 → 区域终止，防缺料死循环）
        try:
            _mf_cfg = get_config().mineflayer
            self._restock_stacks: int = max(1, min(16, int(
                getattr(_mf_cfg, "map_art_restock_stacks", 4) or 4)))
            self._min_restock_interval_s: float = max(0.0, float(
                getattr(_mf_cfg, "map_art_min_restock_interval_s", 90) or 90))
        except Exception:
            self._restock_stacks = 4
            self._min_restock_interval_s = 90.0
        self._last_restock_at: float = 0.0
        self._no_gain_cycles: int = 0
        # 2026-08-15 决定性修复：bot 站立层相对 origin_y 的偏移（默认-1=平台顶=origin_y-1）
        try:
            self._stand_y_offset: int = int(
                getattr(get_config().mineflayer, "map_art_stand_y_offset", 0) or 0)
        except Exception:
            self._stand_y_offset = 0
        # 2026-08-15 环境检测整合（用户需求）：可自定义建造领地 + 建造维度
        try:
            _mf = get_config().mineflayer
            self._build_residence: str = (getattr(_mf, "map_art_residence", "") or "").strip()
            self._build_world: str = (getattr(_mf, "map_art_build_world", "overworld") or "overworld").strip()
        except Exception:
            self._build_residence = ""
            self._build_world = "overworld"
        self._region_materials: Optional[dict] = None  # 区域材料需求（RestockPlanner 产出，懒缓存）
        self._restocker: Optional[ShulkerRestocker] = None  # 懒创建
        self._supply_box: Optional[tuple[int, int, int]] = supply_box  # 分区补给箱坐标（None→用传送）
        # 2026-08-14：材料级潜影盒坐标（用户配置，优先级最高）+ 任务级三个传送指令
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = supply_boxes or {}
        self._supply_cfg: dict = supply_config or self._default_supply_cfg()
        # 2026-08-14 模块A：食物配置 + 猪排潜影盒坐标
        self._food_cfg: dict = food_config or self._default_food_cfg()
        self._food_boxes: list[tuple[int, int, int]] = food_boxes or []
        # 2026-08-14 模块B：快捷栏槽位 → 材料映射缓存（避免每次全背包搜索）
        self._hotbar_map: dict[int, str] = {}  # slot(0-8) → clean_item_id
        self._food_task: Optional[asyncio.Task] = None  # 食物监控协程
        # 2026-08-14：溺水/坠落防护——记录上次血量，持续下降时传送回建造点
        self._last_health: Optional[float] = None

        # P2-26：EssentialsX 传送点名从 config 读取（保持类默认值兼容）
        try:
            _mf = get_config().mineflayer
            if getattr(_mf, "map_art_warehouse_home", None):
                self.WAREHOUSE_HOME = _mf.map_art_warehouse_home
            if getattr(_mf, "map_art_temp_home", None):
                self.TEMP_HOME = _mf.map_art_temp_home
        except Exception:
            pass

        # ── 建造/寻路调参（对齐开发文档：防放错、限速、容错） ──
        # 放置间隔读 config.safety.place_interval_ticks（tick=50ms），下限 0.15s 防高频放置误判
        try:
            _ticks = getattr(get_config().safety, "place_interval_ticks", 3) or 3
            self._place_interval: float = max(0.15, int(_ticks) / 20.0)
        except Exception:
            self._place_interval: float = 0.25
        # 2026-08-16 P2：寻路/放置/兜底参数收敛到 config（config.py mineflayer 段）
        try:
            _mf_cfg2 = get_config().mineflayer
            self._move_retries: int = max(1, int(getattr(_mf_cfg2, "map_art_move_retries", 2) or 2))
            self._place_retries: int = max(1, int(getattr(_mf_cfg2, "map_art_place_retries", 3) or 3))
            # P1-3：高度校验 y 容差（原硬编码 0.6 过严，浮点/台阶抖动误判；双条件改为 y 偏差 + 脚下实体）
            self._verify_y_tol: float = max(0.5, float(getattr(_mf_cfg2, "map_art_verify_y_tol", 1.0) or 1.0))
            # P0-4：传送兜底重试上限（每级 / 总上限）
            self._tp_retry_each: int = max(1, int(getattr(_mf_cfg2, "map_art_tp_retry_each", 3) or 3))
            self._tp_retry_total: int = max(1, int(getattr(_mf_cfg2, "map_art_tp_retry_total", 8) or 8))
        except Exception:
            self._move_retries: int = 2
            self._place_retries: int = 3
            self._verify_y_tol: float = 1.0
            self._tp_retry_each: int = 3
            self._tp_retry_total: int = 8
        self._move_timeout_ms: int = 20000      # 单次寻路超时
        self._place_sample_count: int = 0       # 放置采样计数（RTT 自适应）
        self._last_pos: Optional[tuple[int, int, int]] = None  # 最近一次移动到达的坐标（跳过重复寻路）
        # 2026-08-16 P0-4：最近一次 _move_to 失败原因标签（供兜底分流：no_path/stuck/timeout/height/fall/...）
        self._last_move_fail_reason: str = ""

        # ── 断点续建（DB 持久化）：放置成功/已正确的方块批量写库，行完成 flush ──
        self._db_updates: list[tuple[int, int, int, str]] = []
        self._db_flushed_rows: int = 0
        # P2-9：同 run 内已验证正确的方块集合（跳过重复 get_world_block_at WS 往返）
        self._verified_set: set[tuple[int, int, int]] = set()

        # 2026-08-16 P0-5：放置后校验分层状态
        # _pending_confirm：弱确认（_genericPlace 发出 + 本地复核通过）但尚无服务器权威确认的坐标
        #（行尾复核/启动对账时收敛 verified）
        self._pending_confirm: list[tuple[int, int, int, str]] = []
        # P0-2：站立格前提校验失败的坐标（悬空/缺方块，跳过放置，记入待补清单）
        self._pending_gaps: list[tuple[int, int, int, str]] = []
        # 2026-08-16：运行中已放置坐标集合（世界坐标）——供 blocks/placed 接口
        # 实时返回（不依赖 DB 行尾 flush），前端预览像素即时变深。
        self._placed_coords: set[tuple[int, int, int]] = set()
        # P0-5：对账统计（启动/行/完成）
        self._reconcile_stats: dict = {"start": {}, "row": {}, "done": {}}

    # ── 蛇形寻路：偶数相对行正向（x_start→x_end），奇数行反向（x_end→x_start） ──
    #    行间只需移动 1 格（z+1，x 不变），省掉每行从 x_end 走回 x_start 的 128 格回程。
    def _row_is_forward(self, row_z: int) -> bool:
        return (row_z - self.region.z_start) % 2 == 0

    def _row_x_span(self) -> list[int]:
        """当前行 X 放置顺序（正向升序 / 反向降序）。"""
        xs = list(range(self.region.x_start, self.region.x_end + 1))
        return xs if self._row_is_forward(self.progress.current_row) else xs[::-1]

    # ── Control ──────────────────────────────

    async def pause(self):
        self._paused.clear()
        self.progress.state = "waiting"

    async def resume(self):
        self._paused.set()
        self.progress.state = "placing"

    async def stop(self):
        self._stopped = True
        self._paused.set()  # unblock so loop can exit

    # ── Main loop ────────────────────────────

    async def run(self):
        """Execute the edge-placement build loop for this bot's region."""
        logger.info("[%s] Build loop started: rows %d→%d",
                     self.bot_id, self.region.z_start, self.region.z_end)
        self._activity("info", f"开始建造区域 z[{self.region.z_start}..{self.region.z_end}]")

        # 断点续建：恢复 DB 中已放置进度（已 placed 坐标加载到 _verified_set，
        # 信任 DB 跳过重复 verify——避免 16384 块全量 WS 往返，仅「重新开始」全量核对）
        await self._restore_progress()

        # 2026-08-14 模块A：启动食物监控协程（饱食度/血量低时吃副手猪排）
        self._food_task = asyncio.create_task(self._food_monitor_loop())
        # 2026-08-14 模块B：初始化快捷栏槽位映射（避免每色首次全背包搜索）
        await self._refresh_hotbar_map()

        # 2026-08-15 环境检测整合（用户需求：维度 + 位置 + 附近领地结合）——
        # 启动时输出 bot 当前维度/位置/所在领地/附近领地，校验建造维度与可自定义领地，
        # 不符合预期（如 bot 被留在末地仓库）先告警，再由下方传送定位回主世界建造区。
        await self._check_build_environment()

        # 2026-08-14：保存建造点 home（/esethome dth），供寻路失败/淹死复活后
        # 用 /ehomes dth 传送回来。
        # ⚠️ 2026-08-15 决定性修复：dth 必须保存【确认到位】的平台站立点（y=68）。
        # 启动定位优先级（平台下是水、bot 可能掉水里爬不上平台）：
        #   1) return_fixed（用户配置的可靠家，如 /ehomes mapart 在平台上）→ 传送 → 严格验证
        #   2) 无 return_fixed → 寻路（+蹲搭）走回北缘站立点 → verify_height 确认
        # 到位后才保存 dth（否则 dth=主城/水里等错误位置，传送链全断）。
        # 2026-08-15 第二次修正：站立层固定用 config.map_art_stand_y_offset（默认 -1，
        # 平台顶=origin_y-1=68）——mapart 家 69 能站只是局部高点，自适应会被误导。
        try:
            fixed0 = (self._supply_cfg.get("return_fixed") or "/ehomes mapart").strip()
            placed0 = False
            if fixed0:
                self._activity("info", f"启动定位：传送回固定建造点（{fixed0}）")
                if await self._send_teleport(fixed0):
                    # 2026-08-16 P0-4：_verify_at_build_area 返回 Optional[str]（None=通过）
                    placed0 = (await self._verify_at_build_area()) is None
            gx0 = self.origin_x + self.region.x_start
            gz0 = self.origin_z + self.region.z_start - 1
            gy0 = self.origin_y + self._stand_y_offset  # 站立层（固定 offset）
            if not placed0:
                self._activity("info", f"定位到建造点北缘（{gx0},{gy0},{gz0}）")
                moved0 = await self._move_to(gx0, gy0, gz0, max_offset=2,
                                             label="initial position",
                                             timeout_ms=30000,
                                             allow_scaffold=True,  # 平台边缘/低处可蹲搭爬升
                                             verify_height=True)
                if not moved0:
                    self._activity("warn", "无法走到建造点北缘，尝试传送 dth 后重新定位")
                    await self._try_teleport_home("启动定位失败")
                    moved0 = await self._move_to(gx0, gy0, gz0, max_offset=2,
                                                 label="initial position retry",
                                                 timeout_ms=30000,
                                                 allow_scaffold=True,
                                                 verify_height=True)
                placed0 = moved0
            if not placed0:
                self._activity("warn", "仍无法定位到建造点，dth 将保存当前位置（可能不准）")
            else:
                self._activity("info", "已确认到位，保存 dth")
        except Exception as _e:
            logger.warning("[%s] Initial positioning failed: %s", self.bot_id, _e)
        try:
            r = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r, dict) and r.get("success") is False:
                logger.warning("[%s] save build home failed: %s", self.bot_id, r.get("error", "?"))
            else:
                await asyncio.sleep(1.0)
                self._activity("info", "已保存建造点位置（dth）")
        except Exception as e:
            logger.warning("[%s] save build home error: %s", self.bot_id, e)

        # ⚠️ 2026-08-16：真实世界对账移到【传送定位后】（bot 到建造区、world 从
        # 服务器重拉、chunk 加载）——大范围扫描才准确（在传送前扫描会因区域 chunk
        # 未加载读到 air 全"待定"）。扫描失败/部分未加载由运行中 _verify_block 兜底。
        await self._reconcile_start()

        try:
            for row_z in range(self.region.z_start, self.region.z_end + 1):
                if self._stopped:
                    break

                self.progress.current_row = row_z
                world_z = self.origin_z + row_z

                # 2026-08-15：每行开始前主动检查 bot 是否在建造区域附近——死亡复活到
                # 主城/传送点失效等场景，不等寻路失败才兜底，直接传送重置（位置验证
                # 已修复：get_player_state 的 location 字段现在能被正确解析）。
                try:
                    _p = await self._get_player_pos()
                    if _p and not self._near_build_area(_p[0], _p[1]):
                        self._activity("warn",
                                       f"bot 当前不在建造区域（{_p[0]:.0f},{_p[1]:.0f}），主动传送回建造点")
                        await self._try_teleport_home("bot 不在建造区域")
                except Exception:
                    pass

                # Position bot at north edge of current row
                moved = await self._move_to_row_edge(row_z)
                if not moved and not self._stopped:
                    # 2026-08-14：行边缘寻路失败（bot 淹死复活到远处/掉落/被卡）→
                    # 传送回建造点重试一次，避免任务直接失败
                    await self._try_teleport_home("行边缘寻路失败")
                    moved = await self._move_to_row_edge(row_z)
                if not moved or self._stopped:
                    break  # 移动失败（bot 离线/不可达）→ 终止本 bot 循环

                # Place blocks in this row, grouped by color
                await self._place_row(row_z, world_z)
                if self.progress.state == "offline":
                    break  # 行内移动/放置中断 → 终止循环

            if not self._stopped:
                # 2026-08-16 P0-5：完成前对账——以实际方块状态为准判定完成。
                # 弱确认（_genericPlace 发出但本地复核读到 air/读取失败）的坐标可能
                # 因 Via 不推送块更新而无法在运行中收敛 → 区域结束时先对账 DB 中
                # placed=True 且 verified=False 的行（读真实 world），未确认块不得
                # 静默计入 completed（防「0/16384 却 completed」类进度虚高）。
                ok_count, pending = await self._reconcile_region_final()
                if pending > 0:
                    # 给服务器同步/客户端刷新一次机会后复对账
                    await asyncio.sleep(3)
                    ok_count, pending = await self._reconcile_region_final()
                self.progress.blocks_placed = ok_count
                placed = ok_count
                total = self.progress.blocks_total
                if pending > 0:
                    # 仍存在未确认块（客户端数据旧）：不误报 completed，置 failed
                    # 提示重启 bot 后重新开始对账（权威对账依赖重启后 world 真实）。
                    self.progress.state = "failed"
                    self._activity("error",
                                   f"区域结束仍有 {pending} 块放置状态未确认（客户端数据旧），"
                                   f"已按 {placed}/{total} 记录，请重启 bot 后重新开始对账")
                    logger.warning("[%s] Region has %d unconfirmed blocks (%d/%d placed)",
                                   self.bot_id, pending, placed, total)
                elif total > 0 and placed < total:
                    # 2026-08-14 修复：循环跑完但方块未放完（补货失败/放置失败跳过）
                    # → 标记区域失败，不再误报 completed（此前 0/16384 也 completed）。
                    # 仍回调 on_done，由 coordinator 据 state 判定任务 failed。
                    self.progress.state = "failed"
                    self._activity("error", f"区域完成但未放完：{placed}/{total} 方块")
                    logger.warning("[%s] Region finished but INCOMPLETE: %d/%d blocks placed",
                                   self.bot_id, placed, total)
                else:
                    self.progress.state = "completed"
                    self._activity("info", f"区域完成：{placed} 方块")
                    logger.info("[%s] Region complete: %d blocks placed",
                                self.bot_id, placed)
                # P1-10：通知 coordinator（任务级完成判定 + DB status 更新）
                if self._on_done:
                    try:
                        self._on_done(self.bot_id)
                    except Exception as e:
                        logger.warning("[%s] on_done callback error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            # CancelledError 是 BaseException（Python 3.8+），不会被 except Exception 捕获
            self.progress.state = "offline"
        except Exception as e:
            # P1-9：原代码有第二个不可达的 `except Exception`（死代码），已合并
            self.progress.state = "offline"
            logger.error("[%s] Build loop error: %s", self.bot_id, e)
        finally:
            # 取消食物监控协程（2026-08-14 模块A）
            if self._food_task:
                self._food_task.cancel()
                self._food_task = None
            # P1-9：中断/异常时 flush 残留进度（防最后几行 DB 进度丢失；行内 offline 时
            # _place_row 未执行到行尾 flush）
            if self._db_updates:
                try:
                    await self._flush_db(self.progress.current_row)
                except Exception:
                    pass

    def _stand_y_for_row(self, row_z: int) -> int:
        """行首站立高度（2026-08-16 P0-2「边放边踩」蛇形模式）：

        - 第一行（row_z == z_start）：站平台顶北缘（bot 脚部 y = origin_y +
          map_art_stand_y_offset，默认 0 → 脚 y = origin_y = 平台 68 层顶面）。
        - 后续行：行首站上一行方块顶（脚 y = origin_y + 1）。

        ⚠️ 行内站立高度由 _place_row 统一按「上一格方块顶」= origin_y + 1 处理
        （bot 脚下恒为已放方块，永不踩空），本方法仅用于行首北缘定位。
        """
        if row_z > self.region.z_start:
            return self.origin_y + 1
        return self.origin_y + self._stand_y_offset

    async def _move_to_row_edge(self, row_z: int):
        """Move bot to the north edge of the given row (plan D: stand at row edge).

        Bot stands 1 block north of the row (z-1). Snake pattern: forward rows
        start at x_start (walking east), backward rows start at x_end (walking
        west) — so between rows the bot only moves 1 block (z+1, x unchanged).
        """
        xs = self._row_x_span()
        target_x = self.origin_x + (xs[0] if xs else self.region.x_start)
        target_z = self.origin_z + row_z - 1  # stand 1 block north
        # 2026-08-15「踩地图画建造」：站立高度随行变化——第一行站平台顶，
        # 后续行站上一行已放方块顶（bot 脚下始终有方块，不掉海里）。
        ok = await self._move_to(target_x, self._stand_y_for_row(row_z), target_z,
                                 max_offset=1, label=f"row {row_z} edge",
                                 timeout_ms=20000, verify_height=True)
        if not ok:
            self.progress.state = "offline"
        return ok

    async def _move_to(self, x: int, y: int, z: int, max_offset: int = 1,
                       label: str = "", timeout_ms: int | None = None,
                       ignore_y: bool = True, allow_scaffold: bool = True,
                       verify_height: bool = False) -> bool:
        """Move bot to within max_offset of (x, y, z) using pathfinder.

        2026-08-14：ignore_y 默认 True——地图画建造只关心 x/z 到位（bot 会落到实际
        地面），避免站立层悬空导致 3 维 GoalNear 永远无法满足而 timeout。
        allow_scaffold：补货/传送链路的内部寻路传 False——仓库内寻路失败时不应再
        触发蹲搭（蹲搭→背包无方块→又补货→又寻路，递归死循环），直接失败返回即可。
        2026-08-15 修复（verify_height）：GoalNearXZ（ignore_y）不校验 y——bot 掉下
        平台（如 y=57 vs 站立层 68）时 x/z 到位也"成功"，导致放置时 blockAt 全空气
        （chunk 未加载）→ 参考全失效。建造侧移动传 verify_height=True：到位后检查
        bot 实际 y 与目标 y 偏差，超差（>4）视为未真正到位（返回 False 触发传送兜底）。
        Returns True on arrival, False on failure (after retries).
        """
        await self._paused.wait()
        if self._stopped:
            return False
        self.progress.state = "moving"
        # 2026-08-15：寻路前确保目标站立点安全——站立点有水/岩浆时用背包方块填掉，
        # 避免 pathfinder 到达后 bot 站进水里（用户实测"寻路到水里面"）。填水失败
        # 不阻塞寻路（由后续溺水分级防护/传送兜底处理）。
        try:
            es = await self.mcp.ensure_standable(x, y, z)
            if isinstance(es, dict):
                if es.get("note"):
                    self._activity("debug", f"站立点检查：{es['note']}")
                elif es.get("success") is False and es.get("need_block"):
                    self._activity("warn", f"目标站立点需垫方块但背包无方块：{es.get('error', '?')}")
        except Exception:
            pass
        timeout = timeout_ms or self._move_timeout_ms
        self._last_move_fail_reason = ""  # 2026-08-16 P0-4：每次调用重置失败原因标签
        for attempt in range(self._move_retries + 1):
            if self._stopped:
                return False
            try:
                # 2026-08-15 P1：优先 baritone 移植寻路（A* + Moves，支持爬升/跳跃/
                # 下降，寻路天然校验站立面——平台边缘无方块不会走）。失败回退旧 pathfinder。
                # 2026-08-16 P1-2：双寻路 max_offset 语义统一（不再对 baritone 放宽到 2）——
                # 行内精确站立（max_offset=1）必须同格，宽放会导致 bot 停在错误格放置。
                result = await self.mcp.baritone_move(
                    x, y, z, max_offset=max_offset, timeout_ms=timeout)
                if not result.get("success"):
                    _bt_reason = str(result.get("reason") or "")
                    self._activity(
                        "debug",
                        f"baritone 寻路失败（{_bt_reason}），回退旧 pathfinder")
                    result = await self.mcp.move_to(
                        x, y, z, max_offset=max_offset, timeout_ms=timeout,
                        ignore_y=ignore_y,
                    )
                if result.get("success"):
                    if verify_height:
                        # 2026-08-16 P1-3：高度校验改为「y 偏差 + 脚下实体」双条件——
                        #   · y 偏差 ≤ map_art_verify_y_tol（默认 1.0）：容忍浮点/半砖/台阶抖动
                        #     （原硬编码 0.6 过严，bot 行进中微抖即误判未到位 → 频繁传送兜底）；
                        #   · 脚下必须实体（air/water/lava = 悬空/掉水，无论如何判未到位）——
                        #     这是防坠落的核心强条件，不受 y 容差放宽影响。
                        # 失败时写入 self._last_move_fail_reason 供 P0-4 兜底分流。
                        try:
                            st = await self.mcp.get_player_state()
                            d2 = st.get("data", st) if isinstance(st, dict) else {}
                            loc = d2.get("location") or {}
                            by = loc.get("y")
                            if isinstance(by, (int, float)):
                                dy = abs(float(by) - y)
                                # 脚下实体检查（强条件）
                                foot = await self.mcp.get_world_block_at(
                                    int(round(loc.get("x", x))), int(by) - 1,
                                    int(round(loc.get("z", z))))
                                foot_name = ((foot.get("name") or "air")
                                             .split("[")[0])
                                if foot_name in ("air", "water", "lava",
                                                 "flowing_water", "flowing_lava"):
                                    # 2026-08-16 修复：Via 不推送 blockUpdate，客户端
                                    # world 可能读到旧 air（服务器实际有方块；bot 重启后
                                    # forceLocalBlock 本地标记丢失）→ 不能只看本地方块。
                                    # 结合 on_ground（服务器真实物理状态）判断：
                                    #   on_ground=True → 客户端数据旧，容忍通过；
                                    #   on_ground=False → 真悬空/掉水，判未到位（防坠落）。
                                    on_ground = d2.get("is_on_ground")
                                    if on_ground is True:
                                        self._activity(
                                            "debug",
                                            f"脚下客户端读 {foot_name} 但 on_ground=true"
                                            f"（Via 数据旧），容忍通过")
                                    else:
                                        self._last_move_fail_reason = "fall"
                                        self._activity(
                                            "warn",
                                            f"移动到位但脚下是 {foot_name} 且未落地"
                                            f"（bot 悬空/掉水）——判定未到位")
                                        return False
                                if dy > self._verify_y_tol:
                                    self._last_move_fail_reason = "height"
                                    self._activity(
                                        "warn",
                                        f"移动到位但高度不符（目标y={y}，实际y={by:.1f}，"
                                        f"容差{self._verify_y_tol}）——bot 可能掉下/不在站立层")
                                    return False
                                if dy > 0.5:
                                    self._activity(
                                        "debug",
                                        f"到位高度偏差 {dy:.2f} 格但脚下实体，容忍通过")
                        except Exception:
                            pass
                    self._last_pos = (x, y, z)
                    return True
                _reason = str(result.get("reason") or "unknown")
                if not self._last_move_fail_reason:
                    self._last_move_fail_reason = _reason.split(":")[0].strip()
                logger.warning("[%s] move_to %s (attempt %d/%d) failed: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, result)
            except Exception as e:
                if not self._last_move_fail_reason:
                    self._last_move_fail_reason = "error"
                logger.warning("[%s] move_to %s (attempt %d/%d) error: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, e)
            await asyncio.sleep(0.5)

        # 2026-08-14：pathfinder 全部失败（落差/悬空不可达）→ 尝试自动蹲搭搭路
        # （用手头方块搭柱/搭桥前往）。仅寻路失败且允许蹲搭才触发（补货内寻路
        # allow_scaffold=False，避免"寻路→蹲搭→无方块→补货→再寻路"递归死循环）。
        if not allow_scaffold:
            self._activity("debug", f"寻路到 ({x},{y},{z}) 失败（补货链路内，不触发蹲搭）")
            return False
        await self._paused.wait()
        if self._stopped:
            return False
        self._activity("warn", f"寻路失败，尝试蹲搭前往 ({x},{y},{z})")
        # 2026-08-14：蹲搭前置条件——背包必须有可放置方块，没有先补货（从潜影盒拿）
        if not await self._ensure_scaffold_material():
            self._activity("warn", f"背包无方块且补货失败，无法蹲搭前往 ({x},{y},{z})")
            return False
        try:
            result = await self.mcp.scaffold_to(x, y, z, timeout_ms=30000)
            if result.get("success"):
                self._last_pos = (x, y, z)
                self._activity("info", f"蹲搭到达 ({x},{y},{z})")
                return True
            logger.warning("[%s] Scaffold to (%d,%d,%d) failed: %s",
                           self.bot_id, x, y, z, result.get("error", "?"))
            self._activity("warn", f"蹲搭前往 ({x},{y},{z}) 失败")
        except Exception as e:
            logger.warning("[%s] Scaffold to (%d,%d,%d) error: %s",
                           self.bot_id, x, y, z, e)
            self._activity("warn", f"蹲搭前往 ({x},{y},{z}) 异常")
        return False

    async def _place_row(self, row_z: int, world_z: int):
        """Place all blocks in a single row — 「边放边踩」蛇形逐格连续模式（2026-08-16 P0-2）。

        用户设计前提：bot 站在已建面上前搭一格、踩上前进，蛇形逐行、行末侧移掉头。
        站立序列（bot 脚下恒为已放方块 / 平台顶，永不踩空）：
          - 行首：站北缘（第一行=平台顶 origin_y+offset；后续行=上一行方块顶 origin_y+1）
          - 每格放置后：站立点更新为本格方块顶 (world_x, origin_y+1, world_z)，
            下一格直接从该顶上放置相邻格（参考面 AUTO 优先 bot 脚下/北面/平台）；
          - 蛇形转行：行末方块顶直接放下一行行首（零额外移动，bot 已在其上）。
        放置失败/材料缺失/站立格悬空 → 跳过该格并记入待补清单（不中断，行尾/区域判定兜底）。
        """
        await self._paused.wait()
        if self._stopped:
            return

        x_span = self._row_x_span()
        self.progress.state = "placing"

        # 行首站立高度（第一行=平台顶；后续行=上一行方块顶）
        first_stand_y = self._stand_y_for_row(row_z)
        stand: Optional[tuple[int, int, int]] = None   # 当前 bot 应在的站立点（世界坐标，含脚部 y）
        row_placed = 0
        row_failed = 0
        row_gap = 0
        row_audit: list[dict] = []  # P2-2 放置审计

        # 逐格顺序放置（颜色切换由 _ensure_item_in_hand 的 hotbar_map 缓存零成本处理）
        for x in x_span:
            await self._paused.wait()
            if self._stopped:
                return

            block_id = self.block_matrix.get((x, row_z))
            if not block_id or block_id == "minecraft:air":
                continue  # 空白格不放置（不消耗站立点）

            world_x = self.origin_x + x
            self._activity("debug", f"建造 ({world_x},{self.origin_y},{world_z}) ← {self._normalize_item_id(block_id)}")

            # ── 1. 确定并移动到位 ──
            if stand is None:
                # 行首：北缘（第一行=平台顶；后续行=上一行方块顶，bot 行末转行时已在附近）
                stand = (world_x, first_stand_y, world_z - 1)
            # 行内/转行：stand 已 = 上一格方块顶（放置成功后更新）
            _mv = await self._move_to_step(stand[0], stand[1], stand[2],
                                           label=f"stand({world_x},{world_z})")
            if _mv == "gap":
                # 2026-08-16：目标站立点脚下非实体（上一格未放成功/缺块）→ 跳过该格
                # 记待补，不回退 baritone（防掉水→传送死循环）。
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                row_gap += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "gap"})
                self._activity("warn",
                               f"站立点 ({stand[0]},{stand[1]},{stand[2]}) 缺块（上一格未放成功），"
                               f"跳过放置 ({world_x},{world_z})")
                continue
            if not _mv:
                # 站立点不可达（可能 bot 被传送/卡走）→ 传送兜底一次再试
                if await self._try_teleport_home("站立点移动失败"):
                    if not await self._move_to(stand[0], stand[1], stand[2], max_offset=1,
                                               label=f"stand retry({world_x},{world_z})",
                                               verify_height=True):
                        self.progress.state = "offline"
                        return
                else:
                    self.progress.state = "offline"
                    return

            # ── 2. 站立格前提校验（脚下实体，防踩空坠落）──
            if not await self._stand_solid(stand[0], stand[1], stand[2]):
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                self._activity("warn",
                               f"站立点 ({stand[0]},{stand[1]},{stand[2]}) 脚下非实体——"
                               f"悬空/上一格未放成功，跳过放置 ({world_x},{world_z})")
                row_gap += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "gap"})
                continue  # stand 不更新（bot 仍在原站立点，避免踩空）

            # ── 3. Verify：目标已正确则跳过（仍踩上本格方块顶）──
            if await self._verify_block(world_x, self.origin_y, world_z, block_id):
                self.progress.record_place()
                self.progress.last_completed_x = x
                self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                self._placed_coords.add((world_x, self.origin_y, world_z))  # 实时预览
                row_placed += 1
                stand = (world_x, self.origin_y + 1, world_z)  # 踩上（已放）
                self._activity("debug", f"({world_x},{world_z}) 已放置，跳过")
                continue

            # ── 4. 选物品（P0-3：失败显式跳过，杜绝手持错误物品放错）──
            if not await self._ensure_item_in_hand(block_id):
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                self._activity("warn",
                               f"无法获取材料 {self._normalize_item_id(block_id)}，跳过放置 ({world_x},{world_z})")
                row_failed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "no_material"})
                continue

            # ── 5. 放置（含放置后校验分层，P0-5）──
            if await self._place_with_retry(world_x, self.origin_y, world_z, block_id):
                self.progress.record_place()
                self.progress.last_completed_x = x
                self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                self._placed_coords.add((world_x, self.origin_y, world_z))  # 实时预览
                row_placed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "placed"})
                self._activity("debug", f"放置成功 ({world_x},{world_z}) {self._normalize_item_id(block_id)}")
                # 踩上：下一格站立点 = 本格方块顶（bot 脚下恒为已放方块）
                stand = (world_x, self.origin_y + 1, world_z)
            else:
                row_failed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "fail"})
                logger.warning("[%s] Place FAILED after %d retries at (%d,%d,%d) %s",
                               self.bot_id, self._place_retries,
                               world_x, self.origin_y, world_z, block_id)
                self._activity("warn",
                               f"放置失败 ({world_x},{world_z}) {self._normalize_item_id(block_id)}（重试{self._place_retries}次仍失败）")
                # stand 不更新：bot 仍在上格站立点，下一格继续（AUTO 参考面兜底平台/北面）

            # ── 6. 限速（防放错/防高频）──
            self._place_sample_count += 1
            if self._place_sample_count % 10 == 0:
                await self._update_place_interval()
            await asyncio.sleep(self._place_interval)

        # ── 行尾：flush 进度 + 行尾复核（P0-5）+ 审计日志（P2-2）──
        await self._flush_db(row_z)
        await self._reconcile_row(row_z)
        if row_audit:
            self._activity("info",
                           f"第 {row_z} 行放置统计：成功 {row_placed} / 失败 {row_failed} / 悬空跳过 {row_gap}"
                           f"（放置坐标 {[a['x'] for a in row_audit if a['result']=='placed'][:5]}{'…' if row_placed > 5 else ''}）")
        # 2026-08-14 终端：行完成埋点（低频，每行一条）
        if row_z == self.region.z_start or row_z % 10 == 0 or row_z == self.region.z_end:
            self._activity("info", f"第 {row_z} 行完成")

    async def _stand_solid(self, x: int, y: int, z: int) -> bool:
        """站立格前提校验（P0-2）：bot 站立点 (x, y, z) 脚下 (x, y-1, z) 必须是实体方块。

        非实体（air/water/lava）→ 返回 False（悬空/掉水），调用方跳过放置并记待补，
        不触发传送兜底（区别于移动到位后的脚下检查——那是防坠落强条件）。

        ⚠️ 2026-08-16 修复：Via 不推送 blockUpdate，客户端 world 读到旧 air（服务器
        实际有方块；bot 重启后 forceLocalBlock 本地标记丢失）→ 单看本地方块会把
        bot 真站在方块上误判为"脚下非实体"→ 每格都跳过（卡死，placed 停滞）。
        结合 on_ground（服务器真实物理状态）：on_ground=true → 数据旧容忍；
        false → 真悬空/掉水才判不满足（保持防坠落）。
        """
        try:
            foot = await self.mcp.get_world_block_at(int(x), int(y) - 1, int(z))
            name = ((foot.get("name") or "air").split("[")[0])
            if name not in ("air", "water", "lava", "flowing_water", "flowing_lava"):
                return True
            # 客户端读 air/水：结合服务器物理状态判断
            try:
                _st = await self.mcp.get_player_state()
                _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                if _d2.get("is_on_ground") is True:
                    return True  # Via 数据旧，bot 实际站在方块上
            except Exception:
                pass
            return False
        except Exception:
            return False  # 读取失败按不满足处理（安全侧）

    async def _move_to_step(self, x: int, y: int, z: int, label: str = "") -> bool:
        """轻量行内移动（P0-2/P0-1）：距离 ≤3 用 walk_toward 控制键直走（带护栏，
        Node 侧校验目标格脚下实体 + 此处校验 y 偏差，非实体/高度不符拒绝直走防踩空）；
        失败/超距离回退 _move_to。

        返回值：
          True = 到位；False = 失败（调用方传送兜底/重试）；
          "gap" = 目标站立点脚下非实体（上一格未放成功/缺块）——直接跳过该格，
                  不回退 baritone（回退只会反复掉水→传送死循环→区域 failed）。
        """
        try:
            p = await self._get_player_pos_full()
            if p:
                d = max(abs(p[0] - x), abs(p[2] - z))
                if d <= 3.0:
                    try:
                        r = await self.mcp.walk_toward(x=x, z=z, timeout_ms=8000)
                        if r.get("success"):
                            # walk_toward 只移动 x/z：校验 bot 实际高度与目标站立层
                            # 一致（防 bot 掉下平台后 x/z 到位但高度错误继续放置）
                            p2 = await self._get_player_pos_full()
                            if p2 and abs(float(p2[2]) - y) > 1.5:
                                self._last_move_fail_reason = "height"
                                self._activity("debug",
                                               f"直走到位但高度不符（目标y={y}，实际y={p2[2]:.1f}），回退寻路")
                                return await self._move_to(x, y, z, max_offset=1,
                                                           label=label or f"step({x},{z})",
                                                           verify_height=True)
                            return True
                        # 2026-08-16：walk_toward 失败——目标是【脚下非实体】（缺块/悬空）
                        # → 直接跳过该格（gap），不回退 baritone（防掉水死循环）。
                        _why = str(r.get("reason") or "")
                        if _why in ("unsafe_foot", "foot_check_error"):
                            self._last_move_fail_reason = "gap"
                            self._activity("debug",
                                           f"walk_toward 目标脚下非实体（{_why}）→ 跳过该格 ({x},{z})")
                            return "gap"
                    except Exception:
                        pass
            return await self._move_to(x, y, z, max_offset=1,
                                       label=label or f"step({x},{z})",
                                       verify_height=True)
        except Exception:
            return await self._move_to(x, y, z, max_offset=1,
                                       label=label or f"step({x},{z})",
                                       verify_height=True)

    def _is_near(self, x: int, y: int, z: int, threshold: float = 2.0) -> bool:
        """Check whether the bot's last known position is within `threshold` blocks."""
        if self._last_pos is None:
            return False
        lx, ly, lz = self._last_pos
        return abs(lx - x) <= threshold and abs(ly - y) <= threshold and abs(lz - z) <= threshold

    async def _update_place_interval(self) -> None:
        """RTT-adaptive rate limiting: interval = max(base, RTT*1.5), capped at 2s.

        Mirrors litematica-printer's RttReplayController: never place faster
        than one round-trip, preventing mis-placed/ghost blocks on laggy servers.
        """
        try:
            state = await self.mcp.get_player_state()
            ping_ms = state.get("ping") or 0
            if ping_ms and ping_ms > 0:
                rtt_interval = ping_ms / 1000.0 * 1.5
                if rtt_interval > self._place_interval:
                    self._place_interval = min(rtt_interval, 2.0)  # 上限 2s
                    logger.info("[%s] RTT adaptive interval → %.2fs (ping=%dms)",
                                self.bot_id, self._place_interval, ping_ms)
        except Exception:
            pass

    async def _flush_db(self, row_z: int) -> None:
        """Batch-persist placed/verified blocks to DB (breakpoint resume).

        World state is the source of truth for resume (each block is
        re-verified by _verify_block on next run); the DB is used for
        progress stats (placed_blocks / UI) and fast completion check.
        """
        if not self._db_updates:
            return
        updates = self._db_updates
        self._db_updates = []
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtBlockState, MapArtTask
            from sqlalchemy import func
            db = get_session_factory()()
            try:
                now = datetime.now(timezone.utc)
                for x, y, z, block_id in updates:
                    row = db.query(MapArtBlockState).filter(
                        MapArtBlockState.task_id == self.task_id,
                        MapArtBlockState.x == x,
                        MapArtBlockState.y == y,
                        MapArtBlockState.z == z,
                    ).first()
                    if row is None:
                        continue
                    # 2026-08-16 P0-5：placed=True + verified=False（弱确认）。
                    # verified 由行尾复核（_reconcile_row）/启动对账收敛为 True；
                    # actual_block 先记录期望值，对账发现放错/缺失时重置。
                    row.placed = True
                    row.verified = False
                    row.actual_block = block_id.split("[")[0]
                    row.placed_by_bot = self.bot_id
                    row.placed_at = now
                    row.verified_at = now
                # 2026-08-16 P0-5（B5）：聚合进度同步（索引 COUNT，量级毫秒）——
                # 使 GET /tasks/{id} 的 progress.placed_blocks 与实时推送一致。
                try:
                    task = db.query(MapArtTask).filter(
                        MapArtTask.task_id == self.task_id).first()
                    if task is not None:
                        task.placed_blocks = db.query(func.count()).select_from(
                            MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.placed.is_(True),
                        ).scalar() or 0
                except Exception as _agg_err:
                    logger.warning("[%s] Aggregate progress update failed: %s",
                                   self.bot_id, _agg_err)
                db.commit()
            finally:
                db.close()
            self._db_flushed_rows += 1
            if self._db_flushed_rows <= 5 or self._db_flushed_rows % 10 == 0:
                logger.info("[%s] Progress persisted: row %d (%d blocks)",
                            self.bot_id, row_z, len(updates))
        except Exception as e:
            logger.warning("[%s] DB flush failed (row %d): %s", self.bot_id, row_z, e)
            # 失败不阻断建造：世界状态仍会被 _verify_block 兜底

    async def _reconcile_row(self, row_z: int) -> None:
        """行尾复核（2026-08-16 P0-5）：对本行弱确认（_pending_confirm）的坐标
        重读真实 world，收敛 verified 状态，防进度虚高。

        - 读到期望方块 → verified=True（强确认）
        - 读到明确非期望、非 air 方块 → placed=False 重置（放错/被破坏）
        - 读到 air/读取失败 → 保持 placed=True + verified=False（客户端数据旧，
          待启动/完成对账收敛——权威对账依赖 bot 重启后 world 真实，见方案限制）
        """
        if not self._pending_confirm:
            return
        row_pending = [pc for pc in self._pending_confirm
                       if pc[2] == self.origin_z + row_z]
        if not row_pending:
            return
        ok_count = 0
        reset_count = 0
        stale_count = 0
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtBlockState
            db = get_session_factory()()
            try:
                for x, y, z, block_id in row_pending:
                    try:
                        v = await self.mcp.get_world_block_at(x, y, z)
                        actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                    except Exception:
                        actual = "air"  # 读取失败按旧数据处理
                    if actual == self._normalize_item_id(block_id):
                        ok_count += 1
                        row = db.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == x, MapArtBlockState.y == y,
                            MapArtBlockState.z == z,
                        ).first()
                        if row:
                            row.verified = True
                            row.verified_at = datetime.now(timezone.utc)
                        self._verified_set.add((x, y, z))
                    elif actual in ("air", ""):
                        stale_count += 1  # 客户端旧数据，保持弱确认（不重置）
                    else:
                        reset_count += 1
                        row = db.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == x, MapArtBlockState.y == y,
                            MapArtBlockState.z == z,
                        ).first()
                        if row:
                            row.placed = False
                            row.verified = False
                            row.actual_block = ""
                db.commit()
            finally:
                db.close()
            self._pending_confirm = [pc for pc in self._pending_confirm
                                     if pc not in row_pending]
            self._reconcile_stats["row"][row_z] = {
                "ok": ok_count, "reset": reset_count, "stale": stale_count}
            if ok_count or reset_count:
                self._activity(
                    "debug",
                    f"行 {row_z} 复核：确认 {ok_count} / 重置 {reset_count} / 待定 {stale_count}")
        except Exception as e:
            logger.warning("[%s] Row reconcile failed (row %d): %s", self.bot_id, row_z, e)

    async def _reconcile_start(self) -> None:
        """启动对账（2026-08-16 P0-5）：任务启动（含重新开始）时对 DB 已 placed
        坐标分批真实复核（bot 重启后本地 world 从服务器重拉，此时为权威状态）。

        - 一致 → verified=True（保留）
        - air/读取失败 → 保持 placed（客户端可能旧，运行中 _verify_block 兜底）
        - 明确其它方块 → placed=False 重置（被破坏/放错）
        取代「信任 DB 计数直接复用」（原 _restore_progress 的信任逻辑），
        防止 DB 与世界的进度虚高偏差被静默带入本轮。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtBlockState
            db = get_session_factory()()
            rows = []
            try:
                rows = db.query(
                    MapArtBlockState.x, MapArtBlockState.y, MapArtBlockState.z,
                    MapArtBlockState.expected_block,
                ).filter(
                    MapArtBlockState.task_id == self.task_id,
                    MapArtBlockState.placed.is_(True),
                    MapArtBlockState.x >= self.origin_x + self.region.x_start,
                    MapArtBlockState.x <= self.origin_x + self.region.x_end,
                    MapArtBlockState.z >= self.origin_z + self.region.z_start,
                    MapArtBlockState.z <= self.origin_z + self.region.z_end,
                ).all()
            finally:
                db.close()
            if not rows:
                return
            ok_count = 0
            reset_count = 0
            stale_count = 0
            self._activity("info", f"启动对账：DB 已置位 {len(rows)} 块，大范围扫描匹配投影…")
            db2 = get_session_factory()()
            try:
                # ⚠️ 2026-08-16：优先用【大范围平面扫描】（一次 WS 往返读取区域
                # 指定层所有方块 {x,z,block}）→ 内存与 DB 批量比对，替代 16384 次
                # 逐格 get_world_block_at（重启后 bot world 从服务器重拉 = 权威）。
                actual_map: dict[tuple[int, int], str] = {}
                try:
                    _snap = await self.mcp.scan_region_blocks(
                        x_start=self.origin_x + self.region.x_start,
                        x_end=self.origin_x + self.region.x_end,
                        z_start=self.origin_z + self.region.z_start,
                        z_end=self.origin_z + self.region.z_end,
                        y=self.origin_y,
                    )
                    _blks = (_snap.get("data", _snap)).get("blocks", []) if isinstance(_snap, dict) else []
                    for _b in _blks:
                        actual_map[(_b.get("x"), _b.get("z"))] = self._normalize_item_id(
                            (_b.get("block") or "air").split("[")[0])
                    self._activity("debug", f"大范围扫描完成：{len(actual_map)} 格")
                except Exception as _scan_err:
                    logger.warning("[%s] Region scan failed (%s)，回退逐格对账", self.bot_id, _scan_err)
                    actual_map = {}
                for rx, ry, rz, expected in rows:
                    if actual_map:
                        actual = actual_map.get((rx, rz), "air")
                    else:
                        try:
                            v = await self.mcp.get_world_block_at(rx, ry, rz)
                            actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                        except Exception:
                            actual = "air"
                    if actual == self._normalize_item_id(expected):
                        ok_count += 1
                        row = db2.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == rx,
                            MapArtBlockState.y == ry,
                            MapArtBlockState.z == rz,
                        ).first()
                        if row:
                            row.verified = True
                            row.verified_at = datetime.now(timezone.utc)
                        self._verified_set.add((rx, ry, rz))
                    elif actual in ("air", ""):
                        stale_count += 1  # 客户端旧数据，保持弱确认
                    else:
                        reset_count += 1
                        row = db2.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == rx,
                            MapArtBlockState.y == ry,
                            MapArtBlockState.z == rz,
                        ).first()
                        if row:
                            row.placed = False
                            row.verified = False
                            row.actual_block = ""
                db2.commit()
            finally:
                db2.close()
            self.progress.blocks_placed = ok_count  # 以世界复核一致的计数为准
            self._reconcile_stats["start"] = {
                "total": len(rows), "ok": ok_count, "reset": reset_count, "stale": stale_count}
            self._activity(
                "info",
                f"启动对账完成：{ok_count} 一致 / {reset_count} 重置 / {stale_count} 待定"
                f"（共 {len(rows)} 块 DB 已置位）")
        except Exception as e:
            logger.warning("[%s] Start reconcile failed: %s", self.bot_id, e)

    async def _restore_progress(self) -> None:
        """Restore previously persisted progress from DB (breakpoint resume).

        2026-08-16 P0-5：真实世界对账（_reconcile_start）已移到 run() 传送定位
        之后调用（bot 到建造区、world 从服务器重拉后大范围扫描才准确——
        在传送前对账会因区域 chunk 未加载读到 air 全"待定"）。此处仅保留进度
        计数兜底（对账失败时仍以 DB 计数启动，运行中 _verify_block 逐格纠偏）。
        """
        # 对账已移至 run() 传送定位后，这里不再调用 _reconcile_start
        pass

    async def _reconcile_region_final(self) -> tuple[int, int]:
        """区域完成前对账（2026-08-16 P0-5）：对 DB 中本区域 placed=True 的行复核。

        返回 (已确认数, 待确认数)：
          - verified=True / 复核读到期望方块 → 已确认（ok）
          - 复核读到 air/读取失败 → 待确认（pending，客户端数据旧，不重置、不计入完成）
          - 复核读到明确的其它方块 → placed=False 重置（放错/被破坏）
        同时同步 map_art_tasks.placed_blocks 聚合计数（B5）。

        异常时返回 (0, 0)：调用方 placed=0 < total → 判 failed（fail-safe，不误报完成）。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import (
                MapArtBlockState, MapArtTask,
            )
            from sqlalchemy import func
            db = get_session_factory()()
            rows = []
            try:
                rows = db.query(
                    MapArtBlockState.x, MapArtBlockState.y, MapArtBlockState.z,
                    MapArtBlockState.expected_block, MapArtBlockState.verified,
                ).filter(
                    MapArtBlockState.task_id == self.task_id,
                    MapArtBlockState.placed.is_(True),
                    MapArtBlockState.x >= self.origin_x + self.region.x_start,
                    MapArtBlockState.x <= self.origin_x + self.region.x_end,
                    MapArtBlockState.z >= self.origin_z + self.region.z_start,
                    MapArtBlockState.z <= self.origin_z + self.region.z_end,
                ).all()
            finally:
                db.close()
            ok_count = 0
            pending_count = 0
            reset_count = 0
            db2 = get_session_factory()()
            try:
                for rx, ry, rz, expected, verified in rows:
                    if verified:
                        ok_count += 1
                        continue
                    try:
                        v = await self.mcp.get_world_block_at(rx, ry, rz)
                        actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                    except Exception:
                        actual = "air"
                    if actual == self._normalize_item_id(expected):
                        ok_count += 1
                        row = db2.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == rx,
                            MapArtBlockState.y == ry,
                            MapArtBlockState.z == rz,
                        ).first()
                        if row:
                            row.verified = True
                            row.verified_at = datetime.now(timezone.utc)
                        self._verified_set.add((rx, ry, rz))
                    elif actual in ("air", ""):
                        pending_count += 1  # 客户端数据旧，未确认（不重置）
                    else:
                        reset_count += 1
                        row = db2.query(MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.x == rx,
                            MapArtBlockState.y == ry,
                            MapArtBlockState.z == rz,
                        ).first()
                        if row:
                            row.placed = False
                            row.verified = False
                            row.actual_block = ""
                db2.commit()
                # 聚合进度同步（全任务 placed 计数）
                try:
                    task = db2.query(MapArtTask).filter(
                        MapArtTask.task_id == self.task_id).first()
                    if task is not None:
                        task.placed_blocks = db2.query(func.count()).select_from(
                            MapArtBlockState).filter(
                            MapArtBlockState.task_id == self.task_id,
                            MapArtBlockState.placed.is_(True),
                        ).scalar() or 0
                    db2.commit()
                except Exception as _agg_err:
                    logger.warning("[%s] Final reconcile aggregate failed: %s",
                                   self.bot_id, _agg_err)
            finally:
                db2.close()
            self._reconcile_stats["done"] = {
                "ok": ok_count, "pending": pending_count, "reset": reset_count}
            if reset_count or pending_count:
                self._activity(
                    "info",
                    f"完成前对账：确认 {ok_count} / 待确认 {pending_count} / 重置 {reset_count}")
            return ok_count, pending_count
        except Exception as e:
            logger.warning("[%s] Final reconcile failed: %s", self.bot_id, e)
            return 0, 0  # fail-safe：按未完成处理

    async def _verify_block(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Compare world block at (x,y,z) with the expected block_id (name only).

        P2-9：已验证正确的坐标缓存到 _verified_set——同一 run 内不重复
        get_world_block_at（WS 往返）；方块变化由放置后重放兜底。
        ⚠️ 2026-08-15 P3 修正：不信任缓存直接跳过——方块可能被破坏（打掉），
        必须每次真实读取世界比对，发现"已放但被打掉"→返回 False →重放。
        （16384 格 × 本地 WS 读取开销可接受，换来环境感知正确性）
        """
        key = (x, y, z)
        try:
            result = await self.mcp.get_world_block_at(x, y, z)
            # 2026-08-16 修复：get_world_block_at 返回 name 无前缀（如 black_concrete），
            # 而 block_id 带 minecraft: 前缀 → 直接 == 永远不相等 → 放置成功却被判
            # WRONG 重试（本轮实测 "Place confirmed WRONG: got black_concrete want
            # minecraft:black_concrete" 的根因）。统一 _normalize_item_id 比较。
            actual = self._normalize_item_id((result.get("name") or "air").split("[")[0])
            expected = self._normalize_item_id(block_id)
            if actual == expected:
                self._verified_set.add(key)
                return True
            if key in self._verified_set:
                # 2026-08-15 P3：缓存说已放但世界实际不对（被破坏）→ 清除缓存并重放
                self._verified_set.discard(key)
            return False
        except Exception:
            return False

    async def _place_with_retry(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Place a block with retries; returns True if eventually placed (弱确认成功).

        2026-08-16 P0-5 放置后校验分层（防进度虚高）：
          - 强确认：放置后 world 读到期望方块（服务器真实或本地 forceLocalBlock 同步，
            两者在重启对账时收敛）→ verified；
          - 放错：world 读到明确的非期望、非 air 方块 → 重试（attempt 内）；
          - 弱确认：world 读到 air/读取失败（Via 不推送块更新，客户端数据旧）→
            信任 place_block 发出（服务器已接受），坐标记入 _pending_confirm，
            由行尾复核（_reconcile_row）/启动对账收敛 verified，防止进度虚高。
        """
        # 2026-08-16 修复：统一 _normalize_item_id 比较（get_world_block_at 返回
        # name 无前缀，block_id 带 minecraft: 前缀，直接 == 永远不相等 → 放置成功
        # 却被判 WRONG 重试，进度不记录、方块漏计）。
        expected = self._normalize_item_id(block_id)
        for attempt in range(self._place_retries):
            await self._paused.wait()
            if self._stopped:
                return False
            try:
                # face="AUTO"：Node 侧自动选面（对齐 printer getValidSide），
                # 优先北面参考（bot 站行北缘），其次下方/南面/行内/上方——参考
                # 方块缺失时自动兜底，避免固定 face="SOUTH" 导致放置失败。
                result = await self.mcp.place_block(
                    x=x, y=y, z=z,
                    face="AUTO",
                    hand="MAIN_HAND",
                    look_at_block=False,
                    trust_down=True,  # 2026-08-15 P3：地图画目标下方是平台，
                    # 客户端 blockAt 可能读旧 air → 信任服务器直接以目标下方为参考放置
                )
                if result.get("success"):
                    # P0-3 防线：放置返回的手持物品必须与期望一致（防止放错方块）
                    pw = result.get("placed_with") or ""
                    if pw and self._normalize_item_id(pw) != self._normalize_item_id(expected):
                        logger.warning(
                            "[%s] Place used WRONG item at (%d,%d,%d): held %s want %s — abort",
                            self.bot_id, x, y, z, pw, expected)
                        return False  # 已发出错误放置，由上层跳过/待补（对账会修正）
                    # P0-5 放置后确认（分层）
                    try:
                        v = await self.mcp.get_world_block_at(x, y, z)
                        actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                        if actual == expected:
                            # 强确认（服务器真实或本地已同步）
                            self._verified_set.add((x, y, z))
                            return True
                        if actual in ("air", ""):
                            # 弱确认：客户端数据旧（服务器已放置但本地未同步）→ 记入待确认
                            self._pending_confirm.append((x, y, z, block_id))
                            return True
                        logger.warning(
                            "[%s] Place confirmed WRONG at (%d,%d,%d): got %s want %s — retry",
                            self.bot_id, x, y, z, actual, expected)
                    except Exception:
                        # 读取失败（chunk 未加载等）→ 弱确认（避免死循环）
                        self._pending_confirm.append((x, y, z, block_id))
                        return True
                logger.warning("[%s] Place failed at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, result)
            except Exception as e:
                logger.warning("[%s] Place error at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, e)
            await asyncio.sleep(0.5)
        return False

    async def _ensure_item_in_hand(self, block_id: str) -> bool:
        """Switch hotbar to the required block type, restock if empty.

        ⚠️ 必须检查 select_hotbar_item 返回值（success:false 不会抛异常——
        WS handler 返回错误 dict，而非 reject）。原实现用 except 捕获失败
        永远不触发补货（P0 修复）。
        2026-08-16 P0-3：返回 bool —— True=手持已就绪；False=无法获取该材料
        （补货也失败/装备失败），调用方跳过放置，杜绝手持错误物品放错方块。
        """
        # 2026-08-14 模块B：快捷栏动态识别 —— 先查 _hotbar_map 缓存，命中则直接切槽（零搜索），
        # 未命中才走 select_hotbar_item 全背包搜索，成功后回填缓存。
        if self._current_item == block_id:
            # ⚠️ 2026-08-16 修复：_current_item 缓存可能失效（手持被服务器/补货/
            # 掉落等操作改变）——直接返回 True 会导致手持错误物品放置（实测
            # "Place used WRONG item: held light_gray_concrete want black_concrete"）。
            # 缓存命中时用 get_player_state.held_item（服务器真实手持）快速校验，
            # 不一致 → 缓存失效 → 走下方 select 流程。
            try:
                _st = await self.mcp.get_player_state()
                _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                _held = _d2.get("held_item") or ""
                if not _held:
                    # 手持空（切换中/物品消耗完）→ 不信任缓存，走下方 select 流程
                    # （否则 place 时 No item in hand 连续失败）
                    self._current_item = None
                elif self._normalize_item_id(_held) != self._normalize_item_id(block_id):
                    self._activity("debug",
                                   f"手持缓存失效（实际 {_held}，期望 {block_id}）→ 重新选择")
                    self._current_item = None
                else:
                    return True
            except Exception:
                return True  # 读取失败容忍（保持原行为）
        clean_id = block_id.split("[")[0] if "[" in block_id else block_id

        # 1) 查缓存：_hotbar_map 里有 → 直接 set_quick_bar_slot（零成本）
        # 2026-08-14 修复：缓存存归一化 ID，比较也归一化（原带前缀 vs 无前缀永不命中）
        norm_id = self._normalize_item_id(clean_id)
        for slot, cached_id in self._hotbar_map.items():
            if cached_id == norm_id:
                try:
                    r = await self.mcp.set_quick_bar_slot(slot)
                    if r.get("success"):
                        # ⚠️ 2026-08-16：Via 下 set_quick_bar_slot 后客户端 heldItem
                        # 可能延迟更新，且 hotbar_map 槽位内容可能已过期（如补货/背包
                        # 变化后旧槽位变成 cyan）→ 等 0.5s 后验证实际手持，不符则
                        # 缓存失效，走下方 select 全背包搜索（防手持错误物品放置）。
                        await asyncio.sleep(0.5)
                        try:
                            _st2 = await self.mcp.get_player_state()
                            _d2b = _st2.get("data", _st2) if isinstance(_st2, dict) else {}
                            _held2 = _d2b.get("held_item") or ""
                            if not _held2 or self._normalize_item_id(_held2) != norm_id:
                                self._activity("debug",
                                               f"hotbar_map 槽位 {slot} 内容过期（实际 {_held2 or '空'}，期望 {clean_id}）→ 缓存失效")
                                del self._hotbar_map[slot]
                                break
                        except Exception:
                            pass  # 读取失败不拦截
                        self._current_item = block_id
                        self._current_slot = slot
                        return True
                except Exception:
                    pass
                # 缓存失效（物品已用完/被移动）→ 从缓存清除，走搜索
                del self._hotbar_map[slot]
                break

        # 2) 缓存未命中 → 全背包搜索
        if await self._try_select_item(clean_id, block_id):
            return True

        # select 失败 → 检查背包存量
        count = await self._check_inventory_level(block_id)
        if count > 0:
            # 有物品但装备失败（如背包满/equip 失败）→ 重试一次
            logger.warning("[%s] Equip %s failed but %d in inventory, retrying...",
                           self.bot_id, clean_id, count)
            if await self._try_select_item(clean_id, block_id):
                return True
            logger.warning("[%s] Equip %s retry failed, skipping this color",
                           self.bot_id, clean_id)
            return False

        # 背包中没有该物品 → 补货（2026-08-14：全量补齐所有缺的材料再返回，
        # 避免"缺A补A、回来又缺B再传送"的反复奔波）
        logger.info("[%s] %s 用完了，开始补货...", self.bot_id, clean_id)
        self._activity("warn", f"缺少 {clean_id}，开始补货")
        if await self._do_full_restock(clean_id):
            # 补货后刷新 hotbar_map 并重试
            await self._refresh_hotbar_map()
            if await self._try_select_item(clean_id, block_id):
                return True
        logger.warning("[%s] 补货后仍无法装备 %s，跳过该材料", self.bot_id, clean_id)
        return False

    async def _try_select_item(self, clean_id: str, block_id: str) -> bool:
        """Select/equip item; returns True only if the hand now holds it."""
        try:
            result = await self.mcp.select_hotbar_item(clean_id)
            if result.get("success"):
                # ⚠️ 2026-08-16：Via 下 select 可能"假成功"（服务器切换后客户端
                # heldItem 未同步/equip 未生效）——成功后用 get_player_state.held_item
                # 验证实际手持，不符则视为失败（防手持错误物品放置 → WRONG abort）。
                try:
                    _st = await self.mcp.get_player_state()
                    _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                    _held = _d2.get("held_item") or ""
                    if not _held or self._normalize_item_id(_held) != self._normalize_item_id(clean_id):
                        logger.warning("[%s] select %s 后手持 %s（切换未生效）→ 视为失败",
                                       self.bot_id, clean_id, _held or "空")
                        return False
                except Exception:
                    pass  # 读取失败不拦截（保持原行为）
                self._current_item = block_id
                # 2026-08-14 模块B：记录实际槽位到 hotbar_map（存归一化 ID）
                slot = result.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    self._hotbar_map[slot] = self._normalize_item_id(clean_id)
                    self._current_slot = slot
                return True
            logger.warning("[%s] select_hotbar_item %s failed: %s",
                           self.bot_id, clean_id, result.get("error", "?"))
        except Exception as e:
            logger.warning("[%s] select_hotbar_item %s error: %s",
                           self.bot_id, clean_id, e)
        return False

    async def _refresh_hotbar_map(self) -> None:
        """从 get_inventory_snapshot 重建快捷栏映射（补货后/物品移动后）。

        2026-08-14 修复：snapshot type 无前缀，统一 _normalize_item_id 存储，
        否则 _ensure_item_in_hand 用带前缀 clean_id 查缓存永远不命中（缓存失效）。
        """
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            self._hotbar_map.clear()
            for s in items:
                slot = s.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    item_id = self._normalize_item_id(s.get("type", ""))
                    if item_id:
                        self._hotbar_map[slot] = item_id
        except Exception:
            pass  # 静默失败，不影响建造

    def _activity(self, level: str, message: str) -> None:
        """记录活动日志（2026-08-14 终端：实时反馈 bot 在做什么）。

        level: debug | info | warn | error。debug 为详细模式专属（所有操作细节），
        简略模式只显示 info/warn/error。经 on_activity 回调推给 coordinator 汇聚后
        通过 Socket.IO 广播到前端实时日志终端。同时写 loguru（服务器 /tmp/vmtools.log
        可见，便于诊断埋点是否触发）。
        """
        try:
            if level == "error":
                logger.warning("[%s] [ACT:%s] %s", self.bot_id, level, message)
            elif level == "debug":
                logger.debug("[%s] [ACT:%s] %s", self.bot_id, level, message)
            else:
                logger.info("[%s] [ACT:%s] %s", self.bot_id, level, message)
        except Exception:
            pass
        try:
            if self._on_activity:
                self._on_activity(self.bot_id, self.bot_name, level, message)
        except Exception:
            pass

    async def _get_player_pos(self) -> Optional[tuple[float, float]]:
        """获取 bot 当前 X/Z 坐标（实时优先，缓存兜底）。

        2026-08-15 第二批修复（D1/D14）：last_status 是 status 事件每 5s 推送的缓存，
        传送后/刚启动时可能是旧位置——现改为「实时 get_player_state 优先」，
        last_status 仅作为实时查询失败时的兜底（避免用过期数据误判"不在建造区域"）。
        """
        p = await self._get_player_pos_full()
        return (p[0], p[1]) if p else None

    async def _get_player_pos_full(self) -> Optional[tuple[float, float, float]]:
        """获取 bot 当前位置 (x, z, y)（实时优先，缓存兜底）；获取不到返回 None。

        y 供 _near_build_area 高度校验（D2）；实时 get_player_state 返回 location 字段。
        """
        def _extract3(st: dict) -> Optional[tuple[float, float, float]]:
            if not isinstance(st, dict):
                return None
            pos = (st.get("position") or st.get("pos")
                   or st.get("location")  # 2026-08-15：get_player_state 返回的是 location 字段
                   or st.get("player") or st.get("entity") or {})
            if isinstance(pos, dict):
                x, y, z = pos.get("x"), pos.get("y"), pos.get("z")
                if all(isinstance(v, (int, float)) for v in (x, y, z)):
                    return (float(x), float(z), float(y))
            elif isinstance(pos, (list, tuple)) and len(pos) >= 3:
                if all(isinstance(v, (int, float)) for v in pos[:3]):
                    return (float(pos[0]), float(pos[2]), float(pos[1]))
            return None
        # 1) 实时查询优先（~几百 ms，避免用过期的 5s 推送缓存）
        try:
            r = await self.mcp.get_player_state()
            data = r.get("data", r) if isinstance(r, dict) else {}
            if isinstance(data, dict):
                p = _extract3(data)
                if p:
                    return p
                # 部分实现 position 在 data 的 status 子对象里
                p = _extract3(data.get("status") or data.get("bot_status") or {})
                if p:
                    return p
        except Exception:
            pass
        # 2) 缓存兜底（实时查询失败时用 last_status，可能略旧但总比没有强）
        try:
            p = _extract3(getattr(self.mcp, "last_status", None) or {})
            if p:
                return p
        except Exception:
            pass
        return None

    def _near_build_area(self, x: float, z: float, y: Optional[float] = None) -> bool:
        """判断 (x,z)（可选 y）是否在建造区域附近（矩形区域，X/Z 半宽半高各自外扩自适应余量）。

        2026-08-14 优化（为大地图画准备）：
        - 区域边界首次调用时计算并缓存（O(N) 一次 → 之后 O(1)）——原实现每次
          全量遍历 block_matrix，128²=1.6万 尚可，512²/1024²=26万~100万+ 会卡。
        - 矩形判断（X、Z 分别算半宽半高）——原实现只用 X 方向半径（圆形），
          对纵向长条/宽幅地图画会误判（区域远端被判"不在区域内"触发误兜底）。
        - 余量自适应：min(宽, 高) 的 10%，下限 40 格——小图（128）≈40 格、
          大图（512+）自动放大，覆盖传送落点偏差又不至于过度外扩。
        2026-08-15 第二批（D2）：可选 y 高度校验——bot 站立层 = origin_y-1（地面），
        偏离 >3 格视为不在建造区域（防止 x/z 正确但高度错误的传送落点误判）。
        """
        bounds = self._area_bounds
        if bounds is None:
            try:
                xs = [k[0] for k in self.block_matrix]
                zs = [k[1] for k in self.block_matrix]
                if not xs or not zs:
                    self._area_bounds = (0.0, 0.0, 0.0, 0.0)  # 未知区域：不拦截
                    return True
                w = float(max(xs) - min(xs))
                h = float(max(zs) - min(zs))
                margin = max(40.0, min(w, h) * 0.10)
                cx = self.origin_x + (min(xs) + max(xs)) / 2.0
                cz = self.origin_z + (min(zs) + max(zs)) / 2.0
                bounds = (cx, cz, w / 2.0 + margin, h / 2.0 + margin)
                self._area_bounds = bounds
            except Exception:
                return True
        cx, cz, half_w, half_h = bounds
        if half_w <= 0 or half_h <= 0:
            return True  # 未知区域不拦截（避免误判导致无限兜底）
        if y is not None:
            expected_y = self.origin_y + self._stand_y_offset  # 站立层（地面）
            if abs(y - expected_y) > 3.0:
                return False
        return abs(x - cx) <= half_w and abs(z - cz) <= half_h

    async def _send_teleport(self, cmd: str) -> bool:
        """发送传送指令并等待落地；失败返回 False。"""
        try:
            r = await self.mcp.send_chat(cmd)
            if isinstance(r, dict) and r.get("success") is False:
                self._activity("warn", f"传送失败：{r.get('error', '?')}")
                return False
            # 2026-08-15 修复：等 3.5s 落地稳定（原 2.5s 在悬空传送点/平台边缘时
            # bot 未落地，验证瞬间通过但下一秒掉下平台）
            await asyncio.sleep(3.5)
            self._last_pos = None  # 传送后位置未知，强制重新寻路
            return True
        except Exception as e:
            self._activity("warn", f"传送异常：{e}")
            return False

    # ── 环境检测整合（2026-08-15 用户需求：维度 + 位置 + 附近领地结合）──

    async def _get_bot_environment(self) -> dict:
        """读取 bot 当前维度/位置/所在领地/附近领地（结合后端 bluemap residences）。

        返回 {dimension, location, current_residence, nearby_residences}；
        任一项获取失败时为 None/[]，不影响主流程（只用于诊断与校验）。
        """
        env: dict = {
            "dimension": None,
            "location": None,
            "current_residence": None,
            "nearby_residences": [],
        }
        try:
            st = await self.mcp.get_player_state()
            d = st.get("data", st) if isinstance(st, dict) else {}
            loc = d.get("location") or {}
            env["location"] = loc or None
            env["dimension"] = d.get("dimension") or None
        except Exception:
            pass
        loc = env.get("location") or {}
        x, z, y = loc.get("x"), loc.get("z"), loc.get("y", 64)
        if x is None or z is None:
            return env
        try:
            from vmtools_next.main import get_bluemap_monitor
            mon = get_bluemap_monitor()
            if mon is None:
                return env
            rs = mon.get_residences() or []
            # mineflayer dimension 值 → bluemap 世界名（Residence marker 的 world 字段）
            bm_world = {
                "overworld": "world",
                "world_nether": "world_nether",
                "world_the_end": "world_the_end",
            }.get(env.get("dimension") or "", env.get("dimension") or "")
            dists: list = []
            for r in rs:
                w = r.get("world") or ""
                if w and w != bm_world:
                    continue
                shape = r.get("shape") or []
                if len(shape) >= 3:
                    my = r.get("min_y", -1e9) or -1e9
                    My = r.get("max_y", 1e9) or 1e9
                    if my <= y <= My and _point_in_polygon_2d(x, z, shape):
                        env["current_residence"] = {
                            "name": r.get("label"),
                            "owner": r.get("owner"),
                            "area": r.get("area"),
                        }
                p = r.get("position") or {}
                px, pz = p.get("x"), p.get("z")
                if px is not None and pz is not None:
                    d2 = (px - x) ** 2 + (pz - z) ** 2
                    dists.append((d2, r.get("label"), r.get("owner")))
            env["nearby_residences"] = [
                {"name": n, "owner": o, "distance": round(d2 ** 0.5, 1)}
                for d2, n, o in sorted(dists)[:5]
            ]
        except Exception:
            pass
        return env

    async def _check_build_environment(self) -> dict:
        """启动建造前检查：维度 + 可自定义领地（config.map_art_residence / map_art_build_world）。

        只做诊断与告警（不符合预期不终止，由后续传送定位/兜底链继续处理）：
        - bot 在错误维度（如补货后被留在末地仓库）→ 警告，提醒会尝试传送回建造点
        - bot 所在领地 ≠ 配置的建造领地 → 警告（领地可自定义，空=不校验）
        同时输出「附近领地」列表帮助确认 bot 当前位置。
        """
        env = await self._get_bot_environment()
        loc = env.get("location") or {}
        res = env.get("current_residence") or {}
        res_name = res.get("name") or "无/未知"
        nearby = env.get("nearby_residences") or []
        nearby_names = "、".join(str(n.get("name")) for n in nearby[:5]) or "无"
        self._activity(
            "info",
            f"环境检测：维度={env.get('dimension')} 位置=({loc.get('x', '?')},{loc.get('z', '?')}) "
            f"所在领地={res_name} 附近领地={nearby_names}")
        dim = env.get("dimension")
        if dim and self._build_world and dim != self._build_world:
            self._activity(
                "warn",
                f"⚠️ bot 维度 {dim} ≠ 建造维度 {self._build_world}——bot 可能在错误世界"
                f"（如补货后被留在末地仓库），将尝试传送回建造点")
        if self._build_residence and res_name not in ("无/未知", None):
            if str(res_name).lower() != self._build_residence.lower():
                self._activity(
                    "warn",
                    f"⚠️ bot 所在领地 {res_name} ≠ 配置的建造领地 {self._build_residence}"
                    f"——若 bot 能传送回建造点则继续，否则检查领地权限/坐标")
        return env

    async def _verify_at_build_area(self, retries: int = 2) -> Optional[str]:
        """传送后验证 bot 是否真的回到建造区域附近（2026-08-16 P0-4 改造）。

        返回 None = 验证通过；否则返回失败原因标签（供 _try_teleport_home 分流）：
          - "teleport_no_effect"  ：多次无法获取位置 / 位置不在建造区域（传送未生效或传错位置）
          - "fall_after_teleport" ：位置对但高度不符 / 未落地 / 复查漂移（传回后再次坠落/悬空）
        """
        for attempt in range(retries + 1):
            if attempt > 0:
                await asyncio.sleep(1.5)
            p = await self._get_player_pos_full()
            if p is None:
                if attempt < retries:
                    self._activity("debug",
                                   f"传送后位置获取失败，{1.5}s 后重试（{attempt + 1}/{retries}）")
                    continue
                self._activity("warn", "传送后多次尝试仍无法获取 bot 位置——判定传送未生效")
                return "teleport_no_effect"
            x, z, y = p
            expected_y = self.origin_y + self._stand_y_offset  # 站立层（平台顶）
            # ⚠️ 2026-08-16 修复：bot 坐标 y = 脚的位置。站在地图画方块（y=69）上
            # 脚 y=70（偏差1.0）是正常位置（边放边踩后站在已放方块上），
            # 原 `>=1.0` 把 1.0 判为不符 → 传送后反复误判"高度不符"兜底循环。
            # 统一用 _verify_y_tol（>容差才失败），与 _move_to verify_height 一致。
            if abs(float(y) - expected_y) > self._verify_y_tol:
                self._activity("warn",
                               f"传送后高度不符（站立层={expected_y}，实际y={y:.1f}）——"
                               f"判定未到位（可能悬空/掉水），走兜底")
                return "fall_after_teleport"
            if self._near_build_area(x, z):  # x/z 判断（y 已单独严格校验）
                # 复查：等 1.5s 再确认位置没变（防悬空瞬间验证通过后掉下去）
                await asyncio.sleep(1.5)
                try:
                    st = await self.mcp.get_player_state()
                    d2 = st.get("data", st) if isinstance(st, dict) else {}
                    on_ground = d2.get("is_on_ground")
                    if on_ground is False:
                        self._activity("warn",
                                       f"传送后 bot 未落地（on_ground=False，悬空/水中）——判定未到位，走兜底")
                        return "fall_after_teleport"
                except Exception:
                    pass
                p2 = await self._get_player_pos_full()
                if p2 is None:
                    self._activity("debug",
                                   f"传送后位置验证通过（{x:.0f},{z:.0f},y={y:.0f}），复查位置获取失败视为通过")
                    return None
                x2, z2, y2 = p2
                if (abs(x2 - x) > 3.0 or abs(z2 - z) > 3.0
                        or abs(float(y2) - expected_y) > self._verify_y_tol):
                    self._activity("warn",
                                   f"传送后位置复查异常（初始{x:.0f},{z:.0f},y={y:.0f}→复查"
                                   f"{x2:.0f},{z2:.0f},y={y2:.0f}）——bot 未稳定，判定未到位")
                    return "fall_after_teleport"
                self._activity("debug",
                               f"传送后位置验证通过（{x:.0f},{z:.0f},y={y:.0f}）在建造区域附近")
                return None
            self._activity("warn",
                           f"传送后位置不在建造区域（{x:.0f},{z:.0f},y={y:.0f}），需固定指令兜底")
            return "teleport_no_effect"
        return "teleport_no_effect"

    async def _wait_landed(self, timeout_s: float = 5.0) -> bool:
        """落地稳定化（P0-4）：等待 bot 真正落地（is_on_ground=true 且位置稳定）。

        用于「传回后再次坠落」场景——bot 传送到悬空处/水中时，先等落地稳定
        再验证，避免反复「传送→坠落→再传送」的空转。
        """
        try:
            t0 = time.monotonic()
            last_y = None
            stable_ticks = 0
            while time.monotonic() - t0 < timeout_s:
                st = await self.mcp.get_player_state()
                d2 = st.get("data", st) if isinstance(st, dict) else {}
                on_ground = d2.get("is_on_ground")
                loc = d2.get("location") or {}
                cy = loc.get("y")
                if on_ground is True and isinstance(cy, (int, float)):
                    if last_y is not None and abs(float(cy) - last_y) < 0.05:
                        stable_ticks += 1
                        if stable_ticks >= 3:  # 连续 3 次采样位置稳定且落地
                            return True
                    else:
                        stable_ticks = 0
                    last_y = float(cy)
                await asyncio.sleep(0.6)
            return False
        except Exception:
            return False

    async def _try_teleport_home(self, reason: str = "") -> bool:
        """传送回建造点（2026-08-16 P0-4 兜底状态机，替换原固定三级链）：

        分级与失败原因分流：
          1) 临时点传送（/ehomes dth）——每级内重试 _tp_retry_each 次；
             · teleport_no_effect（传送未生效/传错位置）→ 换下一级传送；
             · fall_after_teleport（传回后坠落/未落地）→ 先 _wait_landed 落地稳定化，
               稳定后再验证，仍失败才换级；
          2) 固定指令兜底（return_fixed，如 /ehomes mapart）——同策略；
          3) pathfinder + 蹲搭走回建造区（传送链全失败时的自愈）。
        总尝试上限 _tp_retry_total（默认 8）——防「传送未生效」死循环空转；
        每次失败记录原因标签/次数/耗时（P2-1 兜底决策日志）。
        """
        t_start = time.monotonic()
        attempts = 0
        fail_log: list[str] = []

        async def _try_tp(cmd: str) -> bool:
            nonlocal attempts
            for _i in range(self._tp_retry_each):
                if self._stopped:
                    return False
                attempts += 1
                if attempts > self._tp_retry_total:
                    self._activity("error",
                                   f"传送兜底尝试次数超上限（{self._tp_retry_total}），放弃")
                    return True  # 占位：实际返回 True 会导致误判成功——由调用方校验位置
                if not await self._send_teleport(cmd):
                    fail_log.append(f"{cmd}:send_fail")
                    continue
                verify = await self._verify_at_build_area()
                if verify is None:
                    return True
                fail_log.append(f"{cmd}:{verify}")
                if verify == "fall_after_teleport":
                    # 传回后坠落 → 先落地稳定化再复验（区分于传送未生效）
                    self._activity("warn", "传送到位但未稳定（坠落/悬空），等待落地稳定后复验…")
                    if await self._wait_landed():
                        verify2 = await self._verify_at_build_area()
                        if verify2 is None:
                            return True
                        fail_log.append(f"{cmd}:landed:{verify2}")
            return False

        # 1) 临时点传送（分级重试）
        cmd = self._supply_cfg.get("return", "/ehomes dth")
        if reason:
            self._activity("warn", f"{reason}，传送回建造点（{cmd}）")
        else:
            self._activity("info", f"传送回建造点（{cmd}）")
        if await _try_tp(cmd):
            self._activity("debug", f"传送兜底成功（{cmd}，共尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
            return True

        # 2) 固定指令兜底（2026-08-15：DB 未配置 return_fixed 时回退默认 /ehomes mapart）
        fixed = (self._supply_cfg.get("return_fixed") or "/ehomes mapart").strip()
        if fixed and fixed != cmd:
            self._activity("warn", f"临时传送点不可用，改用固定指令兜底（{fixed}）")
            if await _try_tp(fixed):
                self._activity("debug", f"传送兜底成功（{fixed}，共尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
                return True

        # 3) 2026-08-15 新增：pathfinder + 蹲搭走回建造区（传送链全失败时的自愈）
        self._activity("warn", f"传送回建造点失败（{attempts} 次，原因 {';'.join(fail_log) or 'unknown'}），尝试寻路走回")
        try:
            gx = self.origin_x + self.region.x_start
            gz = self.origin_z + self.region.z_start - 1
            gy = self.origin_y + self._stand_y_offset
            ok = await self._move_to(gx, gy, gz, max_offset=3,
                                     label="walk back to build area",
                                     timeout_ms=30000,
                                     allow_scaffold=True,  # 允许蹲搭搭路（悬崖/落差）
                                     verify_height=True)
            if ok:
                self._activity("info", f"寻路走回建造区成功（{gx},{gy},{gz}）")
                return True
        except Exception as e:
            logger.warning("[%s] Walk-back to build area failed: %s", self.bot_id, e)
        self._activity("warn",
                       f"传送与寻路走回均失败，无法返回建造点（总尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
        return False

    @staticmethod
    def _normalize_item_id(item_id: str) -> str:
        """统一物品 ID：去 minecraft: 前缀 + 去 [后缀（1.21 组件数据）。

        2026-08-14 修复：get_inventory_snapshot 返回的 type 是 "white_concrete"
        （不带前缀），而 DB/配置/block_matrix 里是 "minecraft:white_concrete"
        （带前缀）→ 直接 == 比较永远失败 → 背包明明有货却判定"无/缺"（用户实测
        "取到方块却显示补货失败""背包有方块却显示无方块"的根因）。
        """
        if not item_id:
            return ""
        item_id = str(item_id).split("[")[0].strip()
        if item_id.startswith("minecraft:"):
            item_id = item_id[len("minecraft:"):]
        return item_id

    def _supply_boxes_for(self, item_id: str) -> list:
        """按归一化 ID 查找该材料的潜影盒坐标（supply_boxes key 兼容带/不带前缀）。"""
        norm = self._normalize_item_id(item_id)
        for key, boxes in self._supply_boxes.items():
            if self._normalize_item_id(key) == norm:
                return boxes
        return []

    def _pick_restock_material(self) -> Optional[str]:
        """选一种要补货的材料：优先已配置潜影盒的、其次当前区域需要的方块。"""
        # 1) 已配置补货潜影盒的材料（用户明确指定了坐标，最可靠）
        if self._supply_boxes:
            return next(iter(self._supply_boxes))
        # 2) 从 block_matrix 选第一个非空气方块
        for (_x, _z), bid in self.block_matrix.items():
            clean = bid.split("[")[0] if "[" in bid else bid
            if clean and self._normalize_item_id(clean) != "air":
                return clean
        return None

    async def _ensure_scaffold_material(self) -> bool:
        """蹲搭前确保背包有可放置方块（任务材料或常见方块）；没有则先补货。

        2026-08-14：蹲搭需要用手头的方块，背包只有食物/工具时搭不了——先补货
        （从配置的潜影盒拿任务材料）再蹲搭。
        """
        # 任务需要的材料集合（这些必然是方块；2026-08-14 统一归一化去前缀）
        task_materials: set[str] = set()
        for (_x, _z), bid in self.block_matrix.items():
            clean = self._normalize_item_id(bid)
            if clean and clean != "air":
                task_materials.add(clean)
        # 常见可放置方块（即使不是任务材料也能搭路；归一化无前缀）
        common = {
            "dirt", "cobblestone", "stone",
            "gravel", "sand", "grass_block",
            "cobbled_deepslate", "oak_planks",
        }
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            have: list[str] = []
            for s in items:
                item_id = self._normalize_item_id(s.get("type", ""))
                cnt = s.get("count", 0)
                if cnt > 0 and item_id:
                    have.append(f"{item_id}×{cnt}")
                    if item_id in task_materials or item_id in common:
                        self._activity("debug", f"背包有可放置方块 {item_id}×{cnt}，可直接蹲搭")
                        return True  # 背包有可放置方块，可直接蹲搭
            self._activity("debug", f"背包物品：{('，'.join(have[:20])) if have else '（空）'}——无可用方块，需补货")
        except Exception as e:
            self._activity("debug", f"背包检查失败：{e}（按无可放置方块处理，去补货）")

        # 背包无可放置方块 → 补货一种任务材料（2026-08-14：全量补齐，蹲搭材料也有了）
        material = self._pick_restock_material()
        if not material:
            self._activity("warn", "背包无方块且无可补货材料，无法蹲搭")
            return False
        self._activity("warn", f"背包无方块，先补货 {material} 再蹲搭")
        if await self._do_full_restock(material):
            await self._refresh_hotbar_map()
            return True
        self._activity("warn", f"补货 {material} 失败，无法蹲搭")
        return False

    # ── Restocking ────────────────────────────

    async def _check_inventory_level(self, block_id: str) -> int:
        """Scan player inventory and return count of block_id.

        2026-08-14 修复：snapshot type 无 minecraft: 前缀，DB 配置带前缀——
        统一 _normalize_item_id 后比较（原 == 永远失败 → 明明有货判定缺货）。
        """
        norm = self._normalize_item_id(block_id)
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            total = sum(
                s.get("count", 0)
                for s in items
                if self._normalize_item_id(s.get("type", "")) == norm
            )
            return total
        except Exception:
            return 0

    @staticmethod
    def _default_supply_cfg() -> dict:
        """任务未配置时使用全局默认三个传送指令（config.py map_art_supply_*_command）。

        2026-08-14：新增 return_fixed——固定返回指令（死亡/意外导致临时点 dth
        不在地图画区域时的兜底传送，如 /ehomes mapart 或 /tp x y z）。
        """
        try:
            mf = get_config().mineflayer
            return {
                "go": getattr(mf, "map_art_supply_go_command", "/ehomes mdssj") or "/ehomes mdssj",
                "save": getattr(mf, "map_art_supply_save_command", "/esethomes dth") or "/esethomes dth",
                "return": getattr(mf, "map_art_supply_return_command", "/ehomes dth") or "/ehomes dth",
                "return_fixed": getattr(mf, "map_art_supply_fixed_return_command", "/ehomes mapart") or "/ehomes mapart",
            }
        except Exception:
            return {"go": "/ehomes mdssj", "save": "/esethomes dth", "return": "/ehomes dth",
                    "return_fixed": "/ehomes mapart"}

    @staticmethod
    def _default_food_cfg() -> dict:
        """食物配置默认值（2026-08-14 模块A）。"""
        try:
            mf = get_config().mineflayer
            return {
                "item_id": getattr(mf, "map_art_food_item", "minecraft:cooked_porkchop"),
                "go_command": getattr(mf, "map_art_food_go_command", "/res tp lixiangxiang.qwp"),
                "wait_after_go_ms": int(getattr(mf, "map_art_food_wait_after_go_ms", 5000)),
                "eat_threshold_food": int(getattr(mf, "map_art_eat_threshold_food", 15)),
                "eat_threshold_health": int(getattr(mf, "map_art_eat_threshold_health", 15)),
            }
        except Exception:
            return {
                "item_id": "minecraft:cooked_porkchop",
                "go_command": "/res tp lixiangxiang.qwp",
                "wait_after_go_ms": 5000,
                "eat_threshold_food": 15,
                "eat_threshold_health": 15,
            }

    async def _restock_one_from_boxes(self, clean_id: str, needed_count: int = 64) -> bool:
        """⚠️ 废弃（2026-08-15 第一批重构后不再被调用，保留防意外引用）。

        原逻辑已由 map_art_restock.ShulkerRestocker 取代（dryTicks 取空记忆/背包满
        检查/模块化）；后续清理批次可删除本方法。
        """
        boxes = self._supply_boxes_for(clean_id)
        if not boxes:
            self._activity("warn", f"{clean_id} 未配置潜影盒坐标，无法补货")
            logger.warning("[%s] %s no configured shulker box, skip", self.bot_id, clean_id)
            return False
        for bx, by, bz in boxes:
            self._activity("info", f"寻路到潜影盒 ({bx},{by},{bz}) 取 {clean_id}")
            t0 = time.monotonic()
            moved = await self._move_to(bx, by, bz, max_offset=3,
                                        label=f"shulker({bx},{by},{bz})",
                                        timeout_ms=20000, allow_scaffold=False)
            self._activity("debug", f"寻路到 ({bx},{by},{bz}) {'成功' if moved else '失败'}，耗时 {time.monotonic() - t0:.1f}s")
            if not moved:
                self._activity("warn", f"寻路到潜影盒 ({bx},{by},{bz}) 失败，尝试下一个")
                continue
            try:
                open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
            except Exception as e:
                logger.warning("[%s] Open shulker at (%d,%d,%d) error: %s",
                               self.bot_id, bx, by, bz, e)
                self._activity("debug", f"open_container_at 抛异常：{e}")
                continue
            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
            container_id = (data or {}).get("container_id") or ""
            if container_id:
                self._activity("debug",
                               f"开箱成功：{data.get('block_name', '?')} container_id={container_id[:8]}.. "
                               f"槽位数={data.get('slot_count', '?')}")
            else:
                self._activity("warn", f"开箱失败：{(data or {}).get('error', '?')}，等 1s 重试")
                await asyncio.sleep(1.0)
                try:
                    open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                    data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                    container_id = (data or {}).get("container_id") or ""
                except Exception:
                    container_id = ""
                if not container_id:
                    self._activity("warn", f"开箱失败（潜影盒 {bx},{by},{bz}），尝试下一个")
                    continue
            self._activity("debug", f"请求取货：{clean_id} ×{needed_count}")
            try:
                wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
            except Exception as e:
                self._activity("warn", f"开箱后取货失败：{e}")
                logger.warning("[%s] Withdraw %s from (%d,%d,%d) error: %s",
                               self.bot_id, clean_id, bx, by, bz, e)
                try:
                    await self.mcp.close_container(container_id)
                except Exception:
                    pass
                continue
            try:
                await self.mcp.close_container(container_id)
            except Exception:
                pass
            if isinstance(wd, dict) and wd.get("success") is False:
                err = wd.get("error", "?")
                c_items = wd.get("container_items") or []
                if c_items:
                    self._activity("debug",
                                   f"容器内物品（{wd.get('item_count', len(c_items))}种）：{'，'.join(c_items[:15])}")
                self._activity("warn", f"取货失败：{err}，尝试下一个坐标")
                logger.warning("[%s] Withdraw %s from (%d,%d,%d) failed: %s",
                               self.bot_id, clean_id, bx, by, bz, err)
                continue
            got_count = (wd or {}).get("count", needed_count) if isinstance(wd, dict) else needed_count
            logger.info("[%s] Shulker restock done: %s ×%d from (%d,%d,%d)",
                        self.bot_id, clean_id, got_count, bx, by, bz)
            self._activity("info", f"取到 {clean_id} ×{got_count}")
            # 2026-08-15：取货后必须背包确认——withdraw 返回 success 不代表背包已同步。
            # 循环轮询背包直到出现该材料（最多 3s），确认真正拿到才算补货成功。
            for _i in range(10):
                await asyncio.sleep(0.3)
                if await self._check_inventory_level(clean_id) > 0:
                    self._activity("debug", f"背包确认：{clean_id} ×{await self._check_inventory_level(clean_id)}")
                    return True
            self._activity("warn", f"{clean_id} 取货后背包未确认到物品（可能是假成功），视为失败")
            logger.warning("[%s] %s withdraw success but inventory check empty", self.bot_id, clean_id)
            # 不 return True，继续尝试下一个坐标
            continue
        self._activity("warn", f"{clean_id} 所有潜影盒均未取到（可能取空/坐标不符/盒子放错）")
        return False

    @_restock_serialized
    async def _do_full_restock(self, trigger_item: str) -> bool:
        """全量补货（2026-08-15 第一批重构：target/have 模型 + 模块化执行）。

        迁移 playercontrolpp AutoRestockFeature 的决策模型：
        - 缺料判定：区域材料需求（RestockPlanner.region_material_count）中
          背包散装量 < target（target = min(区域剩余需求, map_art_restock_stacks×64)，
          默认 4 组 = 256）的材料，按满足度（have/target）最低优先排序取料
        - 未配置潜影盒坐标的材料：提示并跳过（用户确认，不再静默失败）
        - 执行：ShulkerRestocker（dryTicks 取空记忆 + 背包满检查 + withdraw 背包确认），
          传送只做一次（暂存→仓库→逐个取→返回），补两轮 + 全量复查
        - 零收获总闸：连续 3 轮补货无收获 → 终止本 bot 区域（防缺料死循环）
        """
        clean_trigger = self._normalize_item_id(trigger_item)
        self._last_restock_at = time.monotonic()

        # 1) 区域材料需求 + 背包现状（target/have 模型；区域需求缓存一次）
        if self._region_materials is None:
            self._region_materials = RestockPlanner.region_material_count(
                self.block_matrix, self.region, self.origin_x, self.origin_z)
        have_counts: dict[str, int] = {}
        for mat in self._region_materials:
            have_counts[mat] = await self._check_inventory_level(mat)
        planner = RestockPlanner(stacks_per_item=self._restock_stacks)
        needs = planner.compute_needs(self._region_materials, have_counts, self._supply_boxes)

        # 2) 触发材料强制加入（区域统计可能未覆盖/已满足但本次就是要用它）
        if not any(n.item_id == clean_trigger for n in needs):
            have_trigger = await self._check_inventory_level(clean_trigger)
            if have_trigger < 64:  # 触发材料不足一组 → 补
                needs.append(Need(
                    item_id=clean_trigger,
                    target=planner.plan_target(64, self._restock_stacks),
                    have=have_trigger,
                    boxes=self._supply_boxes_for(clean_trigger),
                ))
                needs.sort(key=lambda n: (n.ratio, n.item_id))
        if not needs:
            self._activity("info", "背包材料充足，无需补货")
            return True

        # 未配置坐标的材料：提示并跳过（用户确认）
        unboxed = [n.item_id for n in needs if not n.boxes]
        if unboxed:
            self._activity("warn",
                           f"以下材料任务需要但未配置潜影盒坐标，将跳过：{'，'.join(unboxed)}")
        need_with_boxes = [n for n in needs if n.boxes]
        if not need_with_boxes:
            self._activity("warn", "所有缺料均未配置潜影盒坐标，无法补货")
            return False
        self._activity("warn",
                       f"需补货材料（{len(need_with_boxes)}种，按缺货程度排序）："
                       f"{'，'.join(f'{n.item_id}({n.have}/{n.target})' for n in need_with_boxes)}")

        # 3) 暂存当前位置 → 传送仓库 → 等 chunk 加载
        self.progress.state = "restocking"
        try:
            r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] save command failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            self._activity("info", f"暂存当前位置（{self._supply_cfg.get('save', '/esethomes dth')}）")
            await asyncio.sleep(1.5)
            r2 = await self.mcp.send_chat(self._supply_cfg.get("go", "/ehomes mdssj"))
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] go command failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            self._activity("info", f"传送前往仓库（{self._supply_cfg.get('go', '/ehomes mdssj')}）")
            self._activity("debug", "传送指令已发出，等待 3.5s 让 chunk 加载、bot 落地...")
            await asyncio.sleep(3.5)
            self._activity("debug", "等待完成，开始逐个取货")

            # 4) ShulkerRestocker 逐个补齐（满足度最低优先；dryTicks/背包满/背包确认；补两轮）
            restocker = self._get_restocker()
            restocker.reset_drained()
            for _round in range(2):
                if not need_with_boxes:
                    break
                next_round: list = []
                for need in need_with_boxes:
                    have = await restocker.restock_material(need.item_id, need.target, need.boxes)
                    if have < need.target:
                        next_round.append(need)
                need_with_boxes = next_round
                if need_with_boxes:
                    self._activity("warn",
                                   f"第一轮补货后仍缺：{'，'.join(n.item_id for n in need_with_boxes)}，再补一轮")
            still_missing = [n.item_id for n in need_with_boxes]

            # 5) 返回建造点（报告最终缺失 + 零收获总闸）
            if still_missing:
                self._activity("warn",
                               f"补货结束仍有缺失（{len(still_missing)}种）：{'，'.join(still_missing)}——"
                               f"可能是潜影盒取空/坐标不符，回建造点后再试")
                # 本次有收获（至少一种补到 target）→ 重置计数；全无收获 → 累计
                gained = False
                for n in needs:
                    if n.boxes and await self._check_inventory_level(n.item_id) >= n.target:
                        gained = True
                        break
                if not gained:
                    self._no_gain_cycles += 1
                    if self._no_gain_cycles >= 3:
                        self._activity("error",
                                       "连续 3 轮补货零收获，判定材料严重不足，终止本 bot 区域")
                        self._stopped = True  # 主循环将退出（防缺料死循环）
                else:
                    self._no_gain_cycles = 0
            else:
                self._no_gain_cycles = 0
                self._activity("info", f"全部补齐（{len(needs)}种材料均已确认在背包）")
            self._activity("info", f"传送返回建造点（{self._supply_cfg.get('return', '/ehomes dth')}）")
            try:
                r_ret = await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                # 2026-08-15 修复：检查返回指令是否真正发出（原 try/except 吞掉 success:false，
                # 曾导致 save 指令错误（/esethome 单数）时 dth 家未保存、返回传送静默失败）
                if isinstance(r_ret, dict) and r_ret.get("success") is False:
                    self._activity("warn",
                                   f"返回指令发送失败：{r_ret.get('error', '?')}（检查 supply_config 的 save/return 指令）")
                await asyncio.sleep(1.5)
            except Exception as e:
                self._activity("warn", f"返回指令异常：{e}")
                await asyncio.sleep(1.5)
            self._last_pos = None  # 传送后位置未知，强制下次寻路
            self.progress.state = "placing"
            # ⚠️ 2026-08-16 修复：Via 传送后客户端背包数据延迟且可能【部分】同步
            # （不同槽位数据到达时间不一）——原"等背包非空就 break"可能只等到部分
            # 材料（如 gray/white 在、black 未到）→ check(black)=0 → 误判补货失败。
            # 改为【轮询等待目标材料（clean_id）出现】（最多 10s），确保 select 前
            # 该材料数据已就绪。
            for _wait in range(20):
                try:
                    if (await self._check_inventory_level(clean_id)) > 0:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            await self._refresh_hotbar_map()
            # ⚠️ 2026-08-16 修复：返回「目标材料（clean_id）是否已取到」，而非
            # not still_missing——个别材料缺失（如 cyan 盒子放错成 orange，供应链
            # 问题）会导致整体返回 False → 调用方 `_ensure_item_in_hand` 误判
            # 目标材料补货失败 → 连 select 都不执行 → "补货后仍无法装备" → 缺块。
            try:
                _have_target = (await self._check_inventory_level(clean_id)) > 0
            except Exception:
                _have_target = not still_missing
            return _have_target
        except Exception as e:
            logger.warning("[%s] Full restock failed: %s", self.bot_id, e)
            self._activity("warn", f"全量补货异常：{e}")
            return False

    def _get_restocker(self) -> ShulkerRestocker:
        """懒创建 ShulkerRestocker（寻路包装 allow_scaffold=False 防递归补货）。"""
        if self._restocker is None:
            async def _move_to_box(x: int, y: int, z: int) -> bool:
                return await self._move_to(x, y, z, max_offset=3,
                                           label=f"shulker({x},{y},{z})",
                                           timeout_ms=20000, allow_scaffold=False)
            self._restocker = ShulkerRestocker(
                mcp=self.mcp,
                check_inventory=self._check_inventory_level,
                move_to_cb=_move_to_box,
                activity_cb=self._activity,
                log_prefix=self.bot_id,
            )
        return self._restocker

    @_restock_serialized
    async def _do_restock(self, needed_block_id: str, needed_count: int = 64) -> bool:
        """Restock the required item.

        Strategies (优先级从高到低，2026-08-14 更新)：
          0. 材料级潜影盒坐标（用户配置 map_art_supply_boxes）：暂存位置 → 传送补给点 →
             寻路到该材料潜影盒坐标打开取货 → 返回工作位置（三个指令均可自定义）
          1. 分区补给箱（_supply_box 已配置）：寻路到补给箱附近 → 打开取货 → 返回建造位置
          2. fallback EssentialsX 传送：/esethome gzqy → /ehomes mdssj → withdraw → /ehomes gzqy
        """
        self.progress.state = "restocking"
        clean_id = needed_block_id.split("[")[0] if "[" in needed_block_id else needed_block_id

        # 记录建造位置（传送补货时回程用）
        build_pos = self._last_pos

        # ── 策略 0（2026-08-14）：材料级潜影盒坐标（用户配置，优先级最高） ──
        boxes = self._supply_boxes.get(clean_id) or []
        if boxes:
            try:
                logger.info("[%s] Restock %s from configured shulker boxes (%d coords)",
                            self.bot_id, clean_id, len(boxes))
                # 1. 暂存当前位置（可自定义指令，如 /esethomes dth）
                r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
                if isinstance(r1, dict) and r1.get("success") is False:
                    logger.warning("[%s] save command failed: %s", self.bot_id, r1.get("error", "?"))
                    return False
                self._activity("info", f"暂存当前位置（{self._supply_cfg.get('save', '/esethomes dth')}）")
                await asyncio.sleep(1.5)

                # 2. 前往补给点（可自定义指令，通常为传送，如 /ehomes mdssj）
                r2 = await self.mcp.send_chat(self._supply_cfg.get("go", "/ehomes mdssj"))
                if isinstance(r2, dict) and r2.get("success") is False:
                    logger.warning("[%s] go command failed: %s", self.bot_id, r2.get("error", "?"))
                    return False
                self._activity("info", f"传送前往仓库（{self._supply_cfg.get('go', '/ehomes mdssj')}）")
                # 传送后等待 chunk 加载（原 2.5s 不足：bot 未落地 chunk 未加载，
                # blockAt 返回空 → open_container_at 直接失败 → 误回传建造点）
                self._activity("debug", "传送指令已发出，等待 3.5s 让 chunk 加载、bot 落地...")
                await asyncio.sleep(3.5)
                self._activity("debug", "等待完成，开始寻路到潜影盒")

                # 3. 按顺序尝试每个潜影盒坐标（先显式寻路到坐标附近触发 chunk 加载，再开箱）
                taken = False
                for bx, by, bz in boxes:
                    # 显式寻路到潜影盒附近（触发 chunk 加载 + bot 到位；max_offset=3
                    # 比 2 更宽松，避免最后 1~2 格不可达导致 20s 超时）
                    self._activity("info", f"寻路到潜影盒 ({bx},{by},{bz})")
                    t0 = time.monotonic()
                    moved = await self._move_to(bx, by, bz, max_offset=3,
                                                label=f"shulker({bx},{by},{bz})",
                                                timeout_ms=20000)
                    self._activity("debug", f"寻路到潜影盒 ({bx},{by},{bz}) {'成功' if moved else '失败'}，耗时 {time.monotonic() - t0:.1f}s")
                    if not moved:
                        self._activity("warn", f"寻路到潜影盒 ({bx},{by},{bz}) 失败")
                        logger.warning("[%s] 寻路到潜影盒(%d,%d,%d)失败，尝试下一个",
                                       self.bot_id, bx, by, bz)
                        continue
                    try:
                        open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                    except Exception as e:
                        logger.warning("[%s] Open shulker at (%d,%d,%d) error: %s",
                                       self.bot_id, bx, by, bz, e)
                        self._activity("debug", f"open_container_at 抛异常：{e}")
                        continue
                    data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                    container_id = (data or {}).get("container_id") or ""
                    if container_id:
                        self._activity("debug",
                                       f"开箱成功：{data.get('block_name', '?')} container_id={container_id[:8]}.. "
                                       f"槽位数={data.get('slot_count', '?')}")
                    else:
                        # 寻路已到位但开箱失败：可能是 chunk 尚未完全加载，等 1s 重试一次
                        logger.warning("[%s] Open shulker at (%d,%d,%d) failed: %s，等 1s 重试",
                                       self.bot_id, bx, by, bz, (data or {}).get("error", "?"))
                        self._activity("warn", f"开箱失败：{(data or {}).get('error', '?')}，等 1s 重试")
                        await asyncio.sleep(1.0)
                        try:
                            open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                            container_id = (data or {}).get("container_id") or ""
                            if container_id:
                                self._activity("debug",
                                               f"二次开箱成功：{data.get('block_name', '?')} container_id={container_id[:8]}..")
                        except Exception:
                            container_id = ""
                        if not container_id:
                            self._activity("warn", f"开箱失败（潜影盒 {bx},{by},{bz}），尝试下一个")
                            logger.warning("[%s] Shulker (%d,%d,%d) 二次开箱仍失败，尝试下一个",
                                           self.bot_id, bx, by, bz)
                            continue
                    # 2026-08-14 修复：withdraw 用 try/except 包裹——Python 端对 Node
                    # 返回 success:false 会抛 MineflayerError（而非返回 dict），原代码
                    # isinstance 判断永不命中、异常被外层 except 捕获 → 误 fallback 到
                    # 策略2 传送（"挥手瞬间被传回"的根因）。现在失败→尝试下一个坐标，
                    # 且 finally 关闭容器防泄漏。
                    self._activity("debug", f"请求取货：{clean_id} ×{needed_count}")
                    try:
                        wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
                    except Exception as e:
                        self._activity("warn", f"开箱后取货失败：{e}")
                        logger.warning("[%s] Withdraw %s from (%d,%d,%d) error: %s，尝试下一个坐标",
                                       self.bot_id, clean_id, bx, by, bz, e)
                        try:
                            await self.mcp.close_container(container_id)
                        except Exception:
                            pass
                        continue
                    try:
                        await self.mcp.close_container(container_id)
                    except Exception:
                        pass
                    if isinstance(wd, dict) and wd.get("success") is False:
                        err = wd.get("error", "?")
                        # 诊断增强：容器内容摘要（Node 端已附带 container_items）
                        c_items = wd.get("container_items") or []
                        if c_items:
                            self._activity("debug", f"容器内物品（{wd.get('item_count', len(c_items))}种）：{'，'.join(c_items[:15])}")
                        self._activity("warn", f"取货失败：{err}，尝试下一个坐标")
                        logger.warning(
                            "[%s] Withdraw %s from (%d,%d,%d) failed: %s，尝试下一个坐标",
                            self.bot_id, clean_id, bx, by, bz, err)
                        continue
                    taken = True
                    got_count = (wd or {}).get("count", needed_count) if isinstance(wd, dict) else needed_count
                    logger.info("[%s] Shulker restock done: %s ×%d from (%d,%d,%d)",
                                self.bot_id, clean_id, got_count, bx, by, bz)
                    self._activity("info", f"开箱成功，取到 {clean_id} ×{got_count}")
                    break
                if not taken:
                    logger.warning("[%s] 所有配置潜影盒均未取到 %s（可能取空/坐标不符）", self.bot_id, clean_id)

                # 4. 返回工作位置（可自定义指令，如 /ehomes dth）
                self._activity("info", f"传送返回建造点（{self._supply_cfg.get('return', '/ehomes dth')}）")
                try:
                    await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
                self._last_pos = None  # 传送后位置未知，强制下次寻路
                self.progress.state = "placing"
                return taken
            except Exception as e:
                logger.warning("[%s] Shulker-box restock failed: %s, fallback to old strategy",
                               self.bot_id, e)

        # ── 策略 1：分区补给箱（无传送依赖，适合多 bot 分区） ──
        if self._supply_box is not None:
            try:
                sx, sy, sz = self._supply_box
                logger.info("[%s] Restock from supply box at (%d,%d,%d)",
                            self.bot_id, sx, sy, sz)
                if await self._move_to(sx, sy, sz, max_offset=2, label="supply box",
                                       timeout_ms=25000):
                    # radius=8：实际箱子可能不在建议坐标附近（用户放置位置有偏差）
                    scan = await self.mcp.scan_nearby_blocks(
                        radius=8, max_count=20, material_filter="chest")
                    blocks = (scan.get("data", scan)).get("blocks", [])
                    if blocks:
                        chest = blocks[0]
                        open_result = await self.mcp.open_container_at(
                            chest["x"], chest["y"], chest["z"], timeout_ms=10000)
                        data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                        container_id = (data or {}).get("container_id") or ""
                        if not container_id:
                            logger.warning("[%s] Open supply box failed: %s，回退传送仓库",
                                           self.bot_id, (data or {}).get("error", "?"))
                            if build_pos:
                                await self._move_to(*build_pos, max_offset=2,
                                                    label="back to build pos")
                        else:
                            wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
                            await self.mcp.close_container(container_id)
                            # 2026-08-14 审查修复：校验取货结果，失败不返回成功
                            # （否则 bot 继续建造但手里没物品，静默漏块）
                            if isinstance(wd, dict) and wd.get("success") is False:
                                logger.warning(
                                    "[%s] Supply-box withdraw %s failed: %s，回退传送仓库",
                                    self.bot_id, clean_id, wd.get("error", "?"))
                                # 先返回建造位置再走策略2（避免策略2把补给箱处存为临时家）
                                if build_pos:
                                    await self._move_to(*build_pos, max_offset=2,
                                                        label="back to build pos")
                            else:
                                logger.info("[%s] Supply-box restock done: %s ×%d",
                                            self.bot_id, clean_id, needed_count)
                                # 返回建造位置
                                if build_pos:
                                    await self._move_to(*build_pos, max_offset=2,
                                                        label="back to build pos")
                                self.progress.state = "placing"
                                return True
                logger.warning("[%s] Supply box unavailable, fallback to teleport",
                               self.bot_id)
            except Exception as e:
                logger.warning("[%s] Supply-box restock failed: %s, fallback to teleport",
                               self.bot_id, e)

        # ── 策略 2：EssentialsX 传送仓库 ──
        saved_pos = False
        try:
            # 1. 保存当前位置（命令失败 → 立即中止，避免位置未知继续误操作）
            logger.info("[%s] Saving position → /esethome %s", self.bot_id, self.TEMP_HOME)
            r1 = await self.mcp.send_chat(f"/esethome {self.TEMP_HOME}")
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] /esethome failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            saved_pos = True  # 位置保存成功，finally 才允许传送回（2026-08-14 审查修复）
            await asyncio.sleep(1.5)

            # 2. 传到仓库
            logger.info("[%s] Teleporting to warehouse → /ehomes %s", self.bot_id, self.WAREHOUSE_HOME)
            r2 = await self.mcp.send_chat(f"/ehomes {self.WAREHOUSE_HOME}")
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] /ehomes warehouse failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            await asyncio.sleep(2.5)

            # 3. 扫描附近找容器
            scan = await self.mcp.scan_nearby_blocks(radius=6, max_count=20, material_filter="chest")
            blocks = (scan.get("data", scan)).get("blocks", [])
            if not blocks:
                logger.warning("[%s] 仓库附近没找到容器", self.bot_id)
                return False

            chest = blocks[0]
            cx, cy, cz = chest["x"], chest["y"], chest["z"]

            # 4. 打开 → 取材料 → 关（2026-08-14 修复：用 container_id 而非 inventoryId）
            logger.info("[%s] Opening container at (%d,%d,%d)", self.bot_id, cx, cy, cz)
            open_result = await self.mcp.open_container_at(cx, cy, cz, timeout_ms=10000)
            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
            container_id = (data or {}).get("container_id") or ""
            if not container_id:
                logger.warning("[%s] Open warehouse container failed: %s",
                               self.bot_id, (data or {}).get("error", "?"))
                return False

            wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
            await self.mcp.close_container(container_id)
            if isinstance(wd, dict) and wd.get("success") is False:
                logger.warning("[%s] Warehouse withdraw %s failed: %s",
                               self.bot_id, clean_id, wd.get("error", "?"))
                return False

            logger.info("[%s] Restock done: %s ×%d, returning...", self.bot_id, clean_id, needed_count)
            return True

        except Exception as e:
            logger.error("[%s] Restock failed: %s", self.bot_id, e)
            return False
        finally:
            # 5. 传回建造位置（仅当位置已成功保存——/esethome 失败时传回会迷失）；
            #    try/except 防覆盖返回值
            if saved_pos:
                try:
                    await self.mcp.send_chat(f"/ehomes {self.TEMP_HOME}")
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
            self._last_pos = None  # 传送后位置未知，强制下次寻路
            self.progress.state = "placing"

    # ── 食物监控 + 补货（2026-08-14 模块A）──────────────────────────────

    async def _ensure_food_offhand(self) -> bool:
        """确保副手 (slot 45) 有食物（猪排），没有则补货。

        返回 True 表示副手已有食物或补货成功，False 表示补货失败（不影响建造）。
        """
        food_item = self._food_cfg.get("item_id", "minecraft:cooked_porkchop")
        # 检查副手是否已有食物
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            for s in items:
                if s.get("slot") == 40:  # 前端归一化后副手=40
                    item_id = (s.get("type", "") or "").split("[")[0]
                    if item_id == food_item and s.get("count", 0) > 0:
                        return True
        except Exception:
            pass

        # 副手无食物 → 尝试从背包装备
        try:
            r = await self.mcp.equip_offhand(food_item)
            if r.get("success"):
                logger.info("[%s] Equipped %s to offhand from inventory", self.bot_id, food_item)
                return True
        except Exception as e:
            logger.warning("[%s] equip_offhand %s failed: %s", self.bot_id, food_item, e)

        # 背包也没有 → 食物补货
        logger.info("[%s] 猪排不足，开始食物补货...", self.bot_id)
        if await self._do_food_restock():
            return await self._ensure_food_offhand()  # 递归一次（补货后再次装备）
        return False

    @_restock_serialized
    async def _do_food_restock(self) -> bool:
        """去猪排仓库取猪排。

        独立于材料补货：猪排仓库指令不同（/res tp lixiangxiang.qwp），
        且指令发后需等 5s（指令自带 3s 延迟 + 2s 安全余量）才能开始寻路。
        """
        self.progress.state = "restocking"
        food_item = self._food_cfg.get("item_id", "minecraft:cooked_porkchop")
        go_cmd = self._food_cfg.get("go_command", "/res tp lixiangxiang.qwp")
        wait_ms = int(self._food_cfg.get("wait_after_go_ms", 5000))

        boxes = self._food_boxes
        if not boxes:
            logger.warning("[%s] 食物潜影盒未配置，无法补货猪排", self.bot_id)
            self.progress.state = "placing"
            return False

        try:
            # 1. 保存当前位置
            r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] Food save command failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            await asyncio.sleep(1.5)

            # 2. 前往猪排仓库（指令后等 5s 再寻路）
            logger.info("[%s] Food restock: %s → wait %ds", self.bot_id, go_cmd, wait_ms // 1000)
            self._activity("info", f"猪排不足，传送前往食物仓库（{go_cmd}）")
            r2 = await self.mcp.send_chat(go_cmd)
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] Food go command failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            await asyncio.sleep(wait_ms / 1000.0)

            # 3. 按顺序尝试每个潜影盒坐标（先显式寻路触发 chunk 加载，再开箱）
            taken = False
            for bx, by, bz in boxes:
                # 显式寻路到潜影盒附近（触发 chunk 加载 + bot 到位）
                moved = await self._move_to(bx, by, bz, max_offset=3,
                                            label=f"food-shulker({bx},{by},{bz})",
                                            timeout_ms=20000)
                if not moved:
                    logger.warning("[%s] 寻路到食物潜影盒(%d,%d,%d)失败，尝试下一个",
                                   self.bot_id, bx, by, bz)
                    continue
                try:
                    open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                except Exception as e:
                    logger.warning("[%s] Open food shulker at (%d,%d,%d) error: %s",
                                   self.bot_id, bx, by, bz, e)
                    continue
                data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                container_id = (data or {}).get("container_id") or ""
                if not container_id:
                    await asyncio.sleep(1.0)
                    try:
                        open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                        data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                        container_id = (data or {}).get("container_id") or ""
                    except Exception:
                        container_id = ""
                    if not container_id:
                        logger.warning("[%s] 食物潜影盒(%d,%d,%d) 二次开箱仍失败", self.bot_id, bx, by, bz)
                        continue
                try:
                    wd = await self.mcp.withdraw_container_item(food_item, 64, container_id)
                except Exception as e:
                    logger.warning("[%s] Withdraw food %s from (%d,%d,%d) error: %s，尝试下一个坐标",
                                   self.bot_id, food_item, bx, by, bz, e)
                    try:
                        await self.mcp.close_container(container_id)
                    except Exception:
                        pass
                    continue
                try:
                    await self.mcp.close_container(container_id)
                except Exception:
                    pass
                if isinstance(wd, dict) and wd.get("success") is False:
                    continue
                taken = True
                logger.info("[%s] Food restock done: %s ×64 from (%d,%d,%d)",
                            self.bot_id, food_item, bx, by, bz)
                self._activity("info", f"取到猪排 ×64（{bx},{by},{bz}）")
                break
            if not taken:
                logger.warning("[%s] 所有食物潜影盒均未取到 %s", self.bot_id, food_item)

            # 4. 返回工作位置
            try:
                await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                await asyncio.sleep(1.5)
            except Exception:
                pass
            self._last_pos = None
            self.progress.state = "placing"
            return taken
        except Exception as e:
            logger.warning("[%s] Food restock failed: %s", self.bot_id, e)
            self.progress.state = "placing"
            return False

    async def _food_monitor_loop(self) -> None:
        """食物监控协程：每 2s 检查饱食度/血量，低于阈值时吃副手猪排。

        在 run 启动时创建，stop 时取消。吃食物期间不阻塞建造循环。
        """
        try:
            while not self._stopped:
                await asyncio.sleep(2)
                if self._stopped:
                    break
                try:
                    state = await self.mcp.get_player_state()
                    health = state.get("health") or 20
                    food = state.get("food") or 20
                    threshold_food = int(self._food_cfg.get("eat_threshold_food", 15))
                    threshold_health = int(self._food_cfg.get("eat_threshold_health", 15))

                    # 2026-08-14 溺水/坠落防护：血量持续下降且低（掉水淹死/虚空坠落）→
                    # 立即传送回建造点，避免死亡后复活到远处丢失位置
                    if health < 8 and self._last_health is not None and health < self._last_health:
                        self._activity("warn", f"血量持续下降（{self._last_health}→{health}），疑似溺水/坠落，传送回建造点")
                        await self._try_teleport_home("血量持续下降")
                        self._last_health = health
                        continue
                    self._last_health = health

                    if food < threshold_food or health < threshold_health:
                        self._activity("info", f"饱食度 {food}/血量 {health} 低，准备进食")
                        # 优先确保副手有食物
                        has_food = await self._ensure_food_offhand()
                        if not has_food:
                            logger.warning("[%s] 食物不足且补货失败（food=%d, health=%d）",
                                           self.bot_id, food, health)
                            continue
                        # 吃副手食物
                        try:
                            r = await self.mcp.consume_offhand()
                            if r.get("success"):
                                logger.info("[%s] Ate %s (food=%d→%d, health=%d)",
                                            self.bot_id,
                                            r.get("item", "?"),
                                            food, r.get("food", 20),
                                            r.get("health", 20))
                            else:
                                logger.warning("[%s] consume_offhand failed: %s",
                                               self.bot_id, r.get("error", "?"))
                        except Exception as e:
                            logger.warning("[%s] consume_offhand error: %s", self.bot_id, e)
                except Exception:
                    pass  # 单次检查失败不影响建造
        except asyncio.CancelledError:
            pass


# ──────────────────────────────────────────────
# MapArtCoordinator — orchestrator
# ──────────────────────────────────────────────

class MapArtCoordinator:
    """Orchestrates multi-bot map art construction.

    Lifecycle:
      1. start() → parse projection, partition regions, spawn BotBuildLoops
      2. Progress pushed every 2s via Socket.IO to room "build_{task_id}"
      3. pause() / resume() / stop() → fan out to all loops
      4. add_bot() / remove_bot() → dynamic region reassignment
    """

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        self.task_id = task_id
        self.projection = projection_data
        self.origin = (origin_x, origin_y, origin_z)
        self._loops: dict[str, BotBuildLoop] = {}
        self._started_at: float = 0.0
        self._progress_task: Optional[asyncio.Task] = None
        self._block_matrix: dict[tuple[int, int], str] = {}
        self._done_loops: set[str] = set()  # P1-10：正常完成的任务判定
        # 2026-08-14：区域未放完（failed）的 bot——任务级完成判定排除，置 failed
        self._failed_loops: set[str] = set()
        self._completion_notified: bool = False
        # P2-27：待接管区域队列（remove_bot 释放的未完成区域 → add_bot 分配）
        self._pending_regions: list[Region] = []
        # 2026-08-14：材料级潜影盒坐标 + 任务级三个传送指令（DB 加载，构造时读一次）
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = {}
        self._supply_config: dict = {}
        # 2026-08-14 模块A：食物配置 + 猪排潜影盒坐标（DB 加载）
        self._food_config: dict = {}
        self._food_boxes: list[tuple[int, int, int]] = []
        # 2026-08-14 终端：活动日志环形缓冲（最近 300 条，前端 join 时回放）
        self._activity_log: deque = deque(maxlen=300)
        self._load_supply_data()
        self._load_food_data()

    def _load_supply_data(self) -> None:
        """从 DB 加载任务的补货配置（任务级潜影盒 + 全局仓库合并 + 三个传送指令）。

        2026-08-14 三期：任务级 map_art_supply_boxes 优先；任务没配该材料时
        自动回退全局补货仓库（map_art_supply_warehouse）——用户在首页仓库设定的
        材料↔潜影盒映射，任何任务按需材料自动复用。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTask, MapArtSupplyBox, MapArtSupplyWarehouse
            import json as _json
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task and task.supply_config:
                    try:
                        d = _json.loads(task.supply_config)
                        if isinstance(d, dict):
                            self._supply_config = {k: d.get(k, "") for k in ("go", "save", "return", "return_fixed")}
                    except Exception:
                        pass
                # 任务级潜影盒
                task_boxes: dict[str, list[tuple[int, int, int]]] = {}
                rows = db.query(MapArtSupplyBox).filter(
                    MapArtSupplyBox.task_id == self.task_id
                ).order_by(MapArtSupplyBox.sort_order).all()
                for r in rows:
                    task_boxes.setdefault(r.item_id, []).append((r.x, r.y, r.z))
                # 全局仓库：任务没配的材料自动回退全局
                global_boxes: dict[str, list[tuple[int, int, int]]] = {}
                g_rows = db.query(MapArtSupplyWarehouse).all()
                for g in g_rows:
                    try:
                        boxes = _json.loads(g.boxes_json or "[]")
                        global_boxes[g.item_id] = [(int(b["x"]), int(b["y"]), int(b["z"])) for b in boxes if "x" in b]
                    except Exception:
                        continue
                # 合并：任务级优先，缺的用全局（建造时自动复用）
                merged: dict[str, list[tuple[int, int, int]]] = dict(global_boxes)
                for item_id, boxes in task_boxes.items():
                    merged[item_id] = boxes
                self._supply_boxes = merged
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load supply data failed: %s", self.task_id, e)

    def _load_food_data(self) -> None:
        """从 DB 加载食物配置 + 猪排潜影盒坐标（2026-08-14 模块A）。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTask, MapArtFoodBox
            import json as _json
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task and task.food_config:
                    try:
                        d = _json.loads(task.food_config)
                        if isinstance(d, dict):
                            self._food_config = d
                    except Exception:
                        pass
                # 食物潜影盒坐标
                rows = db.query(MapArtFoodBox).filter(
                    MapArtFoodBox.task_id == self.task_id
                ).order_by(MapArtFoodBox.sort_order).all()
                self._food_boxes = [(r.x, r.y, r.z) for r in rows]
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load food data failed: %s", self.task_id, e)

    # ── 活动日志（2026-08-14 终端）───────────────────────────────────

    def _on_loop_activity(self, bot_id: str, bot_name: str, level: str, message: str) -> None:
        """BotBuildLoop 活动日志回调：汇聚到缓冲 + 广播到前端实时日志终端。"""
        entry = {
            "task_id": self.task_id,
            "bot_id": bot_id,
            "bot_name": bot_name,
            "level": level,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._activity_log.append(entry)
        try:
            asyncio.create_task(sio.emit("build_log", entry, room=f"build_{self.task_id}"))
            logger.info("[%s] build_log emitted (level=%s): %s", bot_id, level, message)
        except Exception as e:
            logger.warning("[%s] build_log emit failed: %s", bot_id, e)

    def emit_log_history(self) -> None:
        """前端 join 房间时回放历史日志（同步方法，由 socket handler 调用）。"""
        if not self._activity_log:
            return
        try:
            asyncio.create_task(sio.emit(
                "build_log_history",
                {"task_id": self.task_id, "logs": list(self._activity_log)},
                room=f"build_{self.task_id}",
            ))
        except Exception:
            pass

    # ── Build 2D matrix from projection layers ──

    @classmethod
    def build_2d_matrix(cls, layers: dict[int, list[tuple[int, int, int, str]]]) -> dict[tuple[int, int], str]:
        """Flatten 3D layer blocks into a 2D (x, z) → block_id matrix.

        Map art is single-layer (y offset 0), so this is straightforward.
        """
        matrix: dict[tuple[int, int], str] = {}
        for y_offset, blocks in layers.items():
            for wx, wy, wz, block_id in blocks:
                matrix[(wx, wz)] = block_id
        return matrix

    # ── Lifecycle ─────────────────────────────

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]):
        """Start build with N bots.

        Args:
            bot_agents: {bot_id: (bot_name, AbstractBotAgent)}
        """
        self._started_at = time.monotonic()

        # Build 2D matrix
        layers = self.projection.get("layers", {})
        self._block_matrix = self.build_2d_matrix(layers)

        # Determine map size from projection
        size_x = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("x", 128)
        size_z = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("z", 128)

        n_bots = len(bot_agents)
        if n_bots == 0:
            logger.error("[%s] No bots available", self.task_id)
            return

        # Partition
        regions = partition_rectangular(size_x, size_z, n_bots)

        # 补给箱方案（开发文档 §补给策略）：每个区域北缘中点分配一个补给箱坐标
        supply_boxes = assign_supply_boxes(
            regions, self.origin[0], self.origin[1], self.origin[2],
        )

        # P2-15：建造开始前复位 bot 手动控制状态（移动控制台遗留的方向键/视角会与
        # pathfinder 并发抢控制 → 放置位置错乱）。MCC 无 set_control_state，用 hasattr 兼容。
        for bot_id, (_name, mcp) in bot_agents.items():
            try:
                if hasattr(mcp, "cancel_pathing"):
                    await mcp.cancel_pathing()
                if hasattr(mcp, "set_control_state"):
                    for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                        await mcp.set_control_state(ctrl, False)
            except Exception as e:
                logger.warning("[%s] Reset control state failed: %s", bot_id, e)

        # Spawn loops
        bot_ids = list(bot_agents.keys())
        for i, bot_id in enumerate(bot_ids):
            bot_name, mcp = bot_agents[bot_id]
            loop = BotBuildLoop(
                bot_id=bot_id,
                bot_name=bot_name,
                task_id=self.task_id,
                region=regions[i],
                block_matrix=self._block_matrix,
                origin_x=self.origin[0],
                origin_y=self.origin[1],
                origin_z=self.origin[2],
                mcp=mcp,
                supply_box=supply_boxes[i] if i < len(supply_boxes) else None,
                supply_boxes=self._supply_boxes,
                supply_config=self._supply_config,
                food_config=self._food_config,
                food_boxes=self._food_boxes,
                on_done=self._on_loop_done,
                on_activity=self._on_loop_activity,
            )
            self._loops[bot_id] = loop
            asyncio.create_task(loop.run())

        # Start progress push loop
        self._progress_task = asyncio.create_task(self._push_loop())

        # Emit initial map data
        await self._emit_map_init(bot_agents, regions, size_x, size_z)

        logger.info("[%s] Build started: %d bots, %d regions",
                     self.task_id, n_bots, len(regions))

    async def pause(self):
        await asyncio.gather(*(loop.pause() for loop in self._loops.values()))

    async def resume(self):
        await asyncio.gather(*(loop.resume() for loop in self._loops.values()))

    async def stop(self):
        await asyncio.gather(*(loop.stop() for loop in self._loops.values()))
        if self._progress_task:
            self._progress_task.cancel()

    # ── Dynamic bot assignment (P2-27) ─────────

    async def add_bot(self, bot_id: str, bot_name: str,
                      mcp: AbstractBotAgent) -> Optional[Region]:
        """Assign a pending (released/unfinished) region to a new bot.

        Returns the assigned Region on success, None if no region is pending
        (all regions already assigned or finished).
        """
        if not self._pending_regions:
            logger.warning("[%s] add_bot %s: no pending region to assign",
                           self.task_id, bot_id)
            return None
        region = self._pending_regions.pop(0)

        # 复位手动控制状态（同 start，防移动控制台遗留方向键与寻路抢控制）
        try:
            if hasattr(mcp, "cancel_pathing"):
                await mcp.cancel_pathing()
            if hasattr(mcp, "set_control_state"):
                for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                    await mcp.set_control_state(ctrl, False)
        except Exception as e:
            logger.warning("[%s] Reset control state for %s failed: %s",
                           self.task_id, bot_id, e)

        loop = BotBuildLoop(
            bot_id=bot_id,
            bot_name=bot_name,
            task_id=self.task_id,
            region=region,
            block_matrix=self._block_matrix,
            origin_x=self.origin[0],
            origin_y=self.origin[1],
            origin_z=self.origin[2],
            mcp=mcp,
            supply_box=None,  # 新 bot 走配置潜影盒 / EssentialsX 传送补货（补给箱已按原 bot 分配）
            supply_boxes=self._supply_boxes,
            supply_config=self._supply_config,
            food_config=self._food_config,
            food_boxes=self._food_boxes,
            on_done=self._on_loop_done,
            on_activity=self._on_loop_activity,
        )
        self._loops[bot_id] = loop
        asyncio.create_task(loop.run())
        logger.info("[%s] Bot %s took over region z[%d..%d]",
                    self.task_id, bot_id, region.z_start, region.z_end)
        return region

    async def remove_bot(self, bot_id: str) -> bool:
        """Stop a bot and release its unfinished region for reassignment.

        Returns True on success, False if the bot is not running in this task.
        """
        loop = self._loops.pop(bot_id, None)
        if not loop:
            logger.warning("[%s] remove_bot %s: not running in this task",
                           self.task_id, bot_id)
            return False
        await loop.stop()

    async def get_bot_inventory(self) -> list[dict]:
        """返回任务正在工作的每个 bot 的背包快照（前端 bot 背包面板轮询）。

        2026-08-14：物品 ID 统一归一化（snapshot type 无 minecraft: 前缀），
        前端按名称+数量展示。
        """
        results: list[dict] = []
        for bot_id, loop in self._loops.items():
            try:
                snap = await loop.mcp.get_inventory_snapshot(inventory_id=0)
                items = (snap.get("data", snap)).get("items", [])
                parsed: list[dict] = []
                for s in items:
                    item_id = BotBuildLoop._normalize_item_id(s.get("type", ""))
                    cnt = s.get("count", 0)
                    if item_id and cnt > 0:
                        parsed.append({"name": item_id, "count": cnt})
                results.append({
                    "bot_id": bot_id,
                    "bot_name": loop.bot_name,
                    "items": parsed,
                    "total_items": sum(i["count"] for i in parsed),
                })
            except Exception as e:
                logger.warning("[%s] inventory snapshot for %s failed: %s",
                               self.task_id, bot_id, e)
                results.append({"bot_id": bot_id, "bot_name": loop.bot_name,
                                "items": [], "total_items": 0})
        return results
        self._done_loops.discard(bot_id)
        # 已完成区域无需接管；未完成区域进入待接管队列
        if loop.progress.state != "completed":
            self._pending_regions.append(loop.region)
            logger.info("[%s] Bot %s removed, region z[%d..%d] released for takeover",
                        self.task_id, bot_id,
                        loop.region.z_start, loop.region.z_end)
        else:
            logger.info("[%s] Bot %s removed (region already completed)",
                        self.task_id, bot_id)
        return True

    # ── Progress & Socket.IO ──────────────────

    def _on_loop_done(self, bot_id: str) -> None:
        """P1-10：单个 bot 区域结束 → 全部结束后判定任务 completed / failed（DB + 推送）。"""
        loop = self._loops.get(bot_id)
        self._done_loops.add(bot_id)
        # 2026-08-14：区域未放完（补货/放置失败）→ 记入失败集合，完成判定排除
        if loop is not None and loop.progress.state == "failed":
            self._failed_loops.add(bot_id)
        if self._completion_notified or not self._loops:
            return
        if len(self._done_loops) >= len(self._loops):
            self._completion_notified = True
            if self._failed_loops:
                # 有 bot 区域未放完 → 任务置 failed（不再误报 completed）
                logger.warning("[%s] Task marked FAILED: %d/%d regions incomplete",
                               self.task_id, len(self._failed_loops), len(self._loops))
                # 停止尚未结束的其余 loop
                for bid, lp in self._loops.items():
                    if bid not in self._done_loops:
                        try:
                            asyncio.create_task(lp.stop())
                        except Exception:
                            pass
                try:
                    from vmtools_next.data.db import get_session_factory, sio as _sio
                    from vmtools_next.data.models.build_map_art import MapArtTask
                    Session = get_session_factory()
                    db = Session()
                    try:
                        # 2026-08-14 修复：failed 分支必须局部导入 datetime——
                        # 同函数 completed 分支有局部 import，整个函数内 datetime 被
                        # 视为局部变量，此处不导入会 UnboundLocalError（persist failed）。
                        from datetime import datetime, timezone
                        task = db.query(MapArtTask).filter(
                            MapArtTask.task_id == self.task_id).first()
                        if task and task.status == "running":
                            task.status = "failed"
                            task.error_message = (
                                f"{len(self._failed_loops)} 个 Bot 区域未完成"
                                f"（补货或放置失败，实际放置 {task.placed_blocks or 0}/{task.total_blocks or 0} 方块）")
                            task.completed_at = datetime.now(timezone.utc)
                            db.commit()
                    finally:
                        db.close()
                    asyncio.create_task(_sio.emit(
                        "build_progress",
                        {"task_id": self.task_id, "status": "failed",
                         "error_message": task.error_message},
                        room=f"build_{self.task_id}",
                    ))
                    try:
                        from vmtools_next.core.task_scheduler import get_task_scheduler
                        _sched = get_task_scheduler()
                        if _sched:
                            asyncio.create_task(_sched.broadcast_queue())
                            asyncio.create_task(_sched.schedule_once())
                    except Exception as _sched_err:
                        logger.warning("[%s] Scheduler notify failed: %s",
                                       self.task_id, _sched_err)
                except Exception as e:
                    logger.warning("[%s] Failure persist failed: %s", self.task_id, e)
                return
            logger.info("[%s] All regions complete, marking task completed", self.task_id)
            try:
                from vmtools_next.data.db import get_session_factory, sio as _sio
                from vmtools_next.data.models.build_map_art import MapArtTask
                Session = get_session_factory()
                db = Session()
                try:
                    from datetime import datetime, timezone
                    task = db.query(MapArtTask).filter(
                        MapArtTask.task_id == self.task_id).first()
                    if task and task.status == "running":
                        task.status = "completed"
                        task.completed_at = datetime.now(timezone.utc)
                        db.commit()
                finally:
                    db.close()
                asyncio.create_task(_sio.emit(
                    "build_progress",
                    {"task_id": self.task_id, "status": "completed"},
                    room=f"build_{self.task_id}",
                ))
                # 2026-08-12（实施计划阶段 2）：任务完成 → 广播队列变化 +
                # 触发调度器立即启动下一个排队任务（不等 2s 轮询）
                try:
                    from vmtools_next.core.task_scheduler import get_task_scheduler
                    _sched = get_task_scheduler()
                    if _sched:
                        asyncio.create_task(_sched.broadcast_queue())
                        asyncio.create_task(_sched.schedule_once())
                except Exception as _sched_err:
                    logger.warning("[%s] Scheduler notify failed: %s",
                                   self.task_id, _sched_err)
            except Exception as e:
                logger.warning("[%s] Completion persist failed: %s", self.task_id, e)

    async def _push_loop(self):
        """Every 2 seconds, aggregate progress and push via Socket.IO."""
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self._push_progress()
                except Exception as e:
                    # 单次推送失败不退出循环（sio.emit 可能因无客户端/序列化失败）
                    logger.warning("[%s] Push progress failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _push_progress(self):
        state = self._aggregate()
        room = f"build_{self.task_id}"
        await sio.emit("build_progress", state.__dict__, room=room)

        # Bot positions（2026-08-14 模块E：优先用真实位置 = mcp.last_status（status 事件
        # 每 5s 推送 position/health/food），fallback _last_pos 寻路目标；补 health/food
        # 供前端 tooltip 展示）
        bot_data = []
        for bid, loop in self._loops.items():
            lp = loop._last_pos
            real_pos = None
            health = None
            food = None
            try:
                st = getattr(loop.mcp, "last_status", None) or {}
                if isinstance(st, dict) and st.get("position"):
                    real_pos = {
                        "x": st["position"].get("x"),
                        "y": st["position"].get("y"),
                        "z": st["position"].get("z"),
                    }
                health = st.get("health")
                food = st.get("food")
            except Exception:
                pass
            # 真实位置优先；没有则回退寻路目标
            pos = real_pos or ({"x": lp[0], "y": lp[1], "z": lp[2]} if lp else None)
            bot_data.append({
                "bot_id": bid,
                "bot_name": loop.bot_name,
                "state": loop.progress.state,
                "position": pos,
                "health": health,
                "food": food,
                "region": {
                    # 2026-08-16 审查修复：region 为相对坐标，画布按世界坐标渲染 → 转世界
                    "x_start": loop.region.x_start + self.origin[0],
                    "x_end": loop.region.x_end + self.origin[0],
                    "z_start": loop.region.z_start + self.origin[2],
                    "z_end": loop.region.z_end + self.origin[2],
                },
                "blocks_placed": loop.progress.blocks_placed,
                "blocks_total": loop.progress.blocks_total,
                "current_row": loop.progress.current_row,
                "place_rate": loop.progress.place_rate,
            })
        await sio.emit("build_bot_status", {"task_id": self.task_id, "bots": bot_data}, room=room)

    async def _emit_map_init(self, bot_agents, regions, size_x, size_z):
        """Push initial 3D map data to connected clients."""
        room = f"build_{self.task_id}"
        blocks = [
            {"x": x, "y": self.origin[1], "z": z, "expected": bid, "placed": False}
            for (x, z), bid in self._block_matrix.items()
        ]
        bots = [
            {
                "bot_id": bid,
                "name": name,
                # 稳定颜色（2026-08-14）：改用 crc32——Python hash() 对字符串每次进程随机，
                # 重启后颜色漂移；crc32 保证同一 bot 永远同色（前端画布标记同算法）
                "color": f"#{zlib.crc32(bid.encode()) & 0xFFFFFF:06x}",
                "region": {
                    # 2026-08-16 审查修复：region 为相对坐标，画布按世界坐标渲染 → 转世界
                    "x_start": r.x_start + self.origin[0], "x_end": r.x_end + self.origin[0],
                    "z_start": r.z_start + self.origin[2], "z_end": r.z_end + self.origin[2],
                },
                "state": "idle",
            }
            for (bid, (name, _)), r in zip(bot_agents.items(), regions)
        ]
        await sio.emit("build_map_init", {
            "task_id": self.task_id,
            "blocks": blocks,
            "bots": bots,
            "origin": {"x": self.origin[0], "y": self.origin[1], "z": self.origin[2]},
            "size": {"x": size_x, "z": size_z},
        }, room=room)

    def _aggregate(self) -> MapArtBuildState:
        total = sum(l.progress.blocks_total for l in self._loops.values())
        placed = sum(l.progress.blocks_placed for l in self._loops.values())
        elapsed = time.monotonic() - self._started_at
        rate = placed / (elapsed / 60) if elapsed > 0 else 0
        remaining = total - placed
        eta = (remaining / rate) * 60 if rate > 0 else 0
        # P1-10：全部区域完成 → 任务级 status=completed（不再硬编码 running）；
        # 2026-08-14：有区域 failed（未放完）→ status=failed；
        # 任一 loop waiting（pause 置 waiting）→ status=paused（防 socket 推送
        # 覆盖前端暂停态，导致暂停后按钮消失/错乱）
        if self._failed_loops:
            status = "failed"
        elif self._done_loops and len(self._done_loops) >= len(self._loops) and self._loops:
            status = "completed"
        elif any(l.progress.state == "waiting" for l in self._loops.values()):
            status = "paused"
        else:
            status = "running"

        bots = [{
            "bot_id": l.bot_id,
            "name": l.bot_name,
            "state": l.progress.state,
            "region": {
                "x_start": l.region.x_start, "x_end": l.region.x_end,
                "z_start": l.region.z_start, "z_end": l.region.z_end,
            },
            "placed": l.progress.blocks_placed,
            "total": l.progress.blocks_total,
            "current_row": l.progress.current_row,
            "rate": l.progress.place_rate,
        } for l in self._loops.values()]

        return MapArtBuildState(
            task_id=self.task_id,
            status=status,
            total_blocks=total,
            placed_blocks=placed,
            bots=bots,
            materials={},  # populated by API layer
            elapsed_sec=elapsed,
            eta_sec=eta,
        )


# ──────────────────────────────────────────────
# Global registry of active coordinators
# ──────────────────────────────────────────────

_active_coordinators: dict[str, MapArtCoordinator] = {}


def get_coordinator(task_id: str) -> Optional[MapArtCoordinator]:
    return _active_coordinators.get(task_id)


def register_coordinator(task_id: str, coordinator: MapArtCoordinator):
    _active_coordinators[task_id] = coordinator


def unregister_coordinator(task_id: str):
    _active_coordinators.pop(task_id, None)
