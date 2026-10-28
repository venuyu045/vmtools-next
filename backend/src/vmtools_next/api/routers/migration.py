"""Data migration API routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from vmtools_next.api.deps import get_current_user, require_site_admin

router = APIRouter(prefix="/api/migration", tags=["migration"])


def _guard_path(raw: str, *, must_exist: bool, what: str) -> Path:
    """把迁移用的路径限制在**配置目录**内，防任意文件读/写。

    ⚠️ 2026-10-20 审查修复（中等·任意路径读 + 任意路径写）：
      原实现直接把请求参数交给 ConfigMigrator：
        · `json_path` 无任何约束 → 可读服务器上任意 JSON（/etc/...、其他应用配置），
          并通过"迁移成功/失败"做文件存在性探测；
        · `yaml_path` 可写**任意可执行位置** → 例如 `yaml_path=../static/index.html`
          即可覆盖前端入口植入 <script>（存储型 XSS / 挂马），或覆盖 .env、
          代码文件、systemd unit —— 权限面远大于"改配置"本身。
      修复：两个路径都必须 resolve() 后落在 config 目录内（与
      mcc_file_service._resolve 同款 `is_relative_to` 校验）。
    """
    from vmtools_next.config import get_config_dir

    root = Path(get_config_dir()).resolve()
    target = Path(raw).expanduser().resolve()
    try:
        inside = target.is_relative_to(root)
    except AttributeError:  # Python < 3.9 兜底
        inside = str(target).startswith(str(root) + "/")
    if not inside:
        raise HTTPException(
            status_code=400,
            detail=f"{what} 必须位于配置目录 {root} 内（防任意文件读写）",
        )
    if must_exist and not target.is_file():
        raise HTTPException(status_code=400, detail=f"{what} 不存在：{target}")
    return target


class MigrationStatus(BaseModel):
    config_migrated: bool = False
    warehouses_migrated: bool = False
    profiles_migrated: bool = False


@router.get("/status", response_model=MigrationStatus)
def get_migration_status(user=Depends(get_current_user)):
    """Get migration status."""
    return MigrationStatus()


@router.post("/config")
def migrate_config(json_path: str, yaml_path: str = "config/config.yaml",
                    user=Depends(require_site_admin)):
    """Migrate Java config to YAML（路径限制在配置目录内，见 _guard_path）。"""
    from vmtools_next.data.migration import ConfigMigrator
    src = _guard_path(json_path, must_exist=True, what="json_path")
    dst = _guard_path(yaml_path, must_exist=False, what="yaml_path")
    success = ConfigMigrator.migrate(str(src), str(dst))
    if success:
        return {"status": "migrated", "source": str(src), "target": str(dst)}
    raise HTTPException(500, "Migration failed")


@router.post("/warehouses")
def migrate_warehouses(json_path: str, user=Depends(require_site_admin)):
    """Migrate Java warehouses to database（路径限制在配置目录内）。"""
    from vmtools_next.data.migration import WarehouseMigrator
    from vmtools_next.data.db import get_session_factory
    src = _guard_path(json_path, must_exist=True, what="json_path")
    Session = get_session_factory()
    db = Session()
    try:
        count = WarehouseMigrator.migrate(str(src), db, None)
        return {"status": "migrated", "count": count}
    finally:
        db.close()
