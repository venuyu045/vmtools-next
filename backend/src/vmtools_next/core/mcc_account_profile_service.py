"""Reusable MCC account profile service."""
from __future__ import annotations

import uuid
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.schemas.mcc_instance import (
    MccAccountConfigUpdate,
    MccAccountProfileCreate,
    MccAccountProfileUpdate,
)
from vmtools_next.core.mcc_security import protect_secret, reveal_secret
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccAccountProfileModel


class MccAccountProfileService:
    """Manage reusable account metadata without returning cleartext secrets."""

    def list_profiles(self, db: Session, user: UserModel) -> list[MccAccountProfileModel]:
        query = db.query(MccAccountProfileModel)
        query = self._scope_query(query, user)
        return query.order_by(MccAccountProfileModel.created_at.desc()).all()

    def get_profile(self, db: Session, user: UserModel, profile_id: str) -> MccAccountProfileModel:
        query = db.query(MccAccountProfileModel).filter(MccAccountProfileModel.profile_id == profile_id)
        query = self._scope_query(query, user)
        profile = query.first()
        if not profile:
            raise HTTPException(status_code=404, detail="MCC account profile not found")
        return profile

    def create_profile(self, db: Session, user: UserModel, data: MccAccountProfileCreate) -> MccAccountProfileModel:
        profile = MccAccountProfileModel(
            profile_id=str(uuid.uuid4()),
            name=data.name,
            auth_type=data.auth_type,
            username=data.username,
            password_secret=self._encode_secret(data.password),
            auth_server_url=data.auth_server_url or None,
            auth_api_path=data.auth_api_path or None,
            authlib_injector_path=data.authlib_injector_path or None,
            mc_server_host=data.mc_server_host,
            mc_server_port=data.mc_server_port,
            mc_version=data.mc_version,
            organization_id=user.organization_id,
        )
        db.add(profile)
        return profile

    def update_profile(
        self,
        db: Session,
        user: UserModel,
        profile_id: str,
        data: MccAccountProfileUpdate,
    ) -> MccAccountProfileModel:
        profile = self.get_profile(db, user, profile_id)
        payload = data.model_dump(exclude_unset=True)
        if "password" in payload:
            password = payload.pop("password")
            if password not in (None, "", "******"):
                profile.password_secret = self._encode_secret(password)
        if payload.pop("clear_password", False):
            profile.password_secret = None
        for field in self._updatable_fields():
            if field in payload:
                value = payload[field]
                if field in {"auth_server_url", "auth_api_path", "authlib_injector_path"} and value == "":
                    value = None
                setattr(profile, field, value)
        return profile

    def delete_profile(self, db: Session, user: UserModel, profile_id: str) -> None:
        profile = self.get_profile(db, user, profile_id)
        db.delete(profile)

    def to_config_update(self, profile: MccAccountProfileModel) -> MccAccountConfigUpdate:
        return MccAccountConfigUpdate(
            auth_type=profile.auth_type,
            username=profile.username,
            password=self._decode_secret(profile.password_secret),
            auth_server_url=profile.auth_server_url or "",
            auth_api_path=profile.auth_api_path or "",
            authlib_injector_path=profile.authlib_injector_path or "",
            mc_server_host=profile.mc_server_host,
            mc_server_port=profile.mc_server_port,
            mc_version=profile.mc_version,
        )

    def to_response(self, profile: MccAccountProfileModel) -> dict:
        return {
            "profile_id": profile.profile_id,
            "name": profile.name,
            "auth_type": profile.auth_type,
            "username": profile.username,
            "password_set": bool(profile.password_secret),
            "auth_server_url": profile.auth_server_url,
            "auth_api_path": profile.auth_api_path,
            "authlib_injector_path": profile.authlib_injector_path,
            "mc_server_host": profile.mc_server_host,
            "mc_server_port": profile.mc_server_port,
            "mc_version": profile.mc_version,
            "last_login_name": profile.last_login_name,
            "organization_id": profile.organization_id,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    def _scope_query(self, query, user: UserModel):
        if user.role == "site_admin":
            return query
        return query.filter(MccAccountProfileModel.organization_id == user.organization_id)

    def _updatable_fields(self) -> Iterable[str]:
        return (
            "name",
            "auth_type",
            "username",
            "auth_server_url",
            "auth_api_path",
            "authlib_injector_path",
            "mc_server_host",
            "mc_server_port",
            "mc_version",
        )

    def _encode_secret(self, value: str | None) -> str | None:
        return protect_secret(value)

    def _decode_secret(self, value: str | None) -> str | None:
        return reveal_secret(value)
