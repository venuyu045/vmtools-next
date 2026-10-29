"""fashion: identity / catalog / loadout / asset

时装系统（VMFashion mod）四张表。**幂等**：``init_db()`` 的 ``create_all`` 可能
已经建过同名表（开发机直接跑 main.py 时），所以先探测再建，重复执行不会炸。

Revision ID: 20261028_fashion
Revises: (无 —— 仓库此前没有 alembic 版本，首个迁移)
Create Date: 2026-10-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20261028_fashion"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = (
    "fashion_identity",
    "fashion_catalog",
    "fashion_loadout",
    "fashion_asset",
)


def _existing_tables() -> set[str]:
    """当前库里已存在的表名（拿不到时返回空集合 → 按「全新建表」处理）。"""
    try:
        bind = op.get_bind()
        return set(sa.inspect(bind).get_table_names())
    except Exception:  # pragma: no cover - 极端降级路径
        return set()


def upgrade() -> None:
    existing = _existing_tables()

    if "fashion_identity" not in existing:
        op.create_table(
            "fashion_identity",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mc_uuid", sa.String(), nullable=False),
            sa.Column("mc_name", sa.String(), nullable=False),
            sa.Column("auth_type", sa.String(), nullable=False, server_default="mojang"),
            sa.Column("auth_server", sa.String(), nullable=False, server_default=""),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_fashion_identity_mc_uuid", "fashion_identity", ["mc_uuid"], unique=True)
        op.create_index("ix_fashion_identity_mc_name", "fashion_identity", ["mc_name"])
        op.create_index("ix_fashion_identity_user_id", "fashion_identity", ["user_id"])

    if "fashion_catalog" not in existing:
        op.create_table(
            "fashion_catalog",
            sa.Column("cosmetic_id", sa.String(), primary_key=True),
            sa.Column("pack_id", sa.String(), nullable=False, server_default=""),
            sa.Column("name", sa.String(), nullable=False, server_default=""),
            sa.Column("category", sa.String(), nullable=False, server_default="other"),
            sa.Column("asset_key", sa.String(), nullable=False, server_default=""),
            sa.Column("sha256", sa.String(), nullable=False, server_default=""),
            sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_fashion_catalog_pack_id", "fashion_catalog", ["pack_id"])
        op.create_index("ix_fashion_catalog_category", "fashion_catalog", ["category"])
        op.create_index("ix_fashion_catalog_asset_key", "fashion_catalog", ["asset_key"])
        op.create_index("ix_fashion_catalog_enabled", "fashion_catalog", ["enabled"])

    if "fashion_loadout" not in existing:
        op.create_table(
            "fashion_loadout",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "identity_id",
                sa.String(),
                sa.ForeignKey("fashion_identity.id"),
                nullable=False,
            ),
            sa.Column("slot", sa.String(), nullable=False),
            sa.Column("cosmetic_id", sa.String(), nullable=False),
            sa.Column("scale", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "identity_id", "slot", name="uq_fashion_loadout_identity_slot"
            ),
        )
        op.create_index("ix_fashion_loadout_identity_id", "fashion_loadout", ["identity_id"])
        op.create_index(
            "ix_fashion_loadout_identity_slot", "fashion_loadout", ["identity_id", "slot"]
        )

    if "fashion_asset" not in existing:
        op.create_table(
            "fashion_asset",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("pack_id", sa.String(), nullable=False, server_default=""),
            sa.Column("version", sa.String(), nullable=False, server_default="1"),
            sa.Column("filename", sa.String(), nullable=False, server_default=""),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("storage_path", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_fashion_asset_pack_id", "fashion_asset", ["pack_id"])
        op.create_index("ix_fashion_asset_sha256", "fashion_asset", ["sha256"])


def downgrade() -> None:
    existing = _existing_tables()
    # 先删引用方（loadout → identity），再删被引用方
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
