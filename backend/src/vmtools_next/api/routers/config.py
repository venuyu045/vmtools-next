"""Configuration management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional

from vmtools_next.api.deps import get_current_user
from vmtools_next.config import get_config, reload_config, save_mcc_config
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.config")
router = APIRouter(prefix="/api/config", tags=["config"])

# ── 敏感字段脱敏（2026-10-20 审查修复·严重） ─────────────────────────────
# 背景：GET /api/config 与 POST /api/config/reload 直接返回 config.model_dump()，
# 其中包含 server.secret_key（JWT 签名密钥）、qqbot.app_secret、qq_connect.app_key
# 等明文凭据。虽然接口本身要求 site_admin，但：
#   ① 密钥一旦经由 HTTP 响应体回显，就会进入浏览器缓存 / 开发者工具 / 代理日志 /
#      前端 Pinia store（useConfigStore.config），泄露面被无谓放大；
#   ② JWT secret 泄露 = 任意用户可伪造 site_admin 令牌（全站接管）；
#   ③ QQ app_key / app_secret 泄露 = 第三方可冒充本站应用。
# 修复：统一脱敏后再返回，只回显「是否已配置」，不回显具体值。
# 需要修改密钥的场景请直接编辑 config.yaml 或设置 VMT_ 环境变量（后端不通过 API 回显）。
_SENSITIVE_PATHS: tuple[tuple[str, str], ...] = (
    ("server", "secret_key"),
    ("server", "database_url"),
    ("qqbot", "app_secret"),
    ("qq_connect", "app_key"),
)


def _mask_config_dump(dump: dict[str, Any]) -> dict[str, Any]:
    """把敏感字段替换为 ``******``（已配置）/ ``""``（未配置），保留键结构。"""
    result = dict(dump)
    for section, key in _SENSITIVE_PATHS:
        node = result.get(section)
        if not isinstance(node, dict) or key not in node:
            continue
        node = dict(node)
        value = node.get(key)
        node[key] = "******" if value else ""
        result[section] = node
    return result


def _require_site_admin(user=Depends(get_current_user)):
    """Dependency that requires site_admin role for config mutations."""
    if user.role != "site_admin":
        raise HTTPException(status_code=403, detail="Only site admin can modify configuration")
    return user


class MccConfigUpdate(BaseModel):
    instance_root: Optional[str] = None
    binary_path: Optional[str] = None
    launch_command: Optional[list[str]] = None
    instance_start_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    instance_end_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    max_instances: Optional[int] = Field(default=None, ge=1, le=100)
    log_retention_days: Optional[int] = Field(default=None, ge=1, le=365)


@router.get("")
def get_current_config(user=Depends(_require_site_admin)):
    """Get the current configuration（敏感字段已脱敏，见 _mask_config_dump）。"""
    config = get_config()
    return _mask_config_dump(config.model_dump())


@router.get("/mcc")
def get_mcc_config(user=Depends(_require_site_admin)):
    """Get MCC section of the configuration."""
    config = get_config()
    return config.mcc.model_dump()


@router.put("/mcc")
def update_mcc_config(data: MccConfigUpdate, user=Depends(_require_site_admin)):
    """Update MCC section in config.yaml. Requires site_admin."""
    try:
        config = save_mcc_config(
            instance_root=data.instance_root,
            binary_path=data.binary_path,
            launch_command=data.launch_command,
            instance_start_port=data.instance_start_port,
            instance_end_port=data.instance_end_port,
            max_instances=data.max_instances,
            log_retention_days=data.log_retention_days,
        )
        return {"status": "saved", "mcc": config.mcc.model_dump()}
    except Exception as e:
        logger.error("Failed to update MCC config: {}", e)
        raise HTTPException(status_code=500, detail="Failed to save configuration")


@router.post("/reload")
def reload(user=Depends(_require_site_admin)):
    """Reload configuration from files. Requires site_admin."""
    try:
        new_config = reload_config()
        return {"status": "reloaded", "config": _mask_config_dump(new_config.model_dump())}
    except Exception as e:
        logger.error("Failed to reload config: {}", e)
        raise HTTPException(status_code=500, detail="Failed to reload configuration")
