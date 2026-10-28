"""地图画建造配置 —— 唯一默认值来源（重构前散落 60+ 处 getattr）。

用法::

    st = MapArtSettings.load()
    st.place_interval_s / st.restock_stacks / st.sleep_night_start ...

所有 ``map_art_*`` 键在这里一次性读取 + 夹取合法区间；引擎内**不再**直接
``getattr(get_config().mineflayer, ...)``。历史上 config 默认值与代码兜底默认值
不一致（``map_art_restock_stacks`` config=1 / 代码兜底=4）就是靠这一层消除的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _mf() -> Any:
    """惰性拿 mineflayer 配置段（失败返回 None，全部走默认值）。"""
    try:
        from vmtools_next.config import get_config

        return getattr(get_config(), "mineflayer", None)
    except Exception:
        return None


def _i(cfg: Any, key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        val = int(getattr(cfg, key, default) if cfg is not None else default)
    except Exception:
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def _f(cfg: Any, key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        val = float(getattr(cfg, key, default) if cfg is not None else default)
    except Exception:
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def _s(cfg: Any, key: str, default: str) -> str:
    try:
        val = getattr(cfg, key, default) if cfg is not None else default
    except Exception:
        return default
    return str(val if val is not None else default)


def _b(cfg: Any, key: str, default: bool) -> bool:
    try:
        val = getattr(cfg, key, default) if cfg is not None else default
    except Exception:
        return default
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val)


@dataclass
class MapArtSettings:
    """全部地图画运行参数（一次加载，构造后只读）。"""

    # ── 补货传送指令 ──
    supply_go: str = "/ehomes mdssj"
    supply_save: str = "/esethomes dth"
    supply_return: str = "/ehomes dth"
    supply_return_fixed: str = "/ehomes mapart"
    supply_box_y_offset: int = -1
    # ── 补货决策 ──
    restock_stacks: int = 1
    min_restock_interval_s: float = 90.0
    # ── 食物 ──
    food_item: str = "minecraft:cooked_porkchop"
    food_go_command: str = "/res tp lixiangxiang.qwp"
    food_wait_after_go_ms: int = 5000
    eat_threshold_food: int = 15
    eat_threshold_health: int = 15
    food_restock_cooldown_s: float = 120.0
    # ── 站立层 / 环境 ──
    stand_y_offset: int = 0
    build_residence: str = ""
    build_world: str = "overworld"
    whitelist_dimensions: tuple[str, ...] = ("world_the_end",)
    # ── 睡觉 ──
    sleep_night_start_tick: int = 12542
    sleep_night_end_tick: int = 23458
    sleep_check_interval_s: float = 10.0
    sleep_min_sleep_s: float = 5.0
    sleep_max_wait_s: float = 300.0
    sleep_go_command: str = ""
    # ── 移动 / 放置 / 传送兜底 ──
    move_retries: int = 2
    place_retries: int = 3
    verify_y_tol: float = 1.0
    tp_retry_each: int = 3
    tp_retry_total: int = 8
    move_timeout_ms: int = 20000
    place_interval_s: float = 0.25          # strip：由 safety.place_interval_ticks 换算
    column_place_interval_s: float = 0.3    # column：多 bot 同时放置的服务端节流
    # ── 列式编队 / 容错 ──
    stuck_timeout_s: float = 10.0
    death_back_timeout_s: float = 10.0
    bot_offline_timeout_s: float = 120.0
    fall_threshold: int = 3
    checkpoint_interval_s: float = 30.0
    # ── 缺块自动补放（#51） ──
    auto_fix_enabled: bool = True
    auto_fix_max_rounds: int = 2
    auto_fix_batch: int = 256
    # ── 杂项 ──
    warehouse_home: str = "mdssj"
    temp_home: str = "gzqy"
    raw: dict = field(default_factory=dict)

    # ── 构造 ──

    @classmethod
    def load(cls) -> "MapArtSettings":
        cfg = _mf()
        # 放置间隔：优先 safety.place_interval_ticks（tick=50ms），否则 map_art_place_interval_s
        try:
            from vmtools_next.config import get_config as _gc

            ticks = int(getattr(_gc().safety, "place_interval_ticks", 3) or 3)
            place_interval = max(0.15, ticks / 20.0)
        except Exception:
            place_interval = 0.25
        whitelist = tuple(
            s.strip() for s in _s(cfg, "map_art_whitelist_dimensions", "world_the_end").split(",")
            if s.strip()
        ) or ("world_the_end",)
        return cls(
            supply_go=_s(cfg, "map_art_supply_go_command", "/ehomes mdssj"),
            supply_save=_s(cfg, "map_art_supply_save_command", "/esethomes dth"),
            supply_return=_s(cfg, "map_art_supply_return_command", "/ehomes dth"),
            supply_return_fixed=_s(cfg, "map_art_supply_fixed_return_command", "/ehomes mapart"),
            supply_box_y_offset=_i(cfg, "map_art_supply_box_y_offset", -1),
            restock_stacks=_i(cfg, "map_art_restock_stacks", 1, lo=1, hi=16),
            min_restock_interval_s=_f(cfg, "map_art_min_restock_interval_s", 90.0, lo=0.0),
            food_item=_s(cfg, "map_art_food_item", "minecraft:cooked_porkchop"),
            food_go_command=_s(cfg, "map_art_food_go_command", "/res tp lixiangxiang.qwp"),
            food_wait_after_go_ms=_i(cfg, "map_art_food_wait_after_go_ms", 5000, lo=0),
            eat_threshold_food=_i(cfg, "map_art_eat_threshold_food", 15, lo=0, hi=20),
            eat_threshold_health=_i(cfg, "map_art_eat_threshold_health", 15, lo=0, hi=20),
            food_restock_cooldown_s=_f(cfg, "map_art_food_restock_cooldown_s", 120.0, lo=0.0),
            stand_y_offset=_i(cfg, "map_art_stand_y_offset", 0, lo=-8, hi=8),
            build_residence=_s(cfg, "map_art_residence", "").strip(),
            build_world=_s(cfg, "map_art_build_world", "overworld").strip(),
            whitelist_dimensions=whitelist,
            sleep_night_start_tick=_i(cfg, "map_art_sleep_night_start_tick", 12542, lo=0, hi=24000),
            sleep_night_end_tick=_i(cfg, "map_art_sleep_night_end_tick", 23458, lo=0, hi=24000),
            sleep_check_interval_s=_f(cfg, "map_art_sleep_check_interval_s", 10.0, lo=3.0),
            sleep_min_sleep_s=_f(cfg, "map_art_sleep_min_sleep_s", 5.0, lo=2.0),
            sleep_max_wait_s=_f(cfg, "map_art_sleep_max_wait_s", 300.0, lo=30.0),
            sleep_go_command=_s(cfg, "map_art_sleep_go_command", "").strip(),
            move_retries=_i(cfg, "map_art_move_retries", 2, lo=1),
            place_retries=_i(cfg, "map_art_place_retries", 3, lo=1),
            verify_y_tol=_f(cfg, "map_art_verify_y_tol", 1.0, lo=0.5),
            tp_retry_each=_i(cfg, "map_art_tp_retry_each", 3, lo=1),
            tp_retry_total=_i(cfg, "map_art_tp_retry_total", 8, lo=1),
            move_timeout_ms=_i(cfg, "map_art_move_timeout_ms", 20000, lo=1000),
            place_interval_s=place_interval,
            column_place_interval_s=_f(cfg, "map_art_column_place_interval_s", 0.3, lo=0.15),
            stuck_timeout_s=_f(cfg, "map_art_stuck_timeout_s", 10.0, lo=5.0),
            death_back_timeout_s=_f(cfg, "map_art_death_back_timeout_s", 10.0, lo=3.0),
            bot_offline_timeout_s=_f(cfg, "map_art_bot_offline_timeout_s", 120.0, lo=30.0),
            fall_threshold=_i(cfg, "map_art_fall_threshold", 3, lo=1),
            checkpoint_interval_s=_f(cfg, "map_art_checkpoint_interval_s", 30.0, lo=10.0),
            auto_fix_enabled=_b(cfg, "map_art_auto_fix_enabled", True),
            auto_fix_max_rounds=_i(cfg, "map_art_auto_fix_max_rounds", 2, lo=0, hi=5),
            auto_fix_batch=_i(cfg, "map_art_auto_fix_batch", 256, lo=16, hi=2048),
            warehouse_home=_s(cfg, "map_art_warehouse_home", "mdssj"),
            temp_home=_s(cfg, "map_art_temp_home", "gzqy"),
            raw={},
        )

    # ── 派生默认值 ──

    def default_supply_config(self) -> dict:
        return {
            "go": self.supply_go,
            "save": self.supply_save,
            "return": self.supply_return,
            "return_fixed": self.supply_return_fixed,
        }

    def default_food_config(self) -> dict:
        return {
            "item_id": self.food_item,
            "go_command": self.food_go_command,
            "wait_after_go_ms": self.food_wait_after_go_ms,
            "eat_threshold_food": self.eat_threshold_food,
            "eat_threshold_health": self.eat_threshold_health,
        }
