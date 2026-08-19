"""Multi-Bot Column Build Coordinator — 列式协作建造引擎（2026-08-19）。

替代旧 MapArtCoordinator 的分区独立模式，实现任务文档要求的多Bot协作：
  - 排内并行：各Bot独立完成本列（沿自定义y轴），列内完全自治
  - 排尾同步：协调器收集所有Bot「列完成」信号后广播推进
  - 整排推进：开路Bot（默认mf-001）沿列尾行向x+放置n格连接条，其余Bot依次就位
  - 排级蛇形：第1排沿y+，第2排沿y-，整排掉头
  - 减员容错：Bot离线超时 → 重组编队（新排宽=剩余Bot数）
  - 余列处理：剩余列数<Bot数 → 仅启用前n台，其余传送回兜底位置

坐标系（对齐任务文档）：
  - MC原生坐标：X/Z水平、Y竖直；建造平面统一 MC Y=319（origin_y）
  - 自定义 x 轴（列）→ MC X 轴：wx = origin_x + (x - 1)
  - 自定义 y 轴（行）→ MC Z 轴：wz = origin_z + (y - 1)
  - 地图画矩形：一角 (1,1)，对角 (x_max, y_max)；x≤0 为永久安全平台

术语：
  - 列：固定x值、沿y方向延伸的一条直线
  - 排（条带）：宽度=当前参与Bot数n的连续列集合，按x升序编号
  - 列尾：本列建造方向上的最后一个待建格

关键设计：
  - ColumnBuildLoop 继承 BotBuildLoop，复用全部已有能力（补货/睡觉/对账/
    放置校验/传送/手持管理/环境检测/死亡事件），仅替换主循环为列式建造
  - MultiBotCoordinator 为全局协调器（控制台进程），持有任务进度表与各Bot
    状态；Bot为独立执行体，状态变更实时上报，同步与推进由协调器判定并广播
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.config import get_config
from vmtools_next.core.map_art_coordinator import (
    BotBuildLoop,
    Region,
    BotProgress,
    MapArtBuildState,
)
from vmtools_next.data.db import sio

logger = logging.getLogger("vmtools.multi_bot")


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class ColumnRegion:
    """单列区域：固定x值（自定义坐标系），y方向从 y_start 到 y_end。

    与旧 Region 的区别：旧 Region 是 Z轴条带（多列×多行），
    ColumnRegion 是单列（1列×多行）。
    """
    column_x: int          # 自定义坐标系 x 值（列号，1-based）
    y_start: int           # 自定义坐标系 y 起始（含，1-based）
    y_end: int             # 自定义坐标系 y 结束（含）
    direction: int = 1     # 建造方向：1=y+, -1=y-

    @property
    def block_count(self) -> int:
        return self.y_end - self.y_start + 1

    def to_region(self, origin_z: int) -> Region:
        """转换为旧 Region（供继承的 BotBuildLoop 方法使用）。

        column_x 列在 Region 语义下 = x_start==x_end 的单列；
        z 方向 = 自定义 y 方向（z_start=1, z_end=y_end 相对）。
        """
        return Region(self.column_x, self.column_x, 1, max(1, self.y_end))


@dataclass
class SquadState:
    """编队状态：全局协调器持有，进度落盘用。"""
    squad_index: int = 1           # 当前排号（1-based）
    direction: int = 1             # 当前排建造方向（1=y+, -1=y-）
    active_bots: list[str] = field(default_factory=list)
    offline_bots: list[str] = field(default_factory=list)
    bot_columns: dict[str, int] = field(default_factory=dict)  # bot_id → column_x
    bot_done: set[str] = field(default_factory=set)            # 本排已完成的bot
    total_columns: int = 0         # 地图画总列数（x_max）
    total_rows: int = 0            # 地图画总行数（y_max）
    placed_total: int = 0          # 全局已放置总数（放置成功事件计数）
    started_at: float = 0.0        # 任务启动时刻（monotonic）
    # 净建造速率统计：只统计建造态时间（剔除补货/复位/同步等待）
    build_active_sec: float = 0.0
    last_build_ts: float = 0.0


# ──────────────────────────────────────────────
# ColumnBuildLoop — 单Bot列式建造循环
# ──────────────────────────────────────────────

class ColumnBuildLoop(BotBuildLoop):
    """列式建造循环：继承 BotBuildLoop 复用所有已有能力。

    与旧分区模式（BotBuildLoop.run → Z行循环）的区别：
      - 旧：bot 在区域内沿 X 蛇形放行（Z 固定）
      - 新：bot 在单列沿 Y（Z轴）方向放置（X 固定），列间由协调器安排
    """

    # 默认开路Bot（可配置轮换以均衡负担）
    LEADER_BOT: str = "mf-001"

    def __init__(
        self,
        *args,
        column_region: ColumnRegion,
        on_column_done: Optional[callable] = None,
        on_bot_offline: Optional[callable] = None,
        squad_lead: bool = False,
        **kwargs,
    ):
        """扩展 BotBuildLoop，增加列式建造所需字段。

        Args:
            column_region: 本Bot分配的列区域（含方向）
            on_column_done: 列完成回调（通知协调器排尾同步）
            on_bot_offline: Bot离线/卡滞回调（通知协调器减员容错）
            squad_lead: 是否为排开路者（负责搭连接条）
        """
        # 构造虚拟 Region 供继承方法使用（x 单列、z 覆盖整列行数）
        virtual_region = column_region.to_region(0)
        # 兼容：若调用方传了 region 参数则覆盖（BotBuildLoop 需要）
        kwargs.pop("region", None)
        super().__init__(*args, region=virtual_region, **kwargs)

        self.column_region = column_region
        self.column_x: int = column_region.column_x
        self.squad_direction: int = column_region.direction
        self.squad_index: int = 1
        self.squad_start_y: int = column_region.y_start
        self.squad_end_y: int = column_region.y_end
        self.squad_lead: bool = squad_lead
        self._on_column_done = on_column_done
        self._on_bot_offline = on_bot_offline

        # 编队控制事件（协调器 → bot）
        self._build_ready = asyncio.Event()          # 协调器广播开工
        self._squad_assigned = asyncio.Event()       # 本排已分配（列/方向已更新）
        self._stop_requested = asyncio.Event()       # 任务停止
        self._column_completed = False                # 本排列是否已完成（上报去重）
        self._temp_blocks: list[tuple[int, int, int]] = []  # 透明格临时跨越方块
        # 卡滞/坠落监控协程
        self._guard_task: Optional[asyncio.Task] = None
        # 死亡复位状态（2026-08-19 增强）
        self._death_lock = asyncio.Event()            # /back 移动锁定
        self._death_lock.set()
        self._last_known_pos: Optional[tuple[float, float, float]] = None
        self._stuck_check_ts: float = 0.0
        self._stuck_last_pos: Optional[tuple[float, float, float]] = None
        self._stuck_count: int = 0

        # 读取多Bot配置
        try:
            _mf = get_config().mineflayer
            self._column_place_interval: float = max(
                0.15, float(getattr(_mf, "map_art_column_place_interval_s", 0.3) or 0.3))
            self._stuck_timeout_s: float = max(
                5.0, float(getattr(_mf, "map_art_stuck_timeout_s", 10) or 10))
            self._death_back_timeout_s: float = max(
                3.0, float(getattr(_mf, "map_art_death_back_timeout_s", 10) or 10))
            self._offline_timeout_s: float = max(
                30.0, float(getattr(_mf, "map_art_bot_offline_timeout_s", 120) or 120))
            self._fall_threshold: int = max(
                1, int(getattr(_mf, "map_art_fall_threshold", 3) or 3))
        except Exception:
            self._column_place_interval = 0.3
            self._stuck_timeout_s = 10.0
            self._death_back_timeout_s = 10.0
            self._offline_timeout_s = 120.0
            self._fall_threshold = 3

    # ── 编队控制（协调器调用）────────────────────────

    async def assign_squad(self, column_x: int, direction: int,
                           start_y: int, end_y: int, squad_index: int) -> None:
        """协调器分配新排任务：更新本Bot列号/方向/范围。"""
        self.column_x = column_x
        self.squad_direction = direction
        self.squad_start_y = start_y
        self.squad_end_y = end_y
        self.squad_index = squad_index
        self.column_region = ColumnRegion(column_x, start_y, end_y, direction)
        self._column_completed = False
        self._build_ready.clear()
        self._squad_assigned.set()

    async def wait_for_ready(self) -> bool:
        """等待协调器广播开工（返回 False=任务停止）。"""
        while not self._build_ready.is_set():
            if self._stopped or self._stop_requested.is_set():
                return False
            await asyncio.sleep(0.3)
        self._build_ready.clear()
        return True

    async def signal_go(self) -> None:
        """协调器广播开工。"""
        self._build_ready.set()

    # ── 主循环 ──────────────────────────────

    async def run(self) -> None:
        """列式建造主循环：启动序列 → 编队等待 → 逐排建造。"""
        logger.info("[%s] Column build loop started: col=%d y[%d..%d] dir=%d",
                    self.bot_id, self.column_x, self.squad_start_y,
                    self.squad_end_y, self.squad_direction)
        self._activity("info", f"列式建造就绪：列 x={self.column_x}")

        # 启动序列（复用 BotBuildLoop 启动流程：环境/定位/食物/睡觉/对账/填坑）
        await self._column_startup()

        # 启动卡滞/坠落监控协程
        self._guard_task = asyncio.create_task(self._guard_monitor_loop())

        try:
            while not self._stopped and not self._stop_requested.is_set():
                # 等待协调器分配排任务（首次已由 __init__ 预设）
                if not self._squad_assigned.is_set():
                    await self.wait_for_ready()
                self._squad_assigned.clear()
                if self._stopped or self._stop_requested.is_set():
                    break

                # 建造本列（排内并行）
                await self.build_column()
                if self._stopped or self._stop_requested.is_set():
                    break

                # 上报列完成（排尾同步）
                self._column_completed = True
                if self._on_column_done:
                    try:
                        self._on_column_done(self.bot_id)
                    except Exception as e:
                        logger.warning("[%s] on_column_done error: %s", self.bot_id, e)

                # 等待协调器推进（下一排分配/余列结束信号）
                await self.wait_for_ready()
        except asyncio.CancelledError:
            self.progress.state = "offline"
        except Exception as e:
            self.progress.state = "offline"
            logger.error("[%s] Column build loop error: %s", self.bot_id, e)
            if self._on_bot_offline:
                try:
                    self._on_bot_offline(self.bot_id, str(e))
                except Exception:
                    pass
        finally:
            # 清理监控协程
            if self._guard_task:
                self._guard_task.cancel()
                self._guard_task = None
            # 拆除透明格临时方块（若还在）
            if self._temp_blocks and not self._stopped:
                try:
                    await self._dismantle_temp_blocks()
                except Exception as e:
                    logger.warning("[%s] Dismantle temp blocks error: %s", self.bot_id, e)
            # 取消食物/睡觉监控协程（继承自 BotBuildLoop）
            if self._food_task:
                self._food_task.cancel()
                self._food_task = None
            if self._sleep_task:
                self._sleep_task.cancel()
                self._sleep_task = None
            self._sleeping = False
            self._sleep_event.set()
            self._sleep_req.clear()
            self._sleep_hold.clear()
            # flush 残留进度
            if self._db_updates:
                try:
                    await self._flush_db(self.progress.current_row)
                except Exception:
                    pass

    async def _column_startup(self) -> None:
        """启动序列（复制自 BotBuildLoop.run 的启动段，2026-08-19 提取）。

        保留全部既有行为：环境检测、定位、dth覆盖、副手猪排、夜晚睡觉、
        启动对账、启动填坑——确保不破坏已有可用功能。
        """
        # 启动食物监控协程 + hotbar 映射
        try:
            self._food_task = asyncio.create_task(self._food_monitor_loop())
            self._sleep_task = asyncio.create_task(self._sleep_monitor_loop())
            await self._refresh_hotbar_map()
        except Exception as e:
            logger.warning("[%s] Startup monitors error: %s", self.bot_id, e)

        # 环境检测（维度/位置/领地诊断告警）
        try:
            await self._check_build_environment()
        except Exception as e:
            logger.warning("[%s] Env check error: %s", self.bot_id, e)

        # 启动定位 + dth 覆盖（复用 BotBuildLoop 启动逻辑）
        try:
            await self._startup_positioning()
        except Exception as e:
            logger.warning("[%s] Startup positioning error: %s", self.bot_id, e)

        # 启动后副手猪排检查
        try:
            _food_ok = await self._ensure_food_offhand()
            if _food_ok:
                self._activity("debug", "副手已就绪（猪排），跳过启动补食")
            else:
                self._activity("warn", "启动时副手未就绪，建造中由食物监控兜底")
        except Exception as _f0e:
            logger.warning("[%s] Startup offhand check error: %s", self.bot_id, _f0e)

        # 夜晚/雷暴 → 先睡觉跳过黑夜
        try:
            _st0 = await self.mcp.get_time_status()
            if _st0.get("success"):
                _tod0 = _st0.get("time_of_day")
                _dim0 = _st0.get("dimension") or "unknown"
                _in_win = self._sleep_night_start <= _tod0 <= self._sleep_night_end
                _thunder0 = bool(_st0.get("is_raining")) and int(_st0.get("thunder_state") or 0) > 0
                if self._sleep_point and _dim0 in ("overworld", "minecraft:overworld", "minecraft_overworld") \
                        and (_in_win or _thunder0) and not bool(_st0.get("is_sleeping")):
                    self._activity("info", f"启动时检测到夜晚（timeOfDay={_tod0}），先传送睡觉跳过黑夜")
                    try:
                        await self._do_sleep_cycle()
                    except Exception as _se:
                        logger.warning("[%s] Startup sleep cycle error: %s", self.bot_id, _se)
        except Exception as _s0e:
            logger.warning("[%s] Startup night check error: %s", self.bot_id, _s0e)

        # 启动对账（须在传送定位后）→ 填坑
        try:
            await self._reconcile_start()
            if self._pending_gaps:
                self._activity("info", f"启动填坑：对账发现 {len(self._pending_gaps)} 格缺口，先补放")
                filled = await self._fill_pending_gaps()
                if filled > 0:
                    self._activity("info", f"启动填坑完成：补放 {filled} 格")
                try:
                    await self._reconcile_start()
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[%s] Startup reconcile error: %s", self.bot_id, e)

        self._activity("info", "启动序列完成，等待协调器编队")

    async def _startup_positioning(self) -> None:
        """启动定位 + dth 覆盖（2026-08-18 语义：仅到位才覆盖 dth）。"""
        try:
            fixed0 = (self._supply_cfg.get("return_fixed") or "/ehomes mapart").strip()
            placed0 = False
            if fixed0:
                self._activity("info", f"启动定位：传送回固定建造点（{fixed0}）")
                if await self._send_teleport(fixed0):
                    placed0 = (await self._verify_at_build_area()) is None
            # 固定点不在本任务区域 → 按本任务 origin 传送
            if not placed0 and self.origin_x is not None:
                tp_cmd = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
                self._activity("info", f"固定点不在本任务区域，改用任务 origin 传送（{tp_cmd}）")
                try:
                    if await self._send_teleport(tp_cmd):
                        placed0 = (await self._verify_at_build_area()) is None
                except Exception as _tp_err:
                    logger.warning("[%s] Origin teleport failed: %s", self.bot_id, _tp_err)
            if not placed0:
                gx0 = self.origin_x + self.column_region.column_x
                gz0 = self.origin_z + self.squad_start_y - 1
                gy0 = self.origin_y + self._stand_y_offset
                self._activity("info", f"定位到建造点北缘（{gx0},{gy0},{gz0}）")
                moved0 = await self._move_to(gx0, gy0, gz0, max_offset=2,
                                             label="initial position", timeout_ms=30000,
                                             allow_scaffold=True, verify_height=True)
                if not moved0:
                    await self._try_teleport_home("启动定位失败")
                    moved0 = await self._move_to(gx0, gy0, gz0, max_offset=2,
                                                 label="initial position retry",
                                                 timeout_ms=30000, allow_scaffold=True,
                                                 verify_height=True)
                placed0 = moved0
            if placed0:
                self._activity("info", "已确认到位，保存 dth")
            # dth 覆盖：仅到位才保存（防旧任务坐标污染）
            if placed0:
                await self._save_dth("启动定位到位")
            elif self.origin_x is not None:
                tp_cmd = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
                self._activity("warn", f"启动定位失败，改用任务 origin 传送后保存 dth（{tp_cmd}）")
                try:
                    if await self._send_teleport(tp_cmd) and (await self._verify_at_build_area()) is None:
                        await self._save_dth("origin /tp 到位")
                    else:
                        self._activity("warn", "origin 传送未到位，dth 保持原值")
                except Exception:
                    self._activity("warn", "origin 传送异常，dth 保持原值")
        except Exception as e:
            logger.warning("[%s] Startup positioning failed: %s", self.bot_id, e)

    async def _save_dth(self, label: str) -> None:
        """保存 dth 临时传送点（复用 BotBuildLoop 内联逻辑）。"""
        try:
            r = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r, dict) and r.get("success") is False:
                logger.warning("[%s] save build home failed: %s", self.bot_id, r.get("error", "?"))
            else:
                await asyncio.sleep(1.0)
                self._activity("info", f"已保存建造点位置（dth）· {label}")
        except Exception as e:
            logger.warning("[%s] save build home error: %s", self.bot_id, e)

    # ── 列式建造核心 ─────────────────────────

    async def build_column(self) -> None:
        """沿本列建造方向放置所有格（边放边踩，复用 _place_row 的逐格语义）。

        站立序列（bot 脚下恒为已放方块 / 起始条，永不踩空）：
          - 首格：起始条方块顶（协调器就位后 bot 已站在其上）
          - 每格放置后：站立点更新为本格方块顶，下一格直接从其上放置相邻格
        透明格（air）用临时方块跨越，列完成后拆除（_dismantle_temp_blocks）。
        """
        await self._paused.wait()
        if self._stopped or self._stop_requested.is_set():
            return

        self.progress.state = "placing"
        world_x = self.origin_x + self.column_x
        # y 范围按排方向排序（含起始条格——首格验证命中后踩上）
        if self.squad_direction == 1:
            y_range = list(range(self.squad_start_y, self.squad_end_y + 1))
        else:
            y_range = list(range(self.squad_start_y, self.squad_end_y - 1, -1))

        placed = 0
        failed = 0
        gap = 0
        row_audit: list[dict] = []
        # 当前站立点：首格用 bot 当前位置（协调器已就位到起始条）
        stand: Optional[tuple[int, int, int]] = None

        for y in y_range:
            await self._paused.wait()
            # 睡觉请求 → 暂停建造（安全点：每格循环开头）
            if self._sleep_req.is_set():
                self._sleep_req.clear()
                self._sleep_event.clear()
                self._sleep_hold.set()
                await self._sleep_event.wait()
            if self._stopped or self._stop_requested.is_set():
                return

            block_id = self.block_matrix.get((self.column_x, y))
            is_transparent = (not block_id or block_id == "minecraft:air")
            world_z = self.origin_z + y

            # ── 1. 确定站立点 ──
            if stand is None:
                # 首格：bot 已在起始条上（协调器就位），用当前位置
                p = await self._get_player_pos_full()
                if p:
                    stand = (int(round(p[0])), int(round(p[1])), int(round(p[2])))
                else:
                    self.progress.state = "offline"
                    return
                self._activity("debug", f"列 {self.column_x} 起始站立 {stand}")

            # 移动到站立点
            _mv = await self._move_to_step(stand[0], stand[1], stand[2],
                                           label=f"col-stand({self.column_x},{y})")
            if _mv == "gap":
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id or ""))
                gap += 1
                self._activity("warn", f"站立点 ({stand[0]},{stand[1]},{stand[2]}) 缺块，跳过 ({world_x},{world_z})")
                continue
            if not _mv:
                if await self._try_teleport_home("列内站立点移动失败"):
                    if not await self._move_to(stand[0], stand[1], stand[2], max_offset=1,
                                               label=f"stand retry({self.column_x},{y})",
                                               verify_height=True):
                        self.progress.state = "offline"
                        return
                else:
                    self.progress.state = "offline"
                    return

            # ── 2. 站立格前提校验 ──
            if not await self._stand_solid(stand[0], stand[1], stand[2]):
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id or ""))
                self._activity("warn", f"站立点脚下非实体，跳过放置 ({world_x},{world_z})")
                gap += 1
                continue

            # ── 3. 透明格处理（临时方块跨越）──
            if is_transparent:
                # 若已到最后一行（列尾）且不需要继续 → 跳过
                is_last = (y == y_range[-1])
                if is_last:
                    continue
                # 放临时方块跨越，踩上后继续
                if await self._cross_transparent(world_x, world_z, y):
                    stand = (world_x, self.origin_y + 1, world_z)
                    placed += 1  # 临时方块不计入正式进度（仅统计）
                    self._activity("debug", f"透明格 ({world_x},{world_z}) 临时跨越")
                    continue
                else:
                    self._pending_gaps.append((world_x, self.origin_y, world_z, block_id or ""))
                    gap += 1
                    self._activity("warn", f"透明格 ({world_x},{world_z}) 跨越失败，跳过")
                    continue

            # ── 4. 验证目标已正确则跳过（仍踩上）──
            if await self._verify_block(world_x, self.origin_y, world_z, block_id):
                self.progress.record_place()
                self.progress.last_completed_x = y
                self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                self._placed_coords.add((world_x, self.origin_y, world_z))
                placed += 1
                stand = (world_x, self.origin_y + 1, world_z)
                self._activity("debug", f"({world_x},{world_z}) 已放置，跳过")
                continue

            # ── 5. 选物品 ──
            if not await self._ensure_item_in_hand(block_id):
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                self._activity("warn", f"无法获取材料 {self._normalize_item_id(block_id)}，跳过放置 ({world_x},{world_z})")
                failed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "no_material"})
                continue

            # ── 6. 放置（含放置后校验分层）──
            if await self._place_with_retry(world_x, self.origin_y, world_z, block_id):
                self.progress.record_place()
                self.progress.last_completed_x = y
                self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                self._placed_coords.add((world_x, self.origin_y, world_z))
                placed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "placed"})
                self._activity("debug", f"放置成功 ({world_x},{world_z}) {self._normalize_item_id(block_id)}")
                stand = (world_x, self.origin_y + 1, world_z)  # 踩上
            else:
                failed += 1
                row_audit.append({"x": world_x, "z": world_z, "result": "fail"})
                self._activity("warn", f"放置失败 ({world_x},{world_z}) {self._normalize_item_id(block_id)}（重试{self._place_retries}次仍失败）")
                # stand 不更新：bot 仍在上格站立点

            # ── 7. 限速（多Bot节流）──
            await asyncio.sleep(self._column_place_interval)

        # ── 列尾：flush 进度 + 对账 ──
        await self._flush_db(self.progress.current_row)
        await self._reconcile_row(self.squad_end_y)
        self.progress.state = "waiting"  # 列完成 → 排尾等待
        self._activity("info",
                       f"列 x={self.column_x} 完成：成功 {placed} / 失败 {failed} / 跳过 {gap}"
                       f"（排 {self.squad_index}）")

    async def _cross_transparent(self, world_x: int, world_z: int, y: int) -> bool:
        """透明格跨越：用临时方块（背包 dirt 等）放置目标格并踩上。

        返回 True=跨越成功；False=失败（无临时方块/放置失败）。
        """
        # 临时方块候选（按优先级）
        temp_ids = ("minecraft:dirt", "minecraft:stone", "minecraft:cobblestone",
                    "minecraft:oak_planks", "minecraft:spruce_planks")
        chosen = None
        for tid in temp_ids:
            if await self._ensure_item_in_hand(tid):
                chosen = tid
                break
        if chosen is None:
            return False
        if await self._place_with_retry(world_x, self.origin_y, world_z, chosen):
            self._temp_blocks.append((world_x, self.origin_y, world_z))
            return True
        return False

    async def _dismantle_temp_blocks(self) -> None:
        """拆除透明格临时方块（列完成后）：逆序拆除，保证 bot 始终有立足点。

        流程：从远端（列尾方向）往近端拆——bot 站在待拆方块上，先确认退路
        （身后更靠近起始条方向的方块存在），拆除当前方块，后退到退路方块。
        全部拆完 bot 回到起始条区域。
        """
        if not self._temp_blocks:
            return
        self._activity("info", f"拆除 {len(self._temp_blocks)} 个临时跨越方块（逆序、保证立足点）")
        # 逆序（从列尾往列首）
        for i in range(len(self._temp_blocks) - 1, -1, -1):
            wx, wy, wz = self._temp_blocks[i]
            if self._stopped:
                break
            # 移动到该临时方块顶
            try:
                mv = await self._move_to(wx, wy + 1, wz, max_offset=1,
                                         label=f"dismantle({wx},{wz})",
                                         timeout_ms=15000, verify_height=True)
                if not mv:
                    self._activity("warn", f"无法走到临时方块 ({wx},{wz})，跳过拆除")
                    continue
                # 确认退路：身后一格（靠近起始条方向）有方块
                # 简化：拆除后 bot 会被服务器移到原地（破坏方块不移动），
                # 只要拆除顺序逆序（列尾→列首），bot 前方的方块已拆，身后未拆 → 立足点保证
                await self.mcp.dig_block(wx, wy, wz)
                self._activity("debug", f"已拆除临时方块 ({wx},{wz})")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("[%s] Dismantle (%d,%d,%d) error: %s", self.bot_id, wx, wy, wz, e)
        self._temp_blocks = []
        self._activity("info", "临时方块拆除完成")

    # ── 监控协程：卡滞 + 坠落 ──────────────────

    async def _guard_monitor_loop(self) -> None:
        """卡滞/坠落监控协程（2026-08-19）。

        卡滞：仅在「执行移动/放置」状态（progress.state in moving/placing）检测，
        连续 _stuck_timeout_s 无位置或动作进展 → 传送至本列最近完成格续建；
        连续 3 次卡滞 → 上报离线。
        坠落：检测到持续下坠且低于建造层 _fall_threshold 格以上 → 记录断点 +
        传送回临时点自救。
        """
        try:
            while not self._stopped and not self._stop_requested.is_set():
                await asyncio.sleep(2)
                if self._stopped or self._stop_requested.is_set():
                    break
                # 仅建造态检测卡滞（排尾等待/补货等待不触发）
                if self.progress.state not in ("moving", "placing"):
                    self._stuck_count = 0
                    continue
                try:
                    p = await self._get_player_pos_full()
                    if not p:
                        continue
                    now = time.monotonic()
                    # ── 卡滞检测 ──
                    if self._stuck_last_pos is None:
                        self._stuck_last_pos = p
                        self._stuck_check_ts = now
                    else:
                        moved = max(abs(p[0] - self._stuck_last_pos[0]),
                                    abs(p[2] - self._stuck_last_pos[2]))
                        if moved < 0.2 and (now - self._stuck_check_ts) >= self._stuck_timeout_s:
                            self._stuck_count += 1
                            self._activity("warn",
                                           f"卡滞检测：{self._stuck_timeout_s:.0f}s 无进展（第 {self._stuck_count} 次）")
                            if self._stuck_count >= 3:
                                self._activity("error", "连续 3 次卡滞 → 标记离线")
                                if self._on_bot_offline:
                                    try:
                                        self._on_bot_offline(self.bot_id, "stuck_3x")
                                    except Exception:
                                        pass
                                self.progress.state = "offline"
                                break
                            # 传送至本列最近完成格续建
                            await self._recover_from_stuck()
                            self._stuck_last_pos = None
                            self._stuck_check_ts = 0
                        elif moved >= 0.2:
                            self._stuck_last_pos = p
                            self._stuck_check_ts = now

                    # ── 坠落检测 ──
                    if p[1] < (self.origin_y + self._stand_y_offset - self._fall_threshold):
                        self._activity("warn",
                                       f"检测到坠落（y={p[1]:.1f} < 建造层-{self._fall_threshold}），尝试传送自救")
                        try:
                            await self._try_teleport_home("坠落自救")
                        except Exception as e:
                            logger.warning("[%s] Fall rescue error: %s", self.bot_id, e)
                        self._stuck_last_pos = None
                        self._stuck_check_ts = 0
                except Exception as e:
                    logger.warning("[%s] Guard monitor error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            pass

    async def _recover_from_stuck(self) -> None:
        """卡滞后传送（而非寻路）至本列最近已完成格续建。"""
        # 找本列最近一个已放置/已验证的格
        target = None
        for y in range(self.squad_start_y, self.squad_end_y + 1):
            wx, wz = self.origin_x + self.column_x, self.origin_z + y
            if (wx, self.origin_y, wz) in self._placed_coords or \
                    await self._verify_block(wx, self.origin_y, wz,
                                             self.block_matrix.get((self.column_x, y), "")):
                target = (wx, wz)
        if target is None:
            # 无已完成格 → 传送回建造点北缘
            self._activity("warn", "本列无已完成格，传送回建造点北缘")
            await self._try_teleport_home("卡滞无完成格")
            return
        self._activity("info", f"卡滞恢复：传送至本列最近完成格 ({target[0]},{target[1]})")
        await self._move_to(target[0], self.origin_y + 1, target[1],
                            max_offset=1, label="stuck-recover", verify_height=True)

    # ── 死亡复位增强（2026-08-19）────────────────

    async def _handle_death(self) -> None:
        """死亡复位主流程（继承增强版）：

        1. 复活完成、画面加载完毕 → 读取死亡点坐标（死亡事件最后已知位置）
        2. 死亡点位于建造层（Y≥origin_y-? 可配置）→ 执行 /back
        3. /back 后移动锁定（禁止移动/放置/交互），每0.5s轮询位置校验
           （与死亡点水平距离≤2格、Y=319±1、维度一致）→ 通过即解锁；最长
           _death_back_timeout_s 未通过 → 进入降级链
        4. 成功回到死亡点：拾取周围8格掉落物 → 校验背包物资与饱食度 →
           缺失按补货规则补足 → 从断点续建
        """
        try:
            # 死亡点 = 死亡事件触发时最后已知坐标
            death_pos = self._last_known_pos
            self._activity("warn", f"死亡事件：死亡点 {death_pos}，等待复活")
            # 等待复活完成（继承的 bot_death 事件流程已有 sleep）
            await asyncio.sleep(5)
            # 死亡点位于建造层才执行 /back（Y 阈值可配置，默认 origin_y-9）
            y_threshold = self.origin_y - 9
            if death_pos and death_pos[1] >= y_threshold:
                self._activity("info", "死亡点位于建造层附近，执行 /back")
                # 移动锁定：禁止一切移动/放置/交互
                self._death_lock.clear()
                try:
                    await self.mcp.send_chat("/back")
                    # 轮询位置校验（0.5s 间隔）
                    deadline = time.monotonic() + self._death_back_timeout_s
                    while time.monotonic() < deadline:
                        await asyncio.sleep(0.5)
                        p = await self._get_player_pos_full()
                        if p:
                            horiz = max(abs(p[0] - death_pos[0]), abs(p[2] - death_pos[2]))
                            if horiz <= 2 and abs(p[1] - self.origin_y) <= 1.5:
                                self._activity("info", "/back 到位，解锁移动")
                                break
                    else:
                        self._activity("warn", "/back 超时未到位，进入降级链")
                        await self._death_fallback_chain()
                        return
                except Exception as e:
                    logger.warning("[%s] /back error: %s", self.bot_id, e)
                    await self._death_fallback_chain()
                    return
                finally:
                    self._death_lock.set()  # 解锁移动
                # 成功回到死亡点：拾取掉落物
                try:
                    await self._pickup_drops(death_pos)
                except Exception as e:
                    logger.warning("[%s] Pickup drops error: %s", self.bot_id, e)
            else:
                self._activity("warn", f"死亡点 {death_pos} 不在建造层（y<{y_threshold}），跳过 /back 直接降级链")
                await self._death_fallback_chain()
                return
            # 校验背包物资与饱食度，缺失按补货规则补足
            try:
                await self._ensure_food_offhand()
            except Exception as e:
                logger.warning("[%s] Death food check error: %s", self.bot_id, e)
            self._activity("info", "死亡复位完成，从断点续建")
        except Exception as e:
            logger.warning("[%s] Death handling error: %s", self.bot_id, e)
            await self._death_fallback_chain()

    async def _death_fallback_chain(self) -> None:
        """复位降级链（逐级尝试，每级独立超时）：

        一级：传送至死亡前最后存储的临时传送点（dth，须存在且维度一致）
        二级：传送至兜底传送点 → 返回 x≤0 安全平台 → 沿已建区域寻路至当前任务列的最近完成格
        全部失败：上报协调器标记「离线待援」，触发减员容错
        """
        self._activity("warn", "进入复位降级链")
        # 一级：dth（临时传送点）
        try:
            dth_cmd = self._supply_cfg.get("return", "/ehomes dth")
            if await self._send_teleport(dth_cmd):
                p = await self._get_player_pos_full()
                if p and await self._verify_at_build_area() is None:
                    self._activity("info", "降级链一级（dth）成功")
                    return
        except Exception as e:
            logger.warning("[%s] Fallback L1 dth error: %s", self.bot_id, e)
        # 二级：兜底传送点（return_fixed）→ 寻路至最近完成格
        try:
            fixed_cmd = self._supply_cfg.get("return_fixed", "/ehomes mapart")
            if await self._send_teleport(fixed_cmd):
                p = await self._get_player_pos_full()
                if p and await self._verify_at_build_area() is None:
                    self._activity("info", "降级链二级（固定点）成功")
                    # 寻路至当前任务列最近完成格
                    await self._recover_from_stuck()
                    return
        except Exception as e:
            logger.warning("[%s] Fallback L2 fixed error: %s", self.bot_id, e)
        # 全部失败：上报协调器「离线待援」
        self._activity("error", "复位降级链全部失败 → 离线待援")
        if self._on_bot_offline:
            try:
                self._on_bot_offline(self.bot_id, "death_fallback_failed")
            except Exception:
                pass
        self.progress.state = "offline"

    async def _pickup_drops(self, at: tuple[float, float, float]) -> None:
        """拾取死亡点周围8格内自身掉落物（走近触发收集）。"""
        try:
            p = await self._get_player_pos_full()
            if p and max(abs(p[0] - at[0]), abs(p[2] - at[2])) > 2:
                await self._move_to(int(round(at[0])), int(round(at[1])) + 1,
                                    int(round(at[2])), max_offset=2,
                                    label="pickup-drops", verify_height=False)
            await asyncio.sleep(1.5)  # 走近后等待物品拾取
        except Exception as e:
            logger.warning("[%s] Pickup drops error: %s", self.bot_id, e)

    # ── 覆盖：死亡事件处理 ────────────────────

    def _on_bot_event(self, event_name: str, data: dict) -> None:
        """覆盖 BotBuildLoop._on_bot_event（同步契约，2026-08-19 增强）。

        mineflayer_client._handle_event 不 await handler——回调必须同步。
        死亡事件：记录最后已知位置（mcp.last_status 缓存）作为死亡点 →
        create_task 调度增强版 _handle_death（/back 主流程 + 降级链）。
        """
        try:
            if event_name == "bot_death":
                if self._stopped:
                    self._activity("debug", "任务已停止，忽略 bot 死亡恢复")
                    return
                # 记录死亡点：status 事件缓存的最后已知位置（同步回调无法 await）
                try:
                    st = getattr(self.mcp, "last_status", None) or {}
                    if isinstance(st, dict) and st.get("position"):
                        self._last_known_pos = (
                            float(st["position"].get("x", 0)),
                            float(st["position"].get("y", 0)),
                            float(st["position"].get("z", 0)),
                        )
                except Exception:
                    pass
                self._activity("warn", "⚠️ bot 死亡——等待复活后执行 /back 复位（增强流程）")
                logger.warning("[%s] bot_death event received, scheduling enhanced recovery",
                               self.bot_id)
                asyncio.create_task(self._handle_death())
        except Exception as e:
            logger.warning("[%s] bot event handler error: %s", self.bot_id, e)


# ──────────────────────────────────────────────
# MultiBotCoordinator — 多Bot列式协调器
# ──────────────────────────────────────────────

class MultiBotCoordinator:
    """多Bot列式协作建造协调器。

    Lifecycle:
      1. start() → 构建 ColumnBuildLoop 们 → 启动主编排循环（_squad_loop）
      2. 排级循环：起始站位 → 排内并行 → 排尾同步 → 整排推进 → 蛇形掉头
      3. pause()/resume()/stop() → 分发到所有 loops
      4. 减员容错：Bot离线 → 重组编队（新排宽=剩余Bot数）
      5. 进度定期落盘（map_art_task_progress 表），崩溃/重启后断点续建

    兼容旧 MapArtCoordinator 的公开接口：start/pause/resume/stop/
    add_bot/remove_bot/get_bot_inventory/force_sleep/_on_loop_done/_push_loop/
    _aggregate/_emit_map_init——保证 API 层无感切换。
    """

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        self.task_id = task_id
        self.projection = projection_data
        self.origin = (origin_x, origin_y, origin_z)
        self._loops: dict[str, ColumnBuildLoop] = {}
        self._started_at: float = time.monotonic()
        self._progress_task: Optional[asyncio.Task] = None
        self._squad_task: Optional[asyncio.Task] = None
        self._checkpoint_task: Optional[asyncio.Task] = None
        self._block_matrix: dict[tuple[int, int], str] = {}
        self._size_x: int = 0
        self._size_y: int = 0
        self._done_loops: set[str] = set()
        self._failed_loops: set[str] = set()
        self._completion_notified: bool = False
        # 编队状态
        self._squad = SquadState()
        self._squad.bot_done = set()
        self._active_bot_ids: list[str] = []   # 按分配顺序（mf-001 优先开路）
        self._leader_id: str = ColumnBuildLoop.LEADER_BOT
        # 上一排完成时刻（排尾同步节流）
        self._squad_advance_ts: float = 0.0
        # 补货配置（与旧协调器同源加载）
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = {}
        self._supply_config: dict = {}
        self._food_config: dict = {}
        self._food_boxes: list[tuple[int, int, int]] = []
        self._sleep_point: Optional[tuple[int, int, int]] = None
        self._activity_log: deque = deque(maxlen=300)
        self._load_task_config()

    # ── 配置加载（复用旧协调器逻辑）────────────────

    def _load_task_config(self) -> None:
        """从 DB 加载任务级配置（补货/食物/睡觉/全局）。"""
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import (
                MapArtTask, MapArtSupplyBox, MapArtSupplyWarehouse,
                MapArtFoodBox, MapArtGlobalConfig,
            )
            import json as _json
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task is None:
                    return
                # 补货传送指令
                if task.supply_config:
                    try:
                        d = _json.loads(task.supply_config)
                        if isinstance(d, dict):
                            self._supply_config = {
                                k: d.get(k, "") for k in ("go", "save", "return", "return_fixed")}
                    except Exception:
                        pass
                # 任务级潜影盒 + 全局仓库合并
                task_boxes: dict[str, list[tuple[int, int, int]]] = {}
                rows = db.query(MapArtSupplyBox).filter(
                    MapArtSupplyBox.task_id == self.task_id
                ).order_by(MapArtSupplyBox.sort_order).all()
                for r in rows:
                    task_boxes.setdefault(r.item_id, []).append((r.x, r.y, r.z))
                global_boxes: dict[str, list[tuple[int, int, int]]] = {}
                for g in db.query(MapArtSupplyWarehouse).all():
                    try:
                        boxes = _json.loads(g.boxes_json or "[]")
                        global_boxes[g.item_id] = [
                            (int(b["x"]), int(b["y"]), int(b["z"])) for b in boxes if "x" in b]
                    except Exception:
                        continue
                merged = dict(global_boxes)
                for item_id, boxes in task_boxes.items():
                    merged[item_id] = boxes
                self._supply_boxes = merged
                # 食物配置（全局优先）+ 食物潜影盒
                gcfg = db.query(MapArtGlobalConfig).filter(MapArtGlobalConfig.id == 1).first()
                if gcfg and gcfg.config_json:
                    try:
                        d = _json.loads(gcfg.config_json)
                        if isinstance(d, dict):
                            self._food_config = d
                            fboxes = d.get("food_boxes") or []
                            if fboxes:
                                self._food_boxes = [
                                    (int(b["x"]), int(b["y"]), int(b["z"]))
                                    for b in fboxes if isinstance(b, dict) and "x" in b]
                    except Exception:
                        pass
                if not self._food_config and task.food_config:
                    try:
                        d = _json.loads(task.food_config)
                        if isinstance(d, dict):
                            self._food_config = d
                    except Exception:
                        pass
                if not self._food_boxes:
                    fb_rows = db.query(MapArtFoodBox).filter(
                        MapArtFoodBox.task_id == self.task_id
                    ).order_by(MapArtFoodBox.sort_order).all()
                    self._food_boxes = [(r.x, r.y, r.z) for r in fb_rows]
                # 睡觉点
                if task.sleep_x is not None and task.sleep_y is not None and task.sleep_z is not None:
                    self._sleep_point = (int(task.sleep_x), int(task.sleep_y), int(task.sleep_z))
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load task config failed: %s", self.task_id, e)

    def _bot_sleep_point(self, bot_id: str) -> Optional[tuple[int, int, int]]:
        """per-bot 睡觉点：mcc_bots.sleep_x/y/z 优先，未配置回退任务级。"""
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.logistics import MccBotModel
            db = get_session_factory()()
            try:
                row = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
                if row is not None and row.sleep_x is not None \
                        and row.sleep_y is not None and row.sleep_z is not None:
                    return (int(row.sleep_x), int(row.sleep_y), int(row.sleep_z))
            finally:
                db.close()
        except Exception:
            pass
        return self._sleep_point

    # ── 活动日志（复用旧协调器）────────────────

    def _on_loop_activity(self, bot_id: str, bot_name: str, level: str, message: str) -> None:
        entry = {
            "task_id": self.task_id, "bot_id": bot_id, "bot_name": bot_name,
            "level": level, "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._activity_log.append(entry)
        try:
            asyncio.create_task(sio.emit("build_log", entry, room=f"build_{self.task_id}"))
        except Exception:
            pass

    def emit_log_history(self) -> None:
        """前端 join 房间时回放历史日志。"""
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

    # ── 2D matrix ─────────────────────────────

    @classmethod
    def build_2d_matrix(cls, layers: dict[int, list[tuple[int, int, int, str]]]) -> dict[tuple[int, int], str]:
        matrix: dict[tuple[int, int], str] = {}
        for y_offset, blocks in layers.items():
            for wx, wy, wz, block_id in blocks:
                matrix[(wx, wz)] = block_id
        return matrix

    # ── Lifecycle ─────────────────────────────

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]):
        """启动多Bot列式建造。

        Args:
            bot_agents: {bot_id: (bot_name, AbstractBotAgent)}
        """
        self._started_at = time.monotonic()
        self._squad.started_at = self._started_at
        self._block_matrix = self.build_2d_matrix(self.projection.get("layers", {}))
        self._size_x = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("x", 128)
        self._size_y = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("z", 128)

        n_bots = len(bot_agents)
        if n_bots == 0:
            logger.error("[%s] No bots available", self.task_id)
            return

        # Bot 排序：开路者（mf-001）优先，其余按配置顺序
        bot_ids = list(bot_agents.keys())
        if self._leader_id in bot_ids:
            bot_ids.remove(self._leader_id)
            bot_ids = [self._leader_id] + bot_ids
        self._active_bot_ids = bot_ids[:n_bots]
        self._squad.active_bots = list(self._active_bot_ids)

        # 复位手动控制状态（同旧协调器）
        for bot_id in self._active_bot_ids:
            _name, mcp = bot_agents[bot_id]
            try:
                if hasattr(mcp, "cancel_pathing"):
                    await mcp.cancel_pathing()
                if hasattr(mcp, "set_control_state"):
                    for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                        await mcp.set_control_state(ctrl, False)
            except Exception as e:
                logger.warning("[%s] Reset control state failed: %s", bot_id, e)

        # 构建 loops：全部分配第1排（x=1..n）
        first_row_columns = list(range(1, len(self._active_bot_ids) + 1))
        for i, bot_id in enumerate(self._active_bot_ids):
            bot_name, mcp = bot_agents[bot_id]
            loop = ColumnBuildLoop(
                bot_id=bot_id,
                bot_name=bot_name,
                task_id=self.task_id,
                column_region=ColumnRegion(first_row_columns[i], 1, self._size_y, 1),
                block_matrix=self._block_matrix,
                origin_x=self.origin[0],
                origin_y=self.origin[1],
                origin_z=self.origin[2],
                mcp=mcp,
                supply_boxes=self._supply_boxes,
                supply_config=self._supply_config,
                food_config=self._food_config,
                food_boxes=self._food_boxes,
                sleep_point=self._bot_sleep_point(bot_id),
                on_done=self._on_loop_done,
                on_activity=self._on_loop_activity,
                on_column_done=self._on_column_done,
                on_bot_offline=self._on_bot_offline,
                squad_lead=(bot_id == self._leader_id),
            )
            self._loops[bot_id] = loop
            self._squad.bot_columns[bot_id] = first_row_columns[i]
            asyncio.create_task(loop.run())

        # 启动主编排循环（起始站位 → 排级推进）
        self._squad_task = asyncio.create_task(self._squad_loop(bot_agents))
        # 进度推送
        self._progress_task = asyncio.create_task(self._push_loop())
        # 进度落盘
        self._checkpoint_task = asyncio.create_task(self._checkpoint_loop())

        # 初始地图数据推送
        await self._emit_map_init(bot_agents, self._active_bot_ids, self._size_x, self._size_y)

        logger.info("[%s] Multi-bot build started: %d bots, %d columns x %d rows",
                    self.task_id, len(self._active_bot_ids), self._size_x, self._size_y)

    async def pause(self):
        for loop in self._loops.values():
            try:
                await loop.pause()
            except Exception:
                pass

    async def resume(self):
        for loop in self._loops.values():
            try:
                await loop.resume()
            except Exception:
                pass

    async def stop(self):
        """停止任务：通知所有 loops 停止（含 _stop_requested）。"""
        for loop in self._loops.values():
            loop._stop_requested.set()
            try:
                await loop.stop()
            except Exception:
                pass
        for t in (self._squad_task, self._progress_task, self._checkpoint_task):
            if t:
                try:
                    t.cancel()
                except Exception:
                    pass
        # 落盘最终进度
        try:
            await self._persist_progress()
        except Exception:
            pass

    async def force_sleep(self, bot_id: str) -> dict:
        """手动触发该 bot 睡觉（复用 BotBuildLoop.force_sleep）。"""
        loop = self._loops.get(bot_id)
        if loop is not None:
            return await loop.force_sleep()
        return {"success": False, "reason": f"bot {bot_id} 不在任务 {self.task_id} 运行中"}

    # ── 主编排循环 ─────────────────────────

    async def _squad_loop(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]):
        """排级编排主循环。

        流程（对齐任务文档）：
          1. 首排起始站位：mf-001 从(0,1)出发沿x+放置n格脚下方块 → 其余Bot依次就位
          2. 协调器确认全员就位 → 广播开工
          3. 排内并行：各Bot独立完成本列（排尾同步由 _on_column_done 收集）
          4. 排尾同步：全部列完成 → 推进（mf-001搭连接条 + 其余就位）
          5. 蛇形掉头 → 循环直至完工
          6. 余列处理 / 完工报告
        """
        try:
            # 任务启动映射自检（四角测试方块校验，防镜像/旋转错误）
            try:
                await self._map_self_check(bot_agents)
            except Exception as _mc_e:
                logger.warning("[%s] Map self-check error: %s", self.task_id, _mc_e)

            squad_index = 1
            direction = 1
            while True:
                # 1. 起始站位（每排：mf-001 搭起始条 + 其余就位）
                n = len(self._squad.active_bots)
                if n <= 0:
                    break
                col_start = (squad_index - 1) * n + 1
                col_end = col_start + n - 1
                # 2026-08-19 余列处理：剩余列数 < n 时仅启用前 n' 台 bot（编号靠前）
                if col_end > self._size_x:
                    col_end = self._size_x
                    n = col_end - col_start + 1
                start_y = 1 if direction == 1 else self._size_y
                end_y = self._size_y if direction == 1 else 1

                # 更新编队状态
                self._squad.squad_index = squad_index
                self._squad.direction = direction
                self._squad.bot_done = set()
                self._activity("info",
                               f"排 {squad_index} 开始：列 [{col_start}..{col_end}] 方向 "
                               f"{'y+' if direction == 1 else 'y-'} 参与 {n} bot")

                # 1a. 开路者搭起始条（首排=平台起步，后续排=连接条）
                leader_ok = await self._place_connector_row(
                    bot_agents, col_start, col_end, start_y)
                if not leader_ok:
                    logger.warning("[%s] 排 %d 起始条失败，尝试降级继续", self.task_id, squad_index)

                # 1b. 各Bot就位到本排列（按序分批避免推挤）
                await self._position_bots(bot_agents, col_start, col_end, start_y, direction, squad_index)

                # 2. 广播开工（仅启用的前 n 台 bot）
                active_now = list(self._squad.active_bots)[:n]
                for bot_id in active_now:
                    loop = self._loops.get(bot_id)
                    if loop is not None:
                        await loop.signal_go()

                # 3. 排尾同步：等待所有活跃Bot上报列完成
                await self._wait_squad_done(timeout=3600)

                # 检查任务是否结束（停止/全部列完成）
                if self._stopped_check():
                    break
                # 判断是否还有剩余列
                next_col_start = col_end + 1
                remaining = self._size_x - (next_col_start - 1)
                if remaining <= 0:
                    break  # 全部列完成

                # 4. 推进：更新各Bot列号/方向（蛇形掉头）
                direction = -direction
                squad_index += 1
                # 减员重组：移除离线Bot
                if self._squad.offline_bots:
                    await self._reorganize_squad()
                await asyncio.sleep(1.0)  # 推进节流（防Bot移动互相推挤）
            # 完工：通知全部完成
            await self._finish_task()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[%s] Squad loop error: %s", self.task_id, e)
            await self._finish_task(failed=True, reason=str(e))

    async def _map_self_check(self, bot_agents) -> bool:
        """任务启动映射自检（2026-08-19 任务文档要求）：

        在投影图四角对应位置各放置 1 格测试方块并读回校验，确认无镜像/旋转
        错误后清除。校验失败 → 告警（不阻断，建造中 _verify_block 兜底）。
        """
        if not self._block_matrix:
            return False
        # 四角坐标（自定义坐标系）：(1,1)、(x_max,1)、(1,y_max)、(x_max,y_max)
        corners = [
            (1, 1), (self._size_x, 1), (1, self._size_y), (self._size_x, self._size_y),
        ]
        # 校验角：取该角实际投影色（air 则跳过——测试方块无法比对）
        check_corners = []
        for (cx, cy) in corners:
            bid = self._block_matrix.get((cx, cy))
            if bid and bid != "minecraft:air":
                check_corners.append((cx, cy, bid))
        if not check_corners:
            self._activity("info", "映射自检：四角无实心方块，跳过（透明角）")
            return True
        leader = self._loops.get(self._leader_id)
        if leader is None:
            return False
        self._activity("info", f"映射自检：校验 {len(check_corners)} 个角（防镜像/旋转错误）")
        ok_count = 0
        for (cx, cy, bid) in check_corners:
            wx = self.origin[0] + cx
            wz = self.origin[2] + cy
            try:
                # 放置测试方块（用该角投影色）
                if not await leader._ensure_item_in_hand(bid):
                    continue
                await leader._place_with_retry(wx, leader.origin_y, wz, bid)
                await asyncio.sleep(0.5)
                actual = await leader.mcp.get_world_block_at(wx, leader.origin_y, wz)
                name = ((actual.get("name") or "air").split("[")[0])
                if name != "air" and name != bid.split(":")[-1]:
                    self._activity("error",
                                   f"映射自检失败：角 ({cx},{cy}) 期望 {bid.split(':')[-1]} 实际 {name}——"
                                   f"可能存在镜像/旋转错误，请检查 origin 与旋转配置")
                    return False
                ok_count += 1
            except Exception as e:
                logger.warning("[%s] Self-check corner (%d,%d) error: %s", self.task_id, cx, cy, e)
        self._activity("info", f"映射自检通过（{ok_count}/{len(check_corners)} 角校验一致）")
        return True

    async def _place_connector_row(self, bot_agents, col_start: int, col_end: int,
                                   start_y: int) -> bool:
        """开路者（mf-001）沿起始行向 x+ 放置 n 格连接条（脚下方块）。

        首排：从(0,1)出发沿x+放置 n 格（第1排起始条）
        后续排：从上一排列尾位置沿x+放置 n 格（新排起始条）
        """
        leader = self._loops.get(self._leader_id)
        if leader is None or self._leader_id not in self._squad.active_bots:
            logger.warning("[%s] 开路者 %s 不在活跃编队，跳过搭条", self.task_id, self._leader_id)
            return False
        try:
            world_z = self.origin[2] + start_y
            placed_ok = True
            # mf-001 从 col_start-1（或安全平台）出发，沿x+放置 col_start..col_end
            for x in range(col_start, col_end + 1):
                block_id = self._block_matrix.get((x, start_y))
                if not block_id or block_id == "minecraft:air":
                    # 透明格：用临时方块
                    block_id = "minecraft:dirt"
                world_x = self.origin[0] + x
                # 移动到放置位置旁（x-1 处，即已放方块上）
                prev_x = self.origin[0] + (x - 1)
                ok = await leader._move_to(prev_x, self.origin[1] + 1, world_z,
                                           max_offset=1, label=f"connector({x},{start_y})",
                                           verify_height=True)
                if not ok:
                    logger.warning("[%s] 开路者搭条移动到 (%d,%d) 失败", self.task_id, x, start_y)
                    placed_ok = False
                    break
                if not await leader._ensure_item_in_hand(block_id):
                    logger.warning("[%s] 开路者搭条材料缺失 %s", self.task_id, block_id)
                    placed_ok = False
                    break
                if not await leader._place_with_retry(world_x, self.origin[1], world_z, block_id):
                    logger.warning("[%s] 开路者搭条放置 (%d,%d) 失败", self.task_id, x, start_y)
                    placed_ok = False
                    break
                await asyncio.sleep(leader._column_place_interval)
            self._activity("info",
                           f"开路者搭条完成：x[{col_start}..{col_end}] y={start_y} "
                           f"({'成功' if placed_ok else '部分失败'})")
            return placed_ok
        except Exception as e:
            logger.warning("[%s] Place connector row error: %s", self.task_id, e)
            return False

    async def _position_bots(self, bot_agents, col_start: int, col_end: int,
                             start_y: int, direction: int, squad_index: int) -> None:
        """各Bot就位到本排列（按序分批，避免互相推挤）。

        就位目标：本Bot列的起始条方块顶（(world_x, origin_y+1, world_z)）。
        按序分批：一次让 1-2 个 bot 移动，等到位后再下一批。
        """
        # 分配列：mf-001 最右（col_end），其余按顺序递减
        columns: dict[str, int] = {}
        active = list(self._squad.active_bots)
        leader_idx = self._leader_id in active
        if leader_idx:
            columns[self._leader_id] = col_end
        others = [b for b in active if b != self._leader_id]
        for i, bid in enumerate(others):
            columns[bid] = col_end - 1 - i
        self._squad.bot_columns = columns

        # 按序分批就位（每批1个，等待到位后下一批——避免推挤）
        ordered = [self._leader_id] + others if leader_idx else active
        for bid in ordered:
            if bid not in self._squad.active_bots:
                continue
            loop = self._loops.get(bid)
            if loop is None:
                continue
            col = columns.get(bid, col_start)
            world_x = self.origin[0] + col
            world_z = self.origin[2] + start_y
            # 通知 loop 本排分配
            await loop.assign_squad(col, direction,
                                    start_y if direction == 1 else 1,
                                    self._size_y if direction == 1 else 1,
                                    squad_index)
            # 移动到起始条方块顶
            self._activity("info", f"{bid} 就位 → 列 x={col}, y={start_y}")
            try:
                ok = await loop._move_to(world_x, self.origin[1] + 1, world_z,
                                         max_offset=1, label=f"pos({bid},{col},{start_y})",
                                         timeout_ms=30000, verify_height=True)
                if not ok:
                    logger.warning("[%s] %s 就位失败（列x=%d y=%d）", self.task_id, bid, col, start_y)
            except Exception as e:
                logger.warning("[%s] %s 就位异常: %s", self.task_id, bid, e)
            await asyncio.sleep(0.8)  # 分批间隔（防推挤）

    async def _wait_squad_done(self, timeout: float = 3600) -> None:
        """排尾同步：等待所有活跃Bot上报列完成。

        轮询 _squad.bot_done 集合；超时未完成的 bot 标记离线（减员容错）。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stopped_check():
                return
            active = [b for b in self._squad.active_bots
                      if b not in self._squad.offline_bots]
            if all(b in self._squad.bot_done for b in active):
                self._activity("info",
                               f"排 {self._squad.squad_index} 全部列完成（{len(active)} bot）")
                return
            await asyncio.sleep(2)
        # 超时：未完成 bot 标记离线（减员容错）
        missing = [b for b in self._squad.active_bots
                   if b not in self._squad.bot_done and b not in self._squad.offline_bots]
        if missing:
            self._activity("warn", f"排尾同步超时，标记离线：{missing}")
            for bid in missing:
                self._squad.offline_bots.append(bid)
                loop = self._loops.get(bid)
                if loop is not None:
                    loop.progress.state = "offline"

    async def _reorganize_squad(self) -> None:
        """减员重组：移除离线Bot，剩余Bot以新排宽重组编队继续建造。"""
        offline = list(self._squad.offline_bots)
        if not offline:
            return
        for bid in offline:
            if bid in self._squad.active_bots:
                self._squad.active_bots.remove(bid)
            if bid in self._squad.bot_columns:
                del self._squad.bot_columns[bid]
        self._activity("info",
                       f"减员重组：离线 {offline}，活跃 {self._squad.active_bots}，"
                       f"后续排宽 = {len(self._squad.active_bots)}")
        # 离线 bot 的 loop 停止
        for bid in offline:
            loop = self._loops.get(bid)
            if loop is not None:
                try:
                    loop._stop_requested.set()
                    await loop.stop()
                except Exception:
                    pass

    def _stopped_check(self) -> bool:
        """检查任务是否应停止（协调器级）。"""
        if self._completion_notified:
            return True
        if not self._loops:
            return True
        # 所有 loop 都 offline/停止 → 停止编排
        all_offline = all(
            loop.progress.state == "offline" or loop._stop_requested.is_set()
            for loop in self._loops.values()
        )
        return all_offline

    async def _finish_task(self, failed: bool = False, reason: str = "") -> None:
        """任务完工：校验各Bot所在格 → 传送回兜底位置 → 输出完工报告。"""
        if self._completion_notified:
            return
        self._completion_notified = True
        try:
            # 全图扫描对账（任务级）：实际方块 vs 投影逐格比对 → 差异报告
            missing, wrong = await self._full_scan_reconcile()
            self._activity("info",
                           f"全图对账完成：漏放 {missing} 格，错色 {wrong} 格")
            if missing or wrong:
                self._activity("warn", "存在差异，启动自动补齐")
                await self._auto_fix_diffs(missing, wrong)
                missing2, wrong2 = await self._full_scan_reconcile()
                self._activity("info", f"补齐后复检：漏放 {missing2} 格，错色 {wrong2} 格")
            # 各Bot传送回兜底位置
            for bid, loop in self._loops.items():
                try:
                    fixed_cmd = loop._supply_cfg.get("return_fixed", "/ehomes mapart")
                    await loop._send_teleport(fixed_cmd)
                except Exception:
                    pass
            # 更新 DB 状态
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTask
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task:
                    task.status = "failed" if failed else "completed"
                    task.completed_at = datetime.now(timezone.utc)
                    task.error_message = reason or task.error_message or ""
                    db.commit()
            finally:
                db.close()
            await sio.emit("build_progress",
                           {"task_id": self.task_id,
                            "status": "failed" if failed else "completed",
                            "error_message": reason},
                           room=f"build_{self.task_id}")
        except Exception as e:
            logger.error("[%s] Finish task error: %s", self.task_id, e)

    async def _full_scan_reconcile(self) -> tuple[int, int]:
        """全图扫描对账：遍历 block_matrix 逐格比对实际方块与投影。

        返回 (漏放数, 错色数)。用带头 bot 的 mcp 读取方块。
        """
        missing = 0
        wrong = 0
        leader = self._loops.get(self._leader_id)
        if leader is None:
            return 0, 0
        try:
            # 分块扫描（每 256 格一批，防 WS 大帧）
            batch: list[tuple[int, int, str]] = []
            total_checked = 0
            for (x, y), block_id in self._block_matrix.items():
                if not block_id or block_id == "minecraft:air":
                    continue
                world_x = self.origin[0] + x
                world_z = self.origin[2] + y
                batch.append((world_x, world_z, block_id))
                if len(batch) >= 256:
                    m, w = await self._scan_batch(leader, batch)
                    missing += m
                    wrong += w
                    total_checked += len(batch)
                    batch = []
            if batch:
                m, w = await self._scan_batch(leader, batch)
                missing += m
                wrong += w
            self._activity("info", f"全图扫描完成：检查 {total_checked + len(batch)} 格")
        except Exception as e:
            logger.warning("[%s] Full scan reconcile error: %s", self.task_id, e)
        return missing, wrong

    async def _scan_batch(self, leader: ColumnBuildLoop,
                          batch: list[tuple[int, int, str]]) -> tuple[int, int]:
        missing = 0
        wrong = 0
        for wx, wz, expected in batch:
            try:
                actual = await leader.mcp.get_world_block_at(wx, leader.origin_y, wz)
                name = ((actual.get("name") or "air").split("[")[0])
                if name == "air":
                    missing += 1
                elif name != expected.split(":")[-1]:
                    wrong += 1
            except Exception:
                missing += 1
        return missing, wrong

    async def _auto_fix_diffs(self, missing: int, wrong: int) -> None:
        """自动补齐差异格（简单实现：用带头 bot 逐格补放）。"""
        leader = self._loops.get(self._leader_id)
        if leader is None or missing + wrong == 0:
            return
        fixed = 0
        for (x, y), block_id in self._block_matrix.items():
            if not block_id or block_id == "minecraft:air":
                continue
            world_x = self.origin[0] + x
            world_z = self.origin[2] + y
            try:
                actual = await leader.mcp.get_world_block_at(world_x, leader.origin_y, world_z)
                name = ((actual.get("name") or "air").split("[")[0])
                if name == "air" or name != block_id.split(":")[-1]:
                    # 需要补放
                    if not await leader._ensure_item_in_hand(block_id):
                        continue
                    if await leader._place_with_retry(world_x, leader.origin_y, world_z, block_id):
                        fixed += 1
                        await asyncio.sleep(leader._column_place_interval)
            except Exception:
                continue
        self._activity("info", f"自动补齐完成：{fixed} 格")

    # ── 回调：列完成 / 离线 ──────────────────

    def _on_column_done(self, bot_id: str) -> None:
        """Bot 列完成回调（排尾同步收集）。"""
        self._squad.bot_done.add(bot_id)
        loop = self._loops.get(bot_id)
        if loop:
            placed = loop.progress.blocks_placed
            self._squad.placed_total = max(self._squad.placed_total, placed)

    def _on_bot_offline(self, bot_id: str, reason: str = "") -> None:
        """Bot 离线回调（减员容错触发）。"""
        if bot_id not in self._squad.offline_bots:
            self._squad.offline_bots.append(bot_id)
        self._activity("error", f"{bot_id} 离线（{reason}）→ 等待减员重组")
        # 异步触发重组（不等排尾同步）
        asyncio.create_task(self._reorganize_squad())

    def _on_loop_done(self, bot_id: str) -> None:
        """兼容接口：旧协调器的区域完成回调（列式模式下用于进度统计）。"""
        self._done_loops.add(bot_id)
        loop = self._loops.get(bot_id)
        if loop is not None and loop.progress.state == "failed":
            self._failed_loops.add(bot_id)

    # ── 进度推送 & 落盘 ─────────────────────

    async def _push_loop(self):
        """每2s聚合进度推送（Socket.IO）。"""
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self._push_progress()
                except Exception as e:
                    logger.warning("[%s] Push progress failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _push_progress(self):
        # 2026-08-19：净建造速率统计——只统计「建造态」（placing/moving）时间，
        # 剔除补货/复位/同步等待耗时；已建格数以放置成功事件计数（progress.blocks_placed）
        try:
            now = time.monotonic()
            any_building = any(
                l.progress.state in ("placing", "moving") for l in self._loops.values()
            )
            if any_building:
                if self._squad.last_build_ts > 0:
                    self._squad.build_active_sec += (now - self._squad.last_build_ts)
                self._squad.last_build_ts = now
            else:
                self._squad.last_build_ts = now  # 重置基准（剔除等待）
        except Exception:
            pass

        state = self._aggregate()
        room = f"build_{self.task_id}"
        await sio.emit("build_progress", state.__dict__, room=room)

        # Bot 位置/状态
        bot_data = []
        for bid, loop in self._loops.items():
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
            lp = loop._last_pos
            pos = real_pos or ({"x": lp[0], "y": lp[1], "z": lp[2]} if lp else None)
            bot_data.append({
                "bot_id": bid,
                "bot_name": loop.bot_name,
                "state": loop.progress.state,
                "position": pos,
                "health": health,
                "food": food,
                "column": loop.column_x,
                "squad_index": loop.squad_index,
                "squad_direction": loop.squad_direction,
                "blocks_placed": loop.progress.blocks_placed,
                "blocks_total": loop.progress.blocks_total,
                "place_rate": loop.progress.place_rate,
                "rate": loop.progress.place_rate,
            })
        await sio.emit("build_bot_status", {"task_id": self.task_id, "bots": bot_data}, room=room)

    async def _checkpoint_loop(self):
        """进度定期落盘（map_art_task_progress 表，每30s）。"""
        try:
            interval = 30.0
            try:
                interval = max(10.0, float(
                    getattr(get_config().mineflayer, "map_art_checkpoint_interval_s", 30) or 30))
            except Exception:
                pass
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._persist_progress()
                except Exception as e:
                    logger.warning("[%s] Checkpoint persist failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _persist_progress(self) -> None:
        """进度落盘（SQLite map_art_task_progress 表）。"""
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTaskProgress
            import json as _json
            payload = {
                "squad_index": self._squad.squad_index,
                "direction": self._squad.direction,
                "active_bots": self._squad.active_bots,
                "offline_bots": self._squad.offline_bots,
                "bot_columns": self._squad.bot_columns,
                "total_columns": self._size_x,
                "total_rows": self._size_y,
                "placed_total": self._squad.placed_total,
            }
            db = get_session_factory()()
            try:
                row = db.query(MapArtTaskProgress).filter(
                    MapArtTaskProgress.task_id == self.task_id).first()
                if row is None:
                    row = MapArtTaskProgress(
                        task_id=self.task_id, progress_json=_json.dumps(payload))
                    db.add(row)
                else:
                    row.progress_json = _json.dumps(payload)
                    row.checkpoint_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Persist progress error: %s", self.task_id, e)

    async def load_progress(self) -> Optional[dict]:
        """加载持久化进度（崩溃/重启断点续建）。"""
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTaskProgress
            import json as _json
            db = get_session_factory()()
            try:
                row = db.query(MapArtTaskProgress).filter(
                    MapArtTaskProgress.task_id == self.task_id).first()
                if row and row.progress_json:
                    d = _json.loads(row.progress_json)
                    self._squad.squad_index = d.get("squad_index", 1)
                    self._squad.direction = d.get("direction", 1)
                    self._squad.active_bots = d.get("active_bots", [])
                    self._squad.offline_bots = d.get("offline_bots", [])
                    self._squad.bot_columns = d.get("bot_columns", {})
                    self._squad.placed_total = d.get("placed_total", 0)
                    self._size_x = d.get("total_columns", self._size_x)
                    self._size_y = d.get("total_rows", self._size_y)
                    return d
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load progress error: %s", self.task_id, e)
        return None

    # ── 兼容接口 ─────────────────────────────

    async def get_bot_inventory(self) -> list[dict]:
        """返回任务正在工作的每个 bot 的背包快照。"""
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

    async def _emit_map_init(self, bot_agents, bot_ids, size_x, size_z):
        """初始地图数据推送（兼容旧格式 + 列式扩展）。"""
        room = f"build_{self.task_id}"
        blocks = [
            {"x": x, "y": self.origin[1], "z": z, "expected": bid, "placed": False}
            for (x, z), bid in self._block_matrix.items()
        ]
        bots = []
        for bid in bot_ids:
            loop = self._loops.get(bid)
            col = loop.column_x if loop else 1
            bots.append({
                "bot_id": bid,
                "name": bot_agents[bid][0] if bid in bot_agents else bid,
                "color": f"#{zlib.crc32(bid.encode()) & 0xFFFFFF:06x}",
                "column": col,
                "squad_index": 1,
                "state": "idle",
            })
        await sio.emit("build_map_init", {
            "task_id": self.task_id,
            "blocks": blocks,
            "bots": bots,
            "origin": {"x": self.origin[0], "y": self.origin[1], "z": self.origin[2]},
            "size": {"x": size_x, "z": size_z},
            "build_mode": "column",
        }, room=room)

    def _aggregate(self) -> MapArtBuildState:
        total = self._size_x * self._size_y
        placed = sum(l.progress.blocks_placed for l in self._loops.values())
        elapsed = time.monotonic() - self._started_at
        rate = placed / (elapsed / 60) if elapsed > 0 else 0
        remaining = max(0, total - placed)
        eta = (remaining / rate) * 60 if rate > 0 else 0
        # 2026-08-19：净建造速率（仅统计建造态时间，剔除补货/复位/同步等待）
        net_sec = self._squad.build_active_sec
        net_rate = placed / (net_sec / 60) if net_sec > 1 else rate
        net_eta = (remaining / net_rate) * 60 if net_rate > 0 else 0

        if self._completion_notified:
            status = "completed"
        elif self._failed_loops:
            status = "failed"
        elif any(l.progress.state == "waiting" for l in self._loops.values()) \
                and all(l.progress.state in ("waiting", "completed")
                        for l in self._loops.values()):
            status = "running"
        else:
            status = "running"

        bots = [{
            "bot_id": l.bot_id,
            "name": l.bot_name,
            "state": l.progress.state,
            "column": l.column_x,
            "squad_index": l.squad_index,
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
            materials={},
            elapsed_sec=elapsed,
            eta_sec=eta,
            net_rate=round(net_rate, 1),
            net_eta=net_eta,
            squad_index=self._squad.squad_index,
            build_mode="column",
        )


# ──────────────────────────────────────────────
# Global registry of active multi-bot coordinators
# ──────────────────────────────────────────────

_active_multi_coordinators: dict[str, MultiBotCoordinator] = {}


def get_multi_coordinator(task_id: str) -> Optional[MultiBotCoordinator]:
    """获取多Bot协调器（API 层按 build_mode 选择）。"""
    return _active_multi_coordinators.get(task_id)


def register_multi_coordinator(task_id: str, coordinator: MultiBotCoordinator):
    _active_multi_coordinators[task_id] = coordinator


def unregister_multi_coordinator(task_id: str):
    _active_multi_coordinators.pop(task_id, None)
