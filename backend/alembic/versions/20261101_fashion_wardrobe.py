"""fashion: wardrobe（我的衣柜收藏）

「我的衣柜」收藏表：玩家在商店页主动「加入衣柜」的时装才出现在衣柜页。

**幂等**：``init_db()`` 的 ``create_all`` 可能已经建过同名表（开发机直接跑
main.py 时），所以先探测再建，重复执行不会炸。

Revision ID: 20261101_fashion_wardrobe
Revises: 20261028_fashion
Create Date: 2026-11-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20261101_fashion_wardrobe"
down_revision = "20261028_fashion"
branch_labels = None
depends_on = None

_TABLE = "fashion_wardrobe"


def _existing_tables() -> set[str]:
    """当前库里已存在的表名（拿不到时返回空集合 → 按「全新建表」处理）。"""
    try:
        bind = op.get_bind()
        return set(sa.inspect(bind).get_table_names())
    except Exception:  # pragma: no cover - 极端降级路径
        return set()


def upgrade() -> None:
    existing = _existing_tables()

    if _TABLE not in existing:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(), primary_key=True),
            # user 维度：衣柜跟网站账号走，一个账号绑定的多个 MC 身份共享同一份
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            # 故意不做外键：目录条目被删/下架后，玩家的收藏记录仍要保留
            # （否则「删目录」会静默清空所有人的衣柜，玩家连删都删不掉）。
            sa.Column("cosmetic_id", sa.String(), nullable=False),
            sa.Column("added_at", sa.DateTime(), nullable=False),
            # 同一用户同一件时装只有一条：重复「加入衣柜」靠唯一约束兜底
            sa.UniqueConstraint(
                "user_id", "cosmetic_id", name="uq_fashion_wardrobe_user_cosmetic"
            ),
        )
        op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])
        op.create_index(f"ix_{_TABLE}_cosmetic_id", _TABLE, ["cosmetic_id"])


def downgrade() -> None:
    if _TABLE in _existing_tables():
        op.drop_table(_TABLE)
