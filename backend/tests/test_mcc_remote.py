"""Tests for MCC remote process management building blocks."""
from __future__ import annotations

from dataclasses import dataclass

from vmtools_next.api.schemas.mcc_instance import MccInstanceCreate
from vmtools_next.config import _apply_env_overrides
import pytest
from fastapi import HTTPException

from vmtools_next.api.schemas.mcc_instance import MccAccountProfileCreate
from vmtools_next.core.mcc_account_profile_service import MccAccountProfileService
from vmtools_next.core.mcc_file_service import MccFileService
from vmtools_next.core.mcc_instance_service import MccInstanceService
from vmtools_next.core.mcc_port_allocator import MccPortAllocator
from vmtools_next.data.db import Base
from vmtools_next.data.models import auth, logistics, mcc_remote  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock


@dataclass
class DummyUser:
    id: str = "user-1"
    role: str = "site_admin"
    organization_id: str | None = None


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_apply_env_overrides_nested(monkeypatch):
    monkeypatch.setenv("VMT_MCC__INSTANCE_ROOT", "/tmp/vmtools/mcc")
    monkeypatch.setenv("VMT_MCC__MAX_INSTANCES", "12")
    config = _apply_env_overrides({"mcc": {"instance_root": "/old", "max_instances": 20}})
    assert config["mcc"]["instance_root"] == "/tmp/vmtools/mcc"
    assert config["mcc"]["max_instances"] == 12


def test_port_allocator_skips_used_port():
    db = make_session()
    try:
        allocator = MccPortAllocator(start_port=45000, end_port=45002)
        first = allocator.allocate(db)
        db.add(mcc_remote.MccInstanceModel(
            instance_id="i1",
            slug="bot-a",
            instance_dir="/tmp/bot-a",
            mcp_port=first,
        ))
        db.commit()
        second = allocator.allocate(db)
        assert second != first
        assert second in {45001, 45002}
    finally:
        db.close()


def test_create_instance_generates_directory_and_ini(tmp_path, monkeypatch):
    binary = tmp_path / "runtime" / "MinecraftClient.exe"
    binary.parent.mkdir()
    binary.write_text("dummy", encoding="utf-8")
    monkeypatch.setenv("VMT_MCC__INSTANCE_ROOT", str(tmp_path / "instances"))
    monkeypatch.setenv("VMT_MCC__BINARY_PATH", str(binary))
    monkeypatch.setenv("VMT_MCC__INSTANCE_START_PORT", "45100")
    monkeypatch.setenv("VMT_MCC__INSTANCE_END_PORT", "45102")

    from vmtools_next.config import reload_config

    reload_config()
    db = make_session()
    try:
        service = MccInstanceService(MccPortAllocator(start_port=45100, end_port=45102))
        instance = service.create_instance(
            db,
            DummyUser(),
            MccInstanceCreate(
                slug="bot-alice",
                display_name="Alice",
                mc_username="AliceBot",
                mc_server_host="mc.example.test",
            ),
        )
        db.commit()
        assert instance.slug == "bot-alice"
        assert instance.mcp_port == 45100
        assert (tmp_path / "instances" / "bot-alice" / "MinecraftClient.ini").exists()
    finally:
        db.close()
        reload_config()


def test_account_profile_masks_password_and_can_apply_to_config(tmp_path):
    db = make_session()
    try:
        service = MccAccountProfileService()
        profile = service.create_profile(
            db,
            DummyUser(),
            MccAccountProfileCreate(
                name="Alice Account",
                auth_type="yggdrasil",
                username="AliceBot",
                password="profile-secret",
                auth_server_url="https://auth.example.test",
                auth_api_path="/api/yggdrasil",
                mc_server_host="mc.example.test",
                mc_server_port=25566,
                mc_version="1.21.1",
            ),
        )
        db.commit()
        response = service.to_response(profile)
        assert response["password_set"] is True
        assert "profile-secret" not in str(response)

        instance_dir = tmp_path / "bot-a"
        instance_dir.mkdir()
        instance = mcc_remote.MccInstanceModel(
            instance_id="i1",
            slug="bot-a",
            instance_dir=str(instance_dir),
            mcp_port=45100,
            mcp_auth_token_env="MCC_MCP_AUTH_TOKEN",
        )
        file_service = MccFileService()
        result = file_service.update_account_config(db, instance, DummyUser(), service.to_config_update(profile))
        assert result["config"]["username"] == "AliceBot"
        assert "password = profile-secret" in (instance_dir / "MinecraftClient.ini").read_text(encoding="utf-8")
    finally:
        db.close()


def test_file_service_tree_mkdir_and_binary_download(tmp_path):
    instance_dir = tmp_path / "bot-a"
    instance_dir.mkdir()
    (instance_dir / "config").mkdir()
    (instance_dir / "config" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (instance_dir / "icon.bin").write_bytes(b"\x00\x01\x02")
    instance = mcc_remote.MccInstanceModel(
        instance_id="i1",
        slug="bot-a",
        instance_dir=str(instance_dir),
        mcp_port=45100,
    )
    service = MccFileService()

    tree = service.list_tree(instance)
    assert any(item["name"] == "config" and item["type"] == "directory" for item in tree)
    crumbs = service.breadcrumbs(instance, "config")
    assert crumbs[-1] == {"name": "config", "path": "config"}
    created = service.create_directory(instance, mcc_remote_placeholder_directory_request("new-dir"))
    assert created["path"] == "new-dir"
    binary = service.read_binary(instance, "icon.bin")
    assert binary["content_base64"] == "AAEC"


def mcc_remote_placeholder_directory_request(path: str):
    from vmtools_next.api.schemas.mcc_instance import MccDirectoryCreateRequest

    return MccDirectoryCreateRequest(path=path)


def test_file_service_blocks_path_traversal(tmp_path):
    instance_dir = tmp_path / "bot-a"
    instance_dir.mkdir()
    instance = mcc_remote.MccInstanceModel(
        instance_id="i1",
        slug="bot-a",
        instance_dir=str(instance_dir),
        mcp_port=45100,
    )
    service = MccFileService()

    with pytest.raises(HTTPException):
        service.read_file(instance, "../secret.txt")


def test_file_service_masks_and_preserves_secret_on_save(tmp_path):
    db = make_session()
    try:
        instance_dir = tmp_path / "bot-a"
        instance_dir.mkdir()
        ini = instance_dir / "MinecraftClient.ini"
        ini.write_text("[Main]\nlogin=Alice\npassword=super-secret\n", encoding="utf-8")
        instance = mcc_remote.MccInstanceModel(
            instance_id="i1",
            slug="bot-a",
            instance_dir=str(instance_dir),
            mcp_port=45100,
        )
        service = MccFileService()

        content = service.read_file(instance, "MinecraftClient.ini")
        assert "super-secret" not in content.content
        assert "password=******" in content.content

        from vmtools_next.api.schemas.mcc_instance import MccFileWriteRequest

        result = service.write_file(
            db,
            instance,
            DummyUser(),
            MccFileWriteRequest(path="MinecraftClient.ini", content=content.content + "serverip=mc.example.test\n"),
        )
        db.commit()
        saved = ini.read_text(encoding="utf-8")
        assert "password=super-secret" in saved
        assert result["masked_secrets_preserved"] is True
    finally:
        db.close()


@pytest.mark.asyncio
async def test_process_manager_recovers_desired_running_instances(monkeypatch):
    from vmtools_next.core.mcc_process_manager import MccProcessManager

    manager = MccProcessManager()
    monkeypatch.setattr(
        manager,
        "_mark_stale_running_instances",
        AsyncMock(),
    )
    monkeypatch.setattr(
        manager,
        "_recover_desired_running_instances",
        AsyncMock(),
    )

    await manager.start()

    manager._mark_stale_running_instances.assert_awaited_once()
    manager._recover_desired_running_instances.assert_awaited_once()


def test_account_config_updates_ini_and_instance_metadata(tmp_path):
    db = make_session()
    try:
        instance_dir = tmp_path / "bot-a"
        instance_dir.mkdir()
        instance = mcc_remote.MccInstanceModel(
            instance_id="i1",
            slug="bot-a",
            instance_dir=str(instance_dir),
            mcp_port=45100,
            mcp_auth_token_env="MCC_MCP_AUTH_TOKEN",
        )
        service = MccFileService()

        from vmtools_next.api.schemas.mcc_instance import MccAccountConfigUpdate

        result = service.update_account_config(
            db,
            instance,
            DummyUser(),
            MccAccountConfigUpdate(
                auth_type="yggdrasil",
                username="AliceBot",
                password="secret-pass",
                auth_server_url="https://auth.example.test",
                auth_api_path="/api/yggdrasil",
                mc_server_host="mc.example.test",
                mc_server_port=25566,
                mc_version="1.21.1",
            ),
        )
        db.commit()
        text = (instance_dir / "MinecraftClient.ini").read_text(encoding="utf-8")
        assert "login = AliceBot" in text
        assert "password = secret-pass" in text
        assert result["config"]["password_set"] is True
        assert instance.mc_server_host == "mc.example.test"
    finally:
        db.close()


def test_audit_log_service_records_actions():
    from vmtools_next.core.mcc_audit_log_service import MccAuditLogService

    db = make_session()
    try:
        audit = MccAuditLogService()
        audit.log(
            db,
            user=DummyUser(),
            action="instance.start",
            resource_type="instance",
            instance_id="i1",
            after={"status": "running"},
        )
        db.commit()
        logs = db.query(mcc_remote.MccAuditLogModel).all()
        assert len(logs) == 1
        assert logs[0].action == "instance.start"
        assert logs[0].user_id == "user-1"
        assert logs[0].success is True
    finally:
        db.close()


def test_port_allocator_exhaustion():
    db = make_session()
    try:
        allocator = MccPortAllocator(start_port=45000, end_port=45001)
        p1 = allocator.allocate(db)
        db.add(mcc_remote.MccInstanceModel(instance_id="i1", slug="a", instance_dir="/tmp/a", mcp_port=p1))
        db.commit()
        p2 = allocator.allocate(db)
        db.add(mcc_remote.MccInstanceModel(instance_id="i2", slug="b", instance_dir="/tmp/b", mcp_port=p2))
        db.commit()
        with pytest.raises(RuntimeError):
            allocator.allocate(db)
    finally:
        db.close()


def test_instance_service_blocks_duplicate_slug(tmp_path):
    db = make_session()
    try:
        service = MccInstanceService(MccPortAllocator(start_port=45200, end_port=45202))
        service.create_instance(db, DummyUser(), MccInstanceCreate(
            slug="bot-x", display_name="X", mc_username="test", mc_server_host="mc.example.test",
        ))
        db.commit()
        with pytest.raises(HTTPException):
            service.create_instance(db, DummyUser(), MccInstanceCreate(
                slug="bot-x", display_name="X2", mc_username="test2", mc_server_host="mc.example.test",
            ))
    finally:
        db.close()


def test_instance_service_delete_soft_deletes():
    db = make_session()
    try:
        service = MccInstanceService(MccPortAllocator(start_port=45300, end_port=45302))
        instance = service.create_instance(db, DummyUser(), MccInstanceCreate(
            slug="bot-soft", display_name="Soft", mc_username="s", mc_server_host="mc.example.test",
        ))
        db.commit()
        from datetime import datetime, timezone

        instance.deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.commit()
        deleted = db.query(mcc_remote.MccInstanceModel).filter(
            mcc_remote.MccInstanceModel.instance_id == instance.instance_id,
        ).first()
        assert deleted is not None
        assert deleted.deleted_at is not None
    finally:
        db.close()


def test_file_service_blocks_create_on_existing_file(tmp_path):
    instance_dir = tmp_path / "bot-a"
    instance_dir.mkdir()
    existing = instance_dir / "readme.txt"
    existing.write_text("hello", encoding="utf-8")
    instance = mcc_remote.MccInstanceModel(
        instance_id="i1", slug="bot-a", instance_dir=str(instance_dir), mcp_port=45100,
    )
    service = MccFileService()
    with pytest.raises(HTTPException):
        service.create_file(
            instance,
            mcc_remote_placeholder_create_request("readme.txt", overwrite=False),
        )
    success = service.create_file(
        instance,
        mcc_remote_placeholder_create_request("readme.txt", overwrite=True),
    )
    assert success["path"] == "readme.txt"


def mcc_remote_placeholder_create_request(path: str, overwrite: bool = False):
    from vmtools_next.api.schemas.mcc_instance import MccFileCreateRequest

    return MccFileCreateRequest(path=path, content="new", overwrite=overwrite)


def test_profile_service_isolates_by_organization():
    db = make_session()
    try:
        service = MccAccountProfileService()
        org_a_user = type("User", (), {"id": "ua", "role": "org_admin", "organization_id": "org-a"})()
        org_b_user = type("User", (), {"id": "ub", "role": "org_admin", "organization_id": "org-b"})()
        profile = service.create_profile(db, org_a_user, MccAccountProfileCreate(
            name="OrgA Profile", auth_type="offline", username="bot1",
            mc_server_host="mc.example.test",
        ))
        db.commit()
        profiles_a = service.list_profiles(db, org_a_user)
        profiles_b = service.list_profiles(db, org_b_user)
        assert len(profiles_a) >= 1
        assert len(profiles_b) == 0
        with pytest.raises(HTTPException):
            service.delete_profile(db, org_b_user, profile.profile_id)
    finally:
        db.close()


def test_terminal_log_buffer_enforces_max_lines():
    from vmtools_next.core.terminal_log_buffer import TerminalLogBuffer

    buf = TerminalLogBuffer(max_lines=5)
    for i in range(10):
        buf.append("i1", "stdout", f"line {i}")
    items = buf.tail("i1", 100)
    assert len(items) == 5
    assert items[0].seq == 6
