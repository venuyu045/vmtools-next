"""Player tracking config management API.

Owner tracking data is stored in the database (player_tracking_owners table),
NOT in config.yaml, to survive git operations and cross-conversation syncs.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.config import get_config, reload_config
from vmtools_next.data.db import get_db, get_session_factory
from vmtools_next.data.models.player_tracking import PlayerTrackingOwnerModel
from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.deps import get_current_user, get_optional_user, require_admin
from vmtools_next.infra.logging import get_logger

logger = get_logger("player_tracking")

router = APIRouter(prefix="/api/player-tracking", tags=["player-tracking"])


class TrackOwnerOut(BaseModel):
    name: str
    qq_openid: str = ""
    track_players: list[str] = []


class PlayerTrackingOut(BaseModel):
    enabled: bool
    sentinel_instance: str
    owners: list[TrackOwnerOut]


# ── In-memory cache for config.runtime access ──
# The bluemap_monitor and mcc_process_manager read player_tracking config
# at runtime. We sync DB → config on every write.
def _sync_db_to_config() -> None:
    """Sync owners from DB into the live config, so runtime code sees them."""
    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.config import get_config as _cfg_get, TrackOwner
        owners_db = db.query(PlayerTrackingOwnerModel).all()
        owners = [
            TrackOwner(
                name=o.name,
                qq_openid=o.qq_openid,
                track_players=json.loads(o.track_players_json),
            )
            for o in owners_db
        ]
        # Mutate cached config in-place (don't clear cache)
        _cfg_get().player_tracking.owners = owners
    finally:
        db.close()


# ── Startup: migrate existing data from config.yaml → DB ──

def _migrate_from_config(db: Session) -> int:
    """One-time migration: copy owners from config.yaml into DB table.
    Returns count of migrated owners.

    ⚠️ 2026-10-20 审查修复（中等·GET 每次都用 config.yaml 覆盖 DB）：
      原实现由 GET /api/player-tracking **每次请求**调用，且对已存在的 owner
      **无条件**写回 config.yaml 的值：
          existing.qq_openid = o.qq_openid          # 空串也会覆盖
          existing.track_players_json = ...
      后果：只要 config.yaml 里还残留旧的 player_tracking.owners 段
      （升级前的配置文件、或用户手工保留），任何一次页面刷新（甚至访客访问）
      都会把用户在网页上做的解绑/改名/改追踪列表**回滚**成配置文件的值；
      若 config 里 qq_openid 为空串，DB 中的 QQ 绑定直接被清空 ——
      正是 2026-10-19 那次修复（S2/M3）想避免的场景，只是换了个入口。
      修复：
        ① 真正的"一次性"——DB 已有任何 owner 记录即视为已迁移，直接返回；
        ② 补值也只补**空字段**（qq_openid 为空才从 config 取），绝不覆盖已有值。
    """
    try:
        # ① 一次性闸门：DB 里已有数据说明迁移早已完成，不再从 config 回灌
        if db.query(PlayerTrackingOwnerModel).count() > 0:
            return 0

        cfg = get_config().player_tracking
        owners = cfg.owners
        if not owners:
            return 0

        migrated = 0
        for o in owners:
            existing = db.query(PlayerTrackingOwnerModel).filter(
                PlayerTrackingOwnerModel.name == o.name
            ).first()
            if existing:
                # ② 只补空值，绝不覆盖用户已在页面上修改过的内容
                if not existing.qq_openid and o.qq_openid:
                    existing.qq_openid = o.qq_openid
                if not existing.track_players_json:
                    existing.track_players_json = json.dumps(list(o.track_players), ensure_ascii=False)
            else:
                db.add(PlayerTrackingOwnerModel(
                    name=o.name,
                    qq_openid=o.qq_openid,
                    track_players_json=json.dumps(list(o.track_players), ensure_ascii=False),
                ))
                migrated += 1
        db.commit()
        if migrated:
            logger.info("Migrated {} player tracking owners from config.yaml to DB", migrated)
        return migrated
    except Exception:
        db.rollback()
        return 0


# ── API Endpoints ──

@router.get("", response_model=PlayerTrackingOut)
def get_player_tracking(
    user: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    cfg = get_config().player_tracking

    # Auto-migrate from config.yaml on first access
    _migrate_from_config(db)

    owners_db = db.query(PlayerTrackingOwnerModel).all()
    # 访客（未登录）不返回 QQ openid，避免泄露绑定标识。
    # ⚠️ 2026-10-19 审查修复：原实现返回 qq_openid="" ，而前端 PlayerAlertsView 会把
    #    拿到的 owners 原样 PUT 回来 → update_player_tracking 里 existing.qq_openid = ""
    #    直接把数据库里的 QQ 绑定**清空**（不可逆）。
    #    改为：访客不返回 owners 明细（空列表），只回 enabled/sentinel_instance；
    #    登录用户仍按原样返回完整 owners。
    if user is None:
        return PlayerTrackingOut(
            enabled=cfg.enabled,
            sentinel_instance=cfg.sentinel_instance,
            owners=[],
        )

    owners_out = [
        TrackOwnerOut(
            name=o.name,
            qq_openid=o.qq_openid or "",
            track_players=json.loads(o.track_players_json),
        )
        for o in owners_db
    ]

    return PlayerTrackingOut(
        enabled=cfg.enabled,
        sentinel_instance=cfg.sentinel_instance,
        owners=owners_out,
    )


@router.put("", response_model=PlayerTrackingOut)
def update_player_tracking(
    data: PlayerTrackingOut,
    user: UserModel = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Update config.yaml for enabled/sentinel_instance (these are server settings)
    #
    # ⚠️ 2026-10-20 审查修复（中等·破坏性写入）：
    #   原实现 yaml.safe_load 全量读 → 改两个键 → safe_dump **全量覆盖写回**。
    #   PyYAML 不保留注释与键顺序，于是运维在 config.yaml 里写的所有注释
    #   （包括「⚠️ 必须替换为随机密钥」「生产建议绝对路径」这类关键告警）
    #   会在**第一次保存上下线提醒设置时被整文件抹掉**，且不可逆。
    #   改为复用 config._replace_toplevel_section（save_mcc_config 已在用）：
    #   只重写 `player_tracking` 这一个顶层段，其余内容（含注释）逐字保留。
    from vmtools_next.config import _find_config_dir, _replace_toplevel_section
    from pathlib import Path
    import yaml
    config_path = Path(_find_config_dir()) / "config.yaml"
    text = config_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    section = raw.get("player_tracking") or {}
    section["enabled"] = data.enabled
    section["sentinel_instance"] = data.sentinel_instance
    new_block = yaml.safe_dump(
        {"player_tracking": section}, allow_unicode=True, default_flow_style=False, sort_keys=False,
    )
    config_path.write_text(_replace_toplevel_section(text, "player_tracking", new_block), encoding="utf-8")
    reload_config()

    # Update owners in DB
    existing_names = {o.name for o in db.query(PlayerTrackingOwnerModel).all()}
    incoming_names = set()

    for o_in in data.owners:
        incoming_names.add(o_in.name)
        existing = db.query(PlayerTrackingOwnerModel).filter(
            PlayerTrackingOwnerModel.name == o_in.name
        ).first()
        if existing:
            # ⚠️ 2026-10-19 审查修复（中等·数据一致性）：
            #   原先无条件 existing.qq_openid = o_in.qq_openid。
            #   若前端拿到的 owners 里 qq_openid 是空串（访客态加载 / 加载失败后
            #   残留的空值 / 手工构造的 PUT），会把数据库中的 QQ 绑定**静默清空**，
            #   且不可逆（无法从别处恢复）。
            #   改为：仅当传入值非空时才更新；传空串视为「不修改」。
            #   需要解绑 QQ 的场景请走成员管理/QQ 绑定接口，不在本接口隐式完成。
            if (o_in.qq_openid or "").strip():
                existing.qq_openid = o_in.qq_openid
            existing.track_players_json = json.dumps(o_in.track_players, ensure_ascii=False)
        else:
            db.add(PlayerTrackingOwnerModel(
                name=o_in.name,
                qq_openid=o_in.qq_openid,
                track_players_json=json.dumps(o_in.track_players, ensure_ascii=False),
            ))

    # Remove owners no longer in the list
    removed = existing_names - incoming_names
    if removed:
        db.query(PlayerTrackingOwnerModel).filter(
            PlayerTrackingOwnerModel.name.in_(removed)
        ).delete(synchronize_session=False)

    db.commit()

    # Sync into runtime config
    _sync_db_to_config()

    return data
