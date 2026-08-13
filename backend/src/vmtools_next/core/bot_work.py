"""Bot 手动工作标记 — 统一辅助（2026-08-13 任务管理）。

mcc_bots 表新增 manual_working / manual_task_name 两列（跨上下线保持）：
- 用户可在「任务管理」页自定义 bot 当前在干什么（工作名称 + 是否工作中）
- 被手动标记「工作中」的 MF bot 不会被自动调度派活（地图画/物流/扫描入口统一拦截）
- 当前工作判定（状态页/任务中心）里手动标记优先级最高
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from vmtools_next.infra.logging import get_logger

logger = get_logger("bot_work")


def get_manual_work(db: Session, bot_id: str) -> Optional[dict]:
    """读取 bot 的手动工作标记；未标记（未工作时）返回 None。"""
    from vmtools_next.data.models.logistics import MccBotModel
    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if bot is None:
        return None
    if not getattr(bot, "manual_working", False):
        return None
    name = (getattr(bot, "manual_task_name", "") or "").strip()
    return {
        "working": True,
        "name": name or "手动工作",
    }


def set_manual_work(db: Session, bot_id: str, working: bool, name: str = "") -> dict:
    """写入 bot 的手动工作标记。

    working=True 时 name 必填（为空抛 ValueError，任务管理页必须填工作名称）。
    返回保存后的标记。
    """
    from vmtools_next.data.models.logistics import MccBotModel
    name = (name or "").strip()
    if working and not name:
        raise ValueError("工作名称不能为空")
    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if bot is None:
        raise LookupError(f"Bot 不存在: {bot_id}")
    bot.manual_working = bool(working)
    bot.manual_task_name = name if working else ""
    db.commit()
    logger.info("Manual work for {} set: working={}, name={}", bot_id, bool(working), name)
    return {
        "bot_id": bot_id,
        "working": bool(working),
        "name": name,
    }


def is_manually_busy(db: Session, bot_id: str) -> bool:
    """该 bot 是否被手动标记为「工作中」。"""
    return get_manual_work(db, bot_id) is not None


def ensure_available_for_work(db: Session, bot_id: str, module: str) -> Optional[str]:
    """调度/派活前校验：被手动标记「工作中」则返回错误消息（None=可用）。

    ``module``：调用模块名（地图画/物流/仓库扫描…），用于错误提示。
    各模块入口（创建/启动/动态分配/入队）调用：:

        err = ensure_available_for_work(db, bot_id, "地图画")
        if err:
            raise HTTPException(400, err)
    """
    mw = get_manual_work(db, bot_id)
    if mw is None:
        return None
    return (
        f"Bot {bot_id} 已被手动标记为工作中（{mw.get('name')}），"
        f"{module}不会派活给它，请先在「任务管理」解除标记"
    )