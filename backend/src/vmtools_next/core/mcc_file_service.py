"""Safe file and account config services for MCC instance directories."""
from __future__ import annotations

import base64
import configparser
import difflib
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.schemas.mcc_instance import (
    MccAccountConfigUpdate,
    MccDirectoryCreateRequest,
    MccFileCreateRequest,
    MccFileRenameRequest,
    MccFileWriteRequest,
)
from vmtools_next.core.mcc_security import mask_text, SECRET_VALUE_RE
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccFileSnapshotModel, MccInstanceModel

TEXT_EXTENSIONS = {
    ".ini",
    ".txt",
    ".json",
    ".log",
    ".conf",
    ".cfg",
    ".yaml",
    ".yml",
    ".properties",
    ".md",
    ".csv",
    ".xml",
    ".toml",
}


@dataclass
class MccFileContent:
    relative_path: str
    content: str
    encoding: str
    size: int
    language: str
    masked: bool
    updated_at: float


class MccFileService:
    """Read and mutate files inside an MCC instance directory only."""

    def __init__(self, max_read_bytes: int = 512 * 1024, max_write_bytes: int = 1024 * 1024):
        self.max_read_bytes = max_read_bytes
        self.max_write_bytes = max_write_bytes

    def list_files(self, instance: MccInstanceModel, relative_path: str = "") -> list[dict[str, Any]]:
        root = self._root(instance)
        target = self._resolve(root, relative_path, allow_missing=False)
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        items: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            try:
                stat = child.stat()
                child_relative = child.relative_to(root).as_posix()
                items.append(
                    {
                        "name": child.name,
                        "path": child_relative,
                        "type": "directory" if child.is_dir() else "file",
                        "size": stat.st_size,
                        "updated_at": stat.st_mtime,
                        "editable": child.is_file() and self._looks_text_file(child),
                        "downloadable": child.is_file(),
                        "language": self._language_for(child) if child.is_file() else "directory",
                    }
                )
            except OSError:
                continue
        return items

    def list_tree(self, instance: MccInstanceModel, relative_path: str = "") -> list[dict[str, Any]]:
        root = self._root(instance)
        target = self._resolve(root, relative_path, allow_missing=False)
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        return [self._build_tree_node(root, child) for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))]

    def breadcrumbs(self, instance: MccInstanceModel, relative_path: str = "") -> list[dict[str, str]]:
        root = self._root(instance)
        target = self._resolve(root, relative_path, allow_missing=False)
        crumbs = [{"name": "root", "path": ""}]
        if target == root:
            return crumbs
        current = []
        for part in target.relative_to(root).parts:
            current.append(part)
            crumbs.append({"name": part, "path": "/".join(current)})
        return crumbs

    def read_file(self, instance: MccInstanceModel, relative_path: str) -> MccFileContent:
        root = self._root(instance)
        path = self._resolve(root, relative_path, allow_missing=False)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        size = path.stat().st_size
        if size > self.max_read_bytes:
            raise HTTPException(status_code=413, detail="File is too large to edit online")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise HTTPException(status_code=415, detail="Binary files cannot be edited online")

        content, encoding = self._decode(raw)
        masked_content = mask_text(content)
        return MccFileContent(
            relative_path=path.relative_to(root).as_posix(),
            content=masked_content,
            encoding=encoding,
            size=size,
            language=self._language_for(path),
            masked=masked_content != content,
            updated_at=path.stat().st_mtime,
        )

    def write_file(
        self,
        db: Session,
        instance: MccInstanceModel,
        user: UserModel,
        data: MccFileWriteRequest,
    ) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, data.path, allow_missing=False)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if len(data.content.encode(data.encoding or "utf-8")) > self.max_write_bytes:
            raise HTTPException(status_code=413, detail="File is too large to save online")

        before = path.read_text(encoding=data.encoding or "utf-8")
        next_content = self._restore_masked_secrets(before, data.content)
        path.write_text(next_content, encoding=data.encoding or "utf-8", newline="\n")
        snapshot = self._save_snapshot(db, instance, user, path.relative_to(root).as_posix(), before, next_content)
        return {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "snapshot_id": snapshot.snapshot_id,
            "diff": snapshot.diff_text,
            "masked_secrets_preserved": next_content != data.content,
        }

    def create_file(self, instance: MccInstanceModel, data: MccFileCreateRequest) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, data.path, allow_missing=True)
        if path.exists() and not data.overwrite:
            raise HTTPException(status_code=409, detail="File already exists")
        if len(data.content.encode(data.encoding or "utf-8")) > self.max_write_bytes:
            raise HTTPException(status_code=413, detail="File is too large to create online")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data.content, encoding=data.encoding or "utf-8", newline="\n")
        return {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size}

    def create_directory(self, instance: MccInstanceModel, data: MccDirectoryCreateRequest) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, data.path, allow_missing=True)
        if path.exists() and not data.overwrite:
            raise HTTPException(status_code=409, detail="Directory already exists")
        path.mkdir(parents=True, exist_ok=True)
        return {"path": path.relative_to(root).as_posix(), "type": "directory"}

    def upload_base64(self, instance: MccInstanceModel, data: MccFileCreateRequest) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, data.path, allow_missing=True)
        if path.exists() and not data.overwrite:
            raise HTTPException(status_code=409, detail="File already exists")
        try:
            raw = base64.b64decode(data.content, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid base64 file content") from exc
        if len(raw) > self.max_write_bytes:
            raise HTTPException(status_code=413, detail="File is too large to upload online")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size}

    def read_binary(self, instance: MccInstanceModel, relative_path: str) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, relative_path, allow_missing=False)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        raw = path.read_bytes()
        if len(raw) > self.max_read_bytes * 4:
            raise HTTPException(status_code=413, detail="File is too large to download online")
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "path": path.relative_to(root).as_posix(),
            "name": path.name,
            "size": len(raw),
            "content_base64": encoded,
            "language": self._language_for(path),
            "download_name": path.name,
        }

    def delete_file(self, instance: MccInstanceModel, relative_path: str) -> dict[str, Any]:
        root = self._root(instance)
        path = self._resolve(root, relative_path, allow_missing=False)
        if path.is_dir():
            raise HTTPException(status_code=400, detail="Directory deletion is not supported online")
        path.unlink()
        return {"deleted": True, "path": relative_path}

    def rename_file(self, instance: MccInstanceModel, data: MccFileRenameRequest) -> dict[str, Any]:
        root = self._root(instance)
        source = self._resolve(root, data.source_path, allow_missing=False)
        target = self._resolve(root, data.target_path, allow_missing=True)
        if target.exists() and not data.overwrite:
            raise HTTPException(status_code=409, detail="Target file already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return {"source_path": data.source_path, "target_path": target.relative_to(root).as_posix()}

    def read_account_config(self, instance: MccInstanceModel) -> dict[str, Any]:
        ini_path = self._minecraft_ini(instance)
        parser = self._read_ini(ini_path)
        main = parser["Main"] if parser.has_section("Main") else {}
        auth = parser["Authentication"] if parser.has_section("Authentication") else {}
        mcp = parser["MCP"] if parser.has_section("MCP") else {}
        password = main.get("password", "") if hasattr(main, "get") else ""
        return {
            "auth_type": auth.get("type", "offline") if hasattr(auth, "get") else "offline",
            "username": main.get("login", instance.mc_username) if hasattr(main, "get") else instance.mc_username,
            "password_set": bool(password),
            "auth_server_url": auth.get("auth_server_url", "") if hasattr(auth, "get") else "",
            "auth_api_path": auth.get("auth_api_path", "") if hasattr(auth, "get") else "",
            "authlib_injector_path": auth.get("authlib_injector_path", "") if hasattr(auth, "get") else "",
            "mc_server_host": main.get("serverip", instance.mc_server_host) if hasattr(main, "get") else instance.mc_server_host,
            "mc_server_port": int(main.get("serverport", instance.mc_server_port) or 25565) if hasattr(main, "get") else instance.mc_server_port,
            "mc_version": main.get("mcversion", instance.mc_version) if hasattr(main, "get") else instance.mc_version,
            "mcp_port": int(mcp.get("port", instance.mcp_port) or instance.mcp_port) if hasattr(mcp, "get") else instance.mcp_port,
            "mcp_auth_token_env": mcp.get("auth_token_env", instance.mcp_auth_token_env) if hasattr(mcp, "get") else instance.mcp_auth_token_env,
        }

    def update_account_config(
        self,
        db: Session,
        instance: MccInstanceModel,
        user: UserModel,
        data: MccAccountConfigUpdate,
    ) -> dict[str, Any]:
        ini_path = self._minecraft_ini(instance)
        before = ini_path.read_text(encoding="utf-8") if ini_path.exists() else ""
        parser = self._read_ini(ini_path)
        for section in ("Main", "Authentication", "MCP"):
            if not parser.has_section(section):
                parser.add_section(section)

        parser.set("Authentication", "type", data.auth_type)
        parser.set("Main", "login", data.username)
        if data.password not in (None, "", "******"):
            parser.set("Main", "password", data.password)
        elif not parser.has_option("Main", "password"):
            parser.set("Main", "password", "")
        parser.set("Authentication", "auth_server_url", data.auth_server_url or "")
        parser.set("Authentication", "auth_api_path", data.auth_api_path or "")
        parser.set("Authentication", "authlib_injector_path", data.authlib_injector_path or "")
        parser.set("Main", "serverip", data.mc_server_host)
        parser.set("Main", "serverport", str(data.mc_server_port))
        parser.set("Main", "mcversion", data.mc_version)
        parser.set("MCP", "enabled", "true")
        parser.set("MCP", "host", instance.mcp_host or "127.0.0.1")
        parser.set("MCP", "port", str(instance.mcp_port))
        parser.set("MCP", "auth_token_env", instance.mcp_auth_token_env or "MCC_MCP_AUTH_TOKEN")

        ini_path.parent.mkdir(parents=True, exist_ok=True)
        with ini_path.open("w", encoding="utf-8", newline="\n") as file:
            parser.write(file)
        after = ini_path.read_text(encoding="utf-8")
        snapshot = self._save_snapshot(db, instance, user, "MinecraftClient.ini", before, after)

        instance.mc_username = data.username
        instance.mc_server_host = data.mc_server_host
        instance.mc_server_port = data.mc_server_port
        instance.mc_version = data.mc_version
        return {"config": self.read_account_config(instance), "snapshot_id": snapshot.snapshot_id, "diff": snapshot.diff_text}

    def _root(self, instance: MccInstanceModel) -> Path:
        root = Path(instance.instance_dir).resolve()
        if not root.exists():
            raise HTTPException(status_code=404, detail="MCC instance directory does not exist")
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="MCC instance path is not a directory")
        return root

    def _resolve(self, root: Path, relative_path: str, *, allow_missing: bool) -> Path:
        normalized = (relative_path or "").replace("\\", "/").strip("/")
        if normalized.startswith("../") or "/../" in normalized or normalized == "..":
            raise HTTPException(status_code=400, detail="Path traversal is not allowed")
        candidate = (root / normalized).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Path escapes MCC instance directory") from exc
        if not allow_missing and not candidate.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        return candidate

    def _looks_text_file(self, path: Path) -> bool:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return True
        try:
            sample = path.read_bytes()[:1024]
        except OSError:
            return False
        return b"\x00" not in sample

    def _decode(self, raw: bytes) -> tuple[str, str]:
        for encoding in ("utf-8", "utf-8-sig", "gbk"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=415, detail="Unsupported text encoding")

    def _build_tree_node(self, root: Path, path: Path) -> dict[str, Any]:
        node = {
            "name": path.name,
            "path": path.relative_to(root).as_posix(),
            "type": "directory" if path.is_dir() else "file",
            "children": [],
        }
        if path.is_dir():
            try:
                node["children"] = [
                    self._build_tree_node(root, child)
                    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
                    if child.is_dir()
                ]
            except OSError:
                node["children"] = []
        return node

    def _language_for(self, path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".ini": "ini",
            ".json": "json",
            ".log": "log",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".xml": "xml",
            ".toml": "toml",
        }.get(suffix, "text")

    def _restore_masked_secrets(self, before: str, incoming: str) -> str:
        before_values: dict[str, str] = {}
        for match in SECRET_VALUE_RE.finditer(before):
            before_values[match.group(1).strip().lower()] = match.group(2)

        def repl(match: re.Match[str]) -> str:
            prefix = match.group(1)
            value = match.group(2)
            key = prefix.strip().lower()
            if value.strip() == "******" and key in before_values:
                return f"{prefix}{before_values[key]}"
            return match.group(0)

        return SECRET_VALUE_RE.sub(repl, incoming)

    def _save_snapshot(
        self,
        db: Session,
        instance: MccInstanceModel,
        user: UserModel,
        relative_path: str,
        before: str,
        after: str,
    ) -> MccFileSnapshotModel:
        diff = "\n".join(
            difflib.unified_diff(
                mask_text(before).splitlines(),
                mask_text(after).splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        snapshot = MccFileSnapshotModel(
            snapshot_id=str(uuid.uuid4()),
            instance_id=instance.instance_id,
            relative_path=relative_path,
            content_hash_before=hashlib.sha256(before.encode("utf-8")).hexdigest(),
            content_hash_after=hashlib.sha256(after.encode("utf-8")).hexdigest(),
            diff_text=diff,
            created_by=user.id,
        )
        db.add(snapshot)
        return snapshot

    def _minecraft_ini(self, instance: MccInstanceModel) -> Path:
        root = self._root(instance)
        return self._resolve(root, "MinecraftClient.ini", allow_missing=True)

    def _read_ini(self, path: Path) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        parser.optionxform = str.lower
        if path.exists():
            parser.read(path, encoding="utf-8")
        return parser
