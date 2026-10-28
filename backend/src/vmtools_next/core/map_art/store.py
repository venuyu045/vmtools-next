"""地图画数据访问层（DB 读写集中在这里）。

重构前的问题：
  - ``_flush_db`` 每块一次 ``SELECT`` + 逐行 UPDATE（47 万块任务 = 47 万次往返）
  - 对账三份实现各自 ``.first()`` 逐行查
  - 配置加载散落在两个协调器里（supply / food / sleep 各一套）

本模块提供：
  - ``load_task_config``  任务级补货/食物/睡觉配置（任务级优先、全局仓库/全局食物合并）
  - ``flush_placed``      批量 UPDATE（executemany，一次事务）+ 任务聚合计数
  - ``query_cells``       按世界坐标范围查格子（对账用，只取需要的列）
  - ``mark_verified`` / ``mark_reset``  批量收敛对账状态
  - ``persist_status`` / ``save_progress`` / ``load_progress``  任务状态与断点
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger("vmtools.map_art.store")


def _session():
    """拿一个新 Session（不可用时抛异常，调用方自行兜底）。"""
    from vmtools_next.data.db import get_session_factory

    return get_session_factory()()


def _models():
    from vmtools_next.data.models import build_map_art as m

    return m


class MapArtStore:
    """单个地图画任务的持久化门面。所有方法都不抛异常（内部兜底 + 日志）。"""

    def __init__(self, task_id: str):
        self.task_id = task_id

    # ──────────────────────────────────────────
    # 配置加载
    # ──────────────────────────────────────────

    def load_task_config(self) -> dict:
        """一次性读全任务配置。

        返回 ``{supply_config, supply_boxes, food_config, food_boxes,
                sleep_point, build_mode, size_x, size_z, origin, status}``
        """
        out: dict = {
            "supply_config": {},
            "supply_boxes": {},
            "food_config": {},
            "food_boxes": [],
            "sleep_point": None,
            "build_mode": "column",
            "size_x": 0,
            "size_z": 0,
            "origin": (0, 0, 0),
            "status": "",
        }
        try:
            m = _models()
            db = _session()
            try:
                task = db.query(m.MapArtTask).filter(m.MapArtTask.task_id == self.task_id).first()
                if task is None:
                    return out
                out["build_mode"] = getattr(task, "build_mode", None) or "column"
                out["size_x"] = int(task.projection_size_x or 0)
                out["size_z"] = int(task.projection_size_z or 0)
                out["origin"] = (int(task.origin_x or 0), int(task.origin_y or 0),
                                 int(task.origin_z or 0))
                out["status"] = task.status or ""
                # 补货传送指令
                if task.supply_config:
                    try:
                        d = json.loads(task.supply_config)
                        if isinstance(d, dict):
                            out["supply_config"] = {
                                k: str(d.get(k) or "") for k in ("go", "save", "return", "return_fixed")
                            }
                    except Exception:
                        pass
                # 任务级潜影盒 + 全局仓库（任务级优先）
                task_boxes: dict[str, list[tuple[int, int, int]]] = {}
                for r in db.query(m.MapArtSupplyBox).filter(
                    m.MapArtSupplyBox.task_id == self.task_id
                ).order_by(m.MapArtSupplyBox.sort_order).all():
                    task_boxes.setdefault(r.item_id, []).append((int(r.x), int(r.y), int(r.z)))
                global_boxes: dict[str, list[tuple[int, int, int]]] = {}
                for g in db.query(m.MapArtSupplyWarehouse).all():
                    try:
                        boxes = json.loads(g.boxes_json or "[]")
                        global_boxes[g.item_id] = [
                            (int(b["x"]), int(b["y"]), int(b["z"]))
                            for b in boxes if isinstance(b, dict) and "x" in b
                        ]
                    except Exception:
                        continue
                merged = dict(global_boxes)
                merged.update(task_boxes)
                out["supply_boxes"] = merged
                # 食物配置：全局优先（一个任务改 → 处处生效），任务级兼容
                gcfg = db.query(m.MapArtGlobalConfig).filter(m.MapArtGlobalConfig.id == 1).first()
                if gcfg and gcfg.config_json:
                    try:
                        d = json.loads(gcfg.config_json)
                        if isinstance(d, dict):
                            out["food_config"] = d
                            fboxes = d.get("food_boxes") or []
                            out["food_boxes"] = [
                                (int(b["x"]), int(b["y"]), int(b["z"]))
                                for b in fboxes if isinstance(b, dict) and "x" in b
                            ]
                    except Exception:
                        pass
                if not out["food_config"] and task.food_config:
                    try:
                        d = json.loads(task.food_config)
                        if isinstance(d, dict):
                            out["food_config"] = d
                    except Exception:
                        pass
                if not out["food_boxes"]:
                    out["food_boxes"] = [
                        (int(r.x), int(r.y), int(r.z))
                        for r in db.query(m.MapArtFoodBox).filter(
                            m.MapArtFoodBox.task_id == self.task_id
                        ).order_by(m.MapArtFoodBox.sort_order).all()
                    ]
                # 睡觉点（任务级；per-bot 由 bot_sleep_point 覆盖）
                if task.sleep_x is not None and task.sleep_y is not None and task.sleep_z is not None:
                    out["sleep_point"] = (int(task.sleep_x), int(task.sleep_y), int(task.sleep_z))
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] load_task_config failed: %s", self.task_id, e)
        return out

    def bot_sleep_point(self, bot_id: str, fallback: Optional[tuple[int, int, int]] = None):
        """per-bot 睡觉点（mcc_bots.sleep_x/y/z 优先，回退任务级）。"""
        try:
            from vmtools_next.data.models.logistics import MccBotModel

            db = _session()
            try:
                row = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
                if row is not None and row.sleep_x is not None \
                        and row.sleep_y is not None and row.sleep_z is not None:
                    return (int(row.sleep_x), int(row.sleep_y), int(row.sleep_z))
            finally:
                db.close()
        except Exception:
            pass
        return fallback

    # ──────────────────────────────────────────
    # 放置结果落库（批量）
    # ──────────────────────────────────────────

    def flush_placed(self, updates: Iterable[tuple[int, int, int, str]], bot_id: str) -> int:
        """批量把「已放置（弱确认）」写库。

        ``updates`` = [(world_x, world_y, world_z, expected_block)]
        返回实际提交的行数；失败返回 0（世界状态仍可兜底，不阻断建造）。
        """
        rows = list(updates)
        if not rows:
            return 0
        now = datetime.now(timezone.utc)
        params = [
            {"b_x": int(x), "b_y": int(y), "b_z": int(z),
             "b_actual": str(bid).split("[")[0], "b_bot": bot_id, "b_now": now}
            for x, y, z, bid in rows
        ]
        try:
            from sqlalchemy import bindparam, update

            m = _models()
            tbl = m.MapArtBlockState
            stmt = (
                update(tbl)
                .where(tbl.task_id == self.task_id)
                .where(tbl.x == bindparam("b_x"))
                .where(tbl.y == bindparam("b_y"))
                .where(tbl.z == bindparam("b_z"))
                .values(placed=True, verified=False,
                        actual_block=bindparam("b_actual"),
                        placed_by_bot=bindparam("b_bot"),
                        placed_at=bindparam("b_now"),
                        verified_at=bindparam("b_now"))
            )
            db = _session()
            try:
                db.execute(stmt, params)  # executemany：一次往返提交全部行
                self._sync_task_counter(db)
                db.commit()
            finally:
                db.close()
            return len(params)
        except Exception as e:
            logger.warning("[%s] flush_placed failed (%d rows): %s", self.task_id, len(params), e)
            return 0

    def _sync_task_counter(self, db) -> None:
        """同步 map_art_tasks.placed_blocks 聚合计数（索引 COUNT，毫秒级）。"""
        try:
            from sqlalchemy import func

            m = _models()
            task = db.query(m.MapArtTask).filter(m.MapArtTask.task_id == self.task_id).first()
            if task is None:
                return
            cnt = db.query(func.count()).select_from(m.MapArtBlockState).filter(
                m.MapArtBlockState.task_id == self.task_id,
                m.MapArtBlockState.placed.is_(True),
            ).scalar()
            task.placed_blocks = int(cnt or 0)
        except Exception as e:
            logger.debug("[%s] sync task counter failed: %s", self.task_id, e)

    # ──────────────────────────────────────────
    # 对账查询 / 状态收敛
    # ──────────────────────────────────────────

    def query_cells(
        self,
        world_bounds: tuple[int, int, int, int],
        *,
        placed_only: bool = True,
        unverified_only: bool = False,
        limit: Optional[int] = None,
    ) -> list[tuple[int, int, int, str, bool]]:
        """按世界坐标范围查格子 → [(x, y, z, expected, verified)]。

        ``world_bounds`` = (x_min, x_max, z_min, z_max)，含端点。
        """
        x0, x1, z0, z1 = world_bounds
        try:
            m = _models()
            db = _session()
            try:
                q = db.query(
                    m.MapArtBlockState.x, m.MapArtBlockState.y, m.MapArtBlockState.z,
                    m.MapArtBlockState.expected_block, m.MapArtBlockState.verified,
                ).filter(
                    m.MapArtBlockState.task_id == self.task_id,
                    m.MapArtBlockState.x >= x0, m.MapArtBlockState.x <= x1,
                    m.MapArtBlockState.z >= z0, m.MapArtBlockState.z <= z1,
                )
                if placed_only:
                    q = q.filter(m.MapArtBlockState.placed.is_(True))
                if unverified_only:
                    q = q.filter(m.MapArtBlockState.verified.is_(False))
                if limit:
                    q = q.limit(int(limit))
                return [(int(r[0]), int(r[1]), int(r[2]), str(r[3]), bool(r[4])) for r in q.all()]
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] query_cells failed: %s", self.task_id, e)
            return []

    def query_expected(self, world_bounds: tuple[int, int, int, int]) -> list[tuple[int, int, int, str]]:
        """范围内全部期望方块（不区分 placed）——任务级全量对账用。"""
        x0, x1, z0, z1 = world_bounds
        try:
            m = _models()
            db = _session()
            try:
                q = db.query(
                    m.MapArtBlockState.x, m.MapArtBlockState.y, m.MapArtBlockState.z,
                    m.MapArtBlockState.expected_block,
                ).filter(
                    m.MapArtBlockState.task_id == self.task_id,
                    m.MapArtBlockState.x >= x0, m.MapArtBlockState.x <= x1,
                    m.MapArtBlockState.z >= z0, m.MapArtBlockState.z <= z1,
                )
                return [(int(r[0]), int(r[1]), int(r[2]), str(r[3])) for r in q.all()]
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] query_expected failed: %s", self.task_id, e)
            return []

    def query_pending_columns(self, world_bounds: tuple[int, int, int, int]) -> Optional[list[int]]:
        """返回仍有未放置格的世界 X 列表（列池重建用）；查询失败返回 None。

        用 ``GROUP BY x HAVING COUNT(unplaced) > 0``，比拉全表轻得多。
        """
        x0, x1, z0, z1 = world_bounds
        try:
            from sqlalchemy import func

            m = _models()
            tbl = m.MapArtBlockState
            db = _session()
            try:
                rows = (
                    db.query(tbl.x)
                    .filter(
                        tbl.task_id == self.task_id,
                        tbl.x >= x0, tbl.x <= x1,
                        tbl.z >= z0, tbl.z <= z1,
                        tbl.placed.is_(False),
                    )
                    .group_by(tbl.x)
                    .all()
                )
                return sorted({int(r[0]) for r in rows})
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] query_pending_columns failed: %s", self.task_id, e)
            return None

    def mark_verified(self, coords: Iterable[tuple[int, int, int]]) -> int:
        return self._bulk_flag(coords, verified=True, placed=True)

    def mark_reset(self, coords: Iterable[tuple[int, int, int]]) -> int:
        return self._bulk_flag(coords, verified=False, placed=False, clear_actual=True)

    def _bulk_flag(self, coords: Iterable[tuple[int, int, int]], *,
                   verified: bool, placed: bool, clear_actual: bool = False) -> int:
        rows = [(int(x), int(y), int(z)) for x, y, z in coords]
        if not rows:
            return 0
        now = datetime.now(timezone.utc)
        params = [{"b_x": x, "b_y": y, "b_z": z, "b_now": now} for x, y, z in rows]
        try:
            from sqlalchemy import bindparam, update

            m = _models()
            tbl = m.MapArtBlockState
            values = {"verified": verified, "placed": placed, "verified_at": bindparam("b_now")}
            if clear_actual:
                values["actual_block"] = ""
            stmt = (
                update(tbl)
                .where(tbl.task_id == self.task_id)
                .where(tbl.x == bindparam("b_x"))
                .where(tbl.y == bindparam("b_y"))
                .where(tbl.z == bindparam("b_z"))
                .values(**values)
            )
            db = _session()
            try:
                db.execute(stmt, params)
                db.commit()
            finally:
                db.close()
            return len(params)
        except Exception as e:
            logger.warning("[%s] bulk flag update failed (%d rows): %s", self.task_id, len(rows), e)
            return 0

    def count_placed(self) -> int:
        try:
            from sqlalchemy import func

            m = _models()
            db = _session()
            try:
                return int(db.query(func.count()).select_from(m.MapArtBlockState).filter(
                    m.MapArtBlockState.task_id == self.task_id,
                    m.MapArtBlockState.placed.is_(True),
                ).scalar() or 0)
            finally:
                db.close()
        except Exception:
            return 0

    # ──────────────────────────────────────────
    # 任务状态 / 断点
    # ──────────────────────────────────────────

    def persist_status(self, status: str, reason: str = "",
                       only_if_running: bool = True) -> bool:
        try:
            m = _models()
            db = _session()
            try:
                task = db.query(m.MapArtTask).filter(m.MapArtTask.task_id == self.task_id).first()
                if task is None:
                    return False
                if only_if_running and task.status not in ("running", "paused"):
                    return False
                task.status = status
                if reason:
                    task.error_message = reason
                if status in ("completed", "failed", "cancelled"):
                    task.completed_at = datetime.now(timezone.utc)
                self._sync_task_counter(db)
                db.commit()
                return True
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] persist_status(%s) failed: %s", self.task_id, status, e)
            return False

    def save_progress(self, payload: dict) -> None:
        try:
            m = _models()
            db = _session()
            try:
                row = db.query(m.MapArtTaskProgress).filter(
                    m.MapArtTaskProgress.task_id == self.task_id).first()
                blob = json.dumps(payload, ensure_ascii=False)
                if row is None:
                    db.add(m.MapArtTaskProgress(task_id=self.task_id, progress_json=blob))
                else:
                    row.progress_json = blob
                    row.checkpoint_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] save_progress failed: %s", self.task_id, e)

    def load_progress(self) -> Optional[dict]:
        try:
            m = _models()
            db = _session()
            try:
                row = db.query(m.MapArtTaskProgress).filter(
                    m.MapArtTaskProgress.task_id == self.task_id).first()
                if row and row.progress_json:
                    return json.loads(row.progress_json)
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] load_progress failed: %s", self.task_id, e)
        return None
