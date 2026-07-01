"""Audit logging for MCC remote management."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from vmtools_next.core.mcc_security import dumps_masked
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccAuditLogModel


class MccAuditLogService:
    """Persist audit events without leaking secrets."""

    def log(
        self,
        db: Session,
        *,
        user: UserModel | None,
        action: str,
        resource_type: str = "instance",
        instance_id: str | None = None,
        resource_path: str | None = None,
        before: Any = None,
        after: Any = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        entry = MccAuditLogModel(
            user_id=user.id if user else None,
            organization_id=user.organization_id if user else None,
            instance_id=instance_id,
            action=action,
            resource_type=resource_type,
            resource_path=resource_path,
            before_json=dumps_masked(before) if before is not None else None,
            after_json=dumps_masked(after) if after is not None else None,
            success=success,
            error_message=error_message,
        )
        db.add(entry)
