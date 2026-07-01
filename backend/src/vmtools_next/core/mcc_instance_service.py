"""Business service for MCC remote instances."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.schemas.mcc_instance import MccInstanceCreate, MccInstanceUpdate
from vmtools_next.config import get_config
from vmtools_next.core.mcc_port_allocator import MccPortAllocator
from vmtools_next.core.mcc_security import hash_secret
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccInstanceModel

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class MccInstanceService:
    """Create and maintain isolated MCC instance directories and records."""

    def __init__(self, port_allocator: MccPortAllocator | None = None):
        self.config = get_config().mcc
        self.port_allocator = port_allocator or MccPortAllocator()

    def list_instances(
        self,
        db: Session,
        user: UserModel,
        status: str | None = None,
    ) -> list[MccInstanceModel]:
        query = db.query(MccInstanceModel).filter(MccInstanceModel.deleted_at.is_(None))
        query = self._scope_query(query, user)
        if status:
            query = query.filter(MccInstanceModel.status == status)
        return query.order_by(MccInstanceModel.created_at.desc()).all()

    def get_instance(self, db: Session, user: UserModel, instance_id: str) -> MccInstanceModel:
        query = db.query(MccInstanceModel).filter(
            MccInstanceModel.instance_id == instance_id,
            MccInstanceModel.deleted_at.is_(None),
        )
        query = self._scope_query(query, user)
        instance = query.first()
        if not instance:
            raise HTTPException(status_code=404, detail="MCC instance not found")
        return instance

    def create_instance(self, db: Session, user: UserModel, data: MccInstanceCreate) -> MccInstanceModel:
        running_count = db.query(MccInstanceModel).filter(MccInstanceModel.deleted_at.is_(None)).count()
        if running_count >= self.config.max_instances:
            raise HTTPException(status_code=400, detail=f"MCC instance limit reached: {self.config.max_instances}")

        slug = data.slug.strip().lower()
        if not SLUG_RE.fullmatch(slug):
            raise HTTPException(status_code=400, detail="Invalid MCC instance slug")
        existing = db.query(MccInstanceModel).filter(
            MccInstanceModel.slug == slug,
            MccInstanceModel.deleted_at.is_(None),
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="MCC instance slug already exists")

        root = Path(self.config.instance_root).resolve()
        instance_dir = (root / slug).resolve()
        self._ensure_inside_root(root, instance_dir)
        instance_dir.mkdir(parents=True, exist_ok=False)
        (instance_dir / "logs").mkdir(parents=True, exist_ok=True)

        instance_id = str(uuid.uuid4())
        token = uuid.uuid4().hex
        mcp_port = self.port_allocator.allocate(db)
        binary_path = self._prepare_binary(instance_dir, data.binary_mode)
        launch_command = self._build_launch_command(binary_path)

        ini_path = instance_dir / "MinecraftClient.ini"
        if not ini_path.exists():
            ini_path.write_text(
                self._render_default_ini(data, mcp_port),
                encoding="utf-8",
            )

        instance = MccInstanceModel(
            instance_id=instance_id,
            slug=slug,
            display_name=data.display_name or slug,
            bot_id=data.bot_id,
            instance_dir=str(instance_dir),
            binary_mode=data.binary_mode,
            mcc_binary_path=str(binary_path) if binary_path else "",
            launch_command_json=json.dumps(launch_command, ensure_ascii=False),
            status="created",
            desired_state="stopped",
            mcp_port=mcp_port,
            mcp_auth_token_hash=hash_secret(token),
            mcp_auth_token_secret=token,
            mcp_auth_token_env=self.config.mcp_auth_token_env,
            mc_username=data.mc_username,
            mc_server_host=data.mc_server_host,
            mc_server_port=data.mc_server_port,
            mc_version=data.mc_version,
            organization_id=user.organization_id,
            created_by=user.id,
        )
        db.add(instance)
        return instance

    def update_instance(
        self,
        db: Session,
        user: UserModel,
        instance_id: str,
        data: MccInstanceUpdate,
    ) -> MccInstanceModel:
        instance = self.get_instance(db, user, instance_id)
        payload = data.model_dump(exclude_unset=True)
        for key, value in payload.items():
            setattr(instance, key, value)
        return instance

    def _scope_query(self, query, user: UserModel):
        if user.role == "site_admin":
            return query
        return query.filter(MccInstanceModel.organization_id == user.organization_id)

    def _prepare_binary(self, instance_dir: Path, binary_mode: str) -> Path | None:
        source = Path(self.config.binary_path).expanduser()
        if not str(source):
            return None
        source = source.resolve()
        target = instance_dir / source.name
        if target.exists():
            return target
        if not source.exists():
            return source
        if binary_mode == "copy":
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return target
        if binary_mode == "symlink":
            try:
                os.symlink(source, target, target_is_directory=source.is_dir())
                return target
            except OSError:
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
                return target
        return source

    def _build_launch_command(self, binary_path: Path | None) -> list[str]:
        template = list(self.config.launch_command)
        binary = str(binary_path) if binary_path else self.config.binary_path
        if template:
            return [part.replace("{binary}", binary) for part in template]
        suffix = Path(binary).suffix.lower()
        if suffix == ".dll":
            return ["dotnet", binary]
        if suffix == ".exe":
            return ["mono", binary]
        return [binary]

    def _render_default_ini(self, data: MccInstanceCreate, mcp_port: int) -> str:
        lines = [
            "[Main]",
            f"login={data.mc_username or data.slug}",
            "password=",
            f"serverip={data.mc_server_host}",
            f"serverport={data.mc_server_port}",
            f"mcversion={data.mc_version}",
            "",
            "[MCP]",
            "enabled=true",
            f"host=127.0.0.1",
            f"port={mcp_port}",
            f"auth_token_env={self.config.mcp_auth_token_env}",
            "",
        ]
        return "\n".join(lines)

    def _ensure_inside_root(self, root: Path, path: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Instance path escapes MCC root") from exc
