"""MCC remote instance management API routes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_current_user, get_db
from vmtools_next.api.schemas.mcc_instance import (
    MccAccountConfigResponse,
    MccAccountConfigSaveResponse,
    MccAccountConfigUpdate,
    MccAccountProfileCreate,
    MccDirectoryCreateRequest,
    MccAccountProfileListResponse,
    MccAccountProfileResponse,
    MccAccountProfileUpdate,
    MccApplyAccountProfileRequest,
    MccFileContentResponse,
    MccFileCreateRequest,
    MccFileEntryResponse,
    MccFileListResponse,
    MccFileRenameRequest,
    MccFileSaveResponse,
    MccFileTreeResponse,
    MccFileWriteRequest,
    MccInstanceCreate,
    MccInstanceListResponse,
    MccInstanceResponse,
    MccInstanceStartRequest,
    MccInstanceStopRequest,
    MccInstanceUpdate,
    MccProcessEventResponse,
    MccStartStopResponse,
    MccTerminalHistoryResponse,
    MccTerminalInputRequest,
    MccTerminalLogResponse,
)
from vmtools_next.core.mcc_account_profile_service import MccAccountProfileService
from vmtools_next.core.mcc_audit_log_service import MccAuditLogService
from vmtools_next.core.mcc_file_service import MccFileService
from vmtools_next.core.mcc_instance_service import MccInstanceService
from vmtools_next.data.db import get_session_factory
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccInstanceModel, MccProcessEventModel, MccTerminalLogModel
from vmtools_next.infra.logging import get_logger

logger = get_logger("mcc.api")

router = APIRouter(prefix="/api/mcc/instances", tags=["mcc-instances"])
service = MccInstanceService()
file_service = MccFileService()
profile_service = MccAccountProfileService()
audit = MccAuditLogService()


def _process_manager(bot_engine: str = "mcc"):
    """Get the appropriate process manager for the given engine type."""
    if bot_engine == "mineflayer":
        from vmtools_next.main import get_mineflayer_process_manager
        manager = get_mineflayer_process_manager()
        if not manager:
            raise RuntimeError("Mineflayer process manager not initialized")
        return manager

    from vmtools_next.main import get_mcc_process_manager
    manager = get_mcc_process_manager()
    if not manager:
        raise RuntimeError("MCC process manager not initialized")
    return manager


async def _auto_connect_mcp_after_start(instance: "MccInstanceModel", engine: str) -> None:
    """After instance start, wait for the MCP server to come up, then auto-connect.

    Replaces the old manual "连接" step: MCC needs a few seconds after launch
    before its MCP HTTP server is reachable, so we retry in the background.
    """
    import asyncio as _asyncio

    from vmtools_next.main import get_pool_for_engine

    bot_id = instance.bot_id
    if not bot_id:
        return
    pool = get_pool_for_engine(engine)
    if not pool:
        return
    host = instance.mcp_host or "127.0.0.1"
    port = instance.mcp_port or 33333
    token = instance.mcp_auth_token_secret or None

    # 重试最多 20 次 × 3s = 60s，覆盖 MCC 慢启动场景
    for attempt in range(20):
        await _asyncio.sleep(3)
        try:
            ok = await pool.connect_bot(bot_id, host=host, port=port, auth_token=token)
            if ok:
                logger.info("Auto-connected MCP for instance {} bot={} (attempt {})", instance.instance_id, bot_id, attempt + 1)
                return
        except Exception as exc:
            logger.warning("Auto-connect attempt {} for {} failed: {}", attempt + 1, instance.instance_id, exc)
    logger.warning("Auto-connect MCP timed out for instance {} bot={}", instance.instance_id, bot_id)


def _resolve_engine(db: Session, instance_id: str) -> str:
    """Determine the bot engine type for an instance."""
    instance = db.query(MccInstanceModel).filter(
        MccInstanceModel.instance_id == instance_id,
        MccInstanceModel.deleted_at.is_(None),
    ).first()
    if instance:
        return getattr(instance, 'bot_engine', 'mcc') or 'mcc'
    return 'mcc'


def _check_file_permission(instance: MccInstanceModel, user: UserModel) -> None:
    """Raise 403 if the user is not the instance creator (and not site_admin)."""
    if user.role == "site_admin":
        return
    if instance.created_by != user.id:
        raise HTTPException(status_code=403, detail="只有实例创建者才能访问文件")


def _status_response(instance: MccInstanceModel, result: dict, message: str = "") -> MccStartStopResponse:
    return MccStartStopResponse(
        instance_id=instance.instance_id,
        status=result.get("status", instance.status),
        pid=result.get("pid", instance.pid),
        mcp_port=instance.mcp_port,
        message=result.get("message", message),
    )


@router.get("/account-profiles", response_model=MccAccountProfileListResponse)
def list_account_profiles(
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    profiles = profile_service.list_profiles(db, user)
    return MccAccountProfileListResponse(
        items=[MccAccountProfileResponse(**profile_service.to_response(profile)) for profile in profiles],
        total=len(profiles),
    )


@router.post("/account-profiles", response_model=MccAccountProfileResponse)
def create_account_profile(
    data: MccAccountProfileCreate,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    profile = profile_service.create_profile(db, user, data)
    audit.log(db, user=user, action="account_profile.create", resource_type="account_profile", after=data.model_dump())
    db.commit()
    db.refresh(profile)
    return MccAccountProfileResponse(**profile_service.to_response(profile))


@router.patch("/account-profiles/{profile_id}", response_model=MccAccountProfileResponse)
def update_account_profile(
    profile_id: str,
    data: MccAccountProfileUpdate,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    profile = profile_service.update_profile(db, user, profile_id, data)
    audit.log(db, user=user, action="account_profile.update", resource_type="account_profile", resource_path=profile_id, after=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(profile)
    return MccAccountProfileResponse(**profile_service.to_response(profile))


@router.delete("/account-profiles/{profile_id}")
def delete_account_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    profile_service.delete_profile(db, user, profile_id)
    audit.log(db, user=user, action="account_profile.delete", resource_type="account_profile", resource_path=profile_id)
    db.commit()
    return {"deleted": True, "profile_id": profile_id}


@router.get("", response_model=MccInstanceListResponse)
def list_instances(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    items = service.list_instances(db, user, status=status)
    return MccInstanceListResponse(items=items, total=len(items))


@router.post("", response_model=MccInstanceResponse)
def create_instance(
    data: MccInstanceCreate,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    try:
        instance = service.create_instance(db, user, data)
        audit.log(db, user=user, action="instance.create", instance_id=instance.instance_id, after=data.model_dump())
        db.commit()
        db.refresh(instance)
        return instance
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="instance.create", after=data.model_dump(), success=False, error_message=str(exc))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{instance_id}", response_model=MccInstanceResponse)
def get_instance(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    return service.get_instance(db, user, instance_id)


@router.patch("/{instance_id}", response_model=MccInstanceResponse)
def update_instance(
    instance_id: str,
    data: MccInstanceUpdate,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.update_instance(db, user, instance_id, data)
    audit.log(db, user=user, action="instance.update", instance_id=instance_id, after=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(instance)
    return instance


@router.delete("/{instance_id}")
def delete_instance(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    if instance.status == "running":
        raise HTTPException(status_code=400, detail="Stop the MCC instance before deleting it")
    instance.deleted_at = datetime.now(timezone.utc)
    instance.status = "deleted"
    audit.log(db, user=user, action="instance.delete", instance_id=instance_id)
    db.commit()
    return {"status": "deleted", "instance_id": instance_id}


@router.post("/{instance_id}/start", response_model=MccStartStopResponse)
async def start_instance(
    instance_id: str,
    data: MccInstanceStartRequest | None = None,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    engine = _resolve_engine(db, instance_id)
    try:
        result = await _process_manager(engine).start_instance(instance_id, extra_env=(data.env if data else None))
        db.refresh(instance)
        audit.log(db, user=user, action="instance.start", instance_id=instance_id, after=result)
        db.commit()
        # 启动后自动连接 MCP（后台重试，无需手动点"连接"）
        if instance.bot_id:
            import asyncio
            asyncio.create_task(_auto_connect_mcp_after_start(instance, engine))
        return _status_response(instance, result)
    except Exception as exc:
        db.rollback()
        err_msg = str(exc) or repr(exc)
        audit.log(db, user=user, action="instance.start", instance_id=instance_id, success=False, error_message=err_msg)
        db.commit()
        raise HTTPException(status_code=400, detail=err_msg) from exc


@router.post("/{instance_id}/stop", response_model=MccStartStopResponse)
async def stop_instance(
    instance_id: str,
    data: MccInstanceStopRequest | None = None,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    request = data or MccInstanceStopRequest()
    try:
        result = await _process_manager(_resolve_engine(db, instance_id)).stop_instance(
            instance_id,
            force=request.force,
            timeout_seconds=request.timeout_seconds,
        )
        db.refresh(instance)
        audit.log(db, user=user, action="instance.stop", instance_id=instance_id, after=result)
        db.commit()
        return _status_response(instance, result)
    except Exception as exc:
        db.rollback()
        err_msg = str(exc) or repr(exc)
        audit.log(db, user=user, action="instance.stop", instance_id=instance_id, success=False, error_message=err_msg)
        db.commit()
        raise HTTPException(status_code=400, detail=err_msg) from exc


@router.post("/kill-all")
async def kill_all_instances(
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    """Force-kill all running processes immediately.

    Tolerant by design: the active engine is the only one initialized at
    startup (MCC XOR Mineflayer), so the other manager may be None —
    that must NOT 500 the request. Orphan scanning still catches leftover
    processes regardless of engine.
    """
    results = []
    # Pre-declare: managers may fail to resolve (engine not initialized);
    # Engine 3 checks manager_mcc to decide whether an orphan sweep is needed.
    manager_mcc = None
    manager_mf = None

    # Engine 1: MCC process manager (may be None if mineflayer is active)
    try:
        manager_mcc = _process_manager("mcc")
        if manager_mcc:
            try:
                mcc_result = await manager_mcc.stop_all_instances(force=True, timeout_seconds=2)
                results.extend(mcc_result.get("results", []))
            except Exception as exc:
                logger.warning("kill-all: MCC engine error: {}", exc)
    except Exception as exc:
        logger.warning("kill-all: MCC manager unavailable: {}", exc)

    # Engine 2: Mineflayer process manager (may be None if MCC is active)
    try:
        manager_mf = _process_manager("mineflayer")
        if manager_mf:
            try:
                if hasattr(manager_mf, "stop_all_instances"):
                    mf_result = await manager_mf.stop_all_instances(force=True, timeout_seconds=2)
                    results.extend(mf_result.get("results", []))
                else:
                    # kill-all：清除 desired_state（与 shutdown 保留语义区分）
                    await manager_mf.stop_all(preserve_desired_state=False)
                    results.append({"instance_id": "mineflayer", "status": "killed", "message": "mineflayer stop_all"})
            except Exception as exc:
                logger.warning("kill-all: Mineflayer engine error: {}", exc)
    except Exception as exc:
        logger.warning("kill-all: Mineflayer manager unavailable: {}", exc)

    # Engine 3 (belt & braces): 仅当 MCC 引擎不可用时才额外扫一次孤儿进程
    # （MCC 引擎的 stop_all_instances 内部已包含 psutil 全进程扫描，避免重复）
    killed = [r for r in results if r.get("status", "") not in ("error",)]
    if manager_mcc is None:
        try:
            sweep = await _sweep_orphan_mcc_processes()
            results.extend(sweep)
        except Exception as exc:
            logger.warning("kill-all: orphan sweep error: {}", exc)

    logger.warning("Force-kill all: {} instances killed by {}", len(killed), user.game_id)
    # Update DB status
    for r in killed:
        try:
            instance = service.get_instance(db, user, r["instance_id"])
            instance.status = "stopped"
            instance.pid = None
            instance.exit_code = None
            instance.last_stopped_at = datetime.now(timezone.utc)
            audit.log(db, user=user, action="instance.kill_all", instance_id=r["instance_id"], after={"status": "killed"})
        except Exception:
            pass
    db.commit()
    return {"killed": len(killed), "results": results}


async def _sweep_orphan_mcc_processes() -> list[dict]:
    """Scan the system process table for leftover MCC processes.

    Matches by configured binary path, its basename, or a known MCC
    executable name — so orphaned processes survive backend restarts
    and missing DB paths.
    """
    import os as _os
    import psutil

    Session = get_session_factory()
    db = Session()
    try:
        all_instances = db.query(MccInstanceModel).all()
    finally:
        db.close()

    binary_paths: set[str] = set()
    for inst in all_instances:
        if inst.mcc_binary_path:
            bp = _os.path.normpath(inst.mcc_binary_path)
            binary_paths.add(bp)
            binary_paths.add(_os.path.basename(bp))

    results: list[dict] = []
    killed_pids: set[int] = set()

    def _match_cmdline(cmdline_str: str, proc_name: str) -> bool:
        if binary_paths and any(bp in cmdline_str for bp in binary_paths):
            return True
        lower = (cmdline_str + " " + proc_name).lower()
        if "minecraftclient" in lower:
            return "exe" in lower or ".dll" in lower or "mono" in lower
        # Weak fallback: executable whose path contains "mcc"
        return "mcc" in lower and ("exe" in lower or ".dll" in lower)

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline)
            if not cmdline_str:
                continue
            if not _match_cmdline(cmdline_str, proc.info.get("name") or ""):
                continue
            pid = proc.pid
            if pid in killed_pids:
                continue
            proc.kill()
            killed_pids.add(pid)
            logger.warning("Force-killed orphaned MCC pid={} cmdline={}", pid, cmdline_str[:200])
            results.append({"instance_id": "orphan", "status": "killed", "pid": pid, "message": "found via psutil scan"})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return results


@router.post("/{instance_id}/restart", response_model=MccStartStopResponse)
async def restart_instance(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    engine = _resolve_engine(db, instance_id)
    manager = _process_manager(engine)
    try:
        await manager.stop_instance(instance_id, force=False, timeout_seconds=10)
        result = await manager.start_instance(instance_id)
        db.refresh(instance)
        audit.log(db, user=user, action="instance.restart", instance_id=instance_id, after=result)
        db.commit()
        return _status_response(instance, result)
    except Exception as exc:
        db.rollback()
        err_msg = str(exc) or repr(exc)
        audit.log(db, user=user, action="instance.restart", instance_id=instance_id, success=False, error_message=err_msg)
        db.commit()
        raise HTTPException(status_code=400, detail=err_msg) from exc


@router.get("/{instance_id}/status", response_model=MccInstanceResponse)
def get_status(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    return service.get_instance(db, user, instance_id)


@router.get("/{instance_id}/terminal/history", response_model=MccTerminalHistoryResponse)
def terminal_history(
    instance_id: str,
    tail: int = Query(default=500, ge=1, le=5000),
    after_seq: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    service.get_instance(db, user, instance_id)
    lines = _process_manager(_resolve_engine(db, instance_id)).tail_logs(instance_id, tail=tail, after_seq=after_seq)
    return MccTerminalHistoryResponse(
        items=[
            MccTerminalLogResponse(
                seq=line.seq,
                stream=line.stream,
                content=line.content,
                created_at=line.created_at,
            )
            for line in lines
        ],
        last_seq=lines[-1].seq if lines else 0,
    )


@router.post("/{instance_id}/terminal/input")
async def terminal_input(
    instance_id: str,
    data: MccTerminalInputRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    service.get_instance(db, user, instance_id)
    try:
        await _process_manager(_resolve_engine(db, instance_id)).write_stdin(instance_id, data.input, append_newline=data.append_newline)
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id)
        db.commit()
        return {"sent": True}
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id, success=False, error_message=str(exc))
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{instance_id}/terminal/log")
def terminal_log_export(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    """Export the full terminal log for an instance as plain text.

    Returns every persisted line (oldest → newest); unlike /history this is not
    capped by the in-memory ring buffer.
    """
    service.get_instance(db, user, instance_id)
    rows = (
        db.query(MccTerminalLogModel)
        .filter(MccTerminalLogModel.instance_id == instance_id)
        .order_by(MccTerminalLogModel.seq.asc())
        .all()
    )
    audit.log(db, user=user, action="terminal.export", resource_type="terminal", instance_id=instance_id)
    db.commit()
    content = "".join(
        f"[{row.created_at.isoformat()}] [{row.stream}] {row.content_masked or row.content}\n"
        for row in rows
    )
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/{instance_id}/events", response_model=list[MccProcessEventResponse])
def process_events(
    instance_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    service.get_instance(db, user, instance_id)
    rows = db.query(MccProcessEventModel).filter(
        MccProcessEventModel.instance_id == instance_id,
    ).order_by(MccProcessEventModel.created_at.desc()).limit(limit).all()
    return rows


@router.get("/{instance_id}/files", response_model=MccFileListResponse)
def list_files(
    instance_id: str,
    path: str = Query(default=""),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    items = file_service.list_files(instance, relative_path=path)
    return MccFileListResponse(
        path=path,
        breadcrumbs=file_service.breadcrumbs(instance, path),
        items=[MccFileEntryResponse(**item) for item in items],
    )


@router.get("/{instance_id}/files/tree", response_model=MccFileTreeResponse)
def file_tree(
    instance_id: str,
    path: str = Query(default=""),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    return MccFileTreeResponse(items=file_service.list_tree(instance, relative_path=path))


@router.get("/{instance_id}/files/download")
def download_file(
    instance_id: str,
    path: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.read_binary(instance, path)
    audit.log(db, user=user, action="file.download", resource_type="file", instance_id=instance_id, resource_path=result["path"])
    db.commit()
    return result


@router.get("/{instance_id}/files/content", response_model=MccFileContentResponse)
def read_file(
    instance_id: str,
    path: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    content = file_service.read_file(instance, path)
    audit.log(db, user=user, action="file.read", resource_type="file", instance_id=instance_id, resource_path=content.relative_path)
    db.commit()
    return MccFileContentResponse(
        path=content.relative_path,
        content=content.content,
        encoding=content.encoding,
        size=content.size,
        language=content.language,
        masked=content.masked,
        updated_at=content.updated_at,
    )


@router.put("/{instance_id}/files/content", response_model=MccFileSaveResponse)
def save_file(
    instance_id: str,
    data: MccFileWriteRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    try:
        result = file_service.write_file(db, instance, user, data)
        audit.log(db, user=user, action="file.write", resource_type="file", instance_id=instance_id, resource_path=result["path"])
        db.commit()
        return MccFileSaveResponse(**result)
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="file.write", resource_type="file", instance_id=instance_id, resource_path=data.path, success=False, error_message=str(exc))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{instance_id}/files", response_model=MccFileSaveResponse)
def create_file(
    instance_id: str,
    data: MccFileCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.create_file(instance, data)
    audit.log(db, user=user, action="file.create", resource_type="file", instance_id=instance_id, resource_path=result["path"])
    db.commit()
    return MccFileSaveResponse(**result)


@router.post("/{instance_id}/directories")
def create_directory(
    instance_id: str,
    data: MccDirectoryCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.create_directory(instance, data)
    audit.log(db, user=user, action="file.mkdir", resource_type="file", instance_id=instance_id, resource_path=result["path"])
    db.commit()
    return result


@router.post("/{instance_id}/files/upload", response_model=MccFileSaveResponse)
def upload_file(
    instance_id: str,
    data: MccFileCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.upload_base64(instance, data)
    audit.log(db, user=user, action="file.upload", resource_type="file", instance_id=instance_id, resource_path=result["path"])
    db.commit()
    return MccFileSaveResponse(**result)


@router.delete("/{instance_id}/files")
def delete_file(
    instance_id: str,
    path: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.delete_file(instance, path)
    audit.log(db, user=user, action="file.delete", resource_type="file", instance_id=instance_id, resource_path=path)
    db.commit()
    return result


@router.post("/{instance_id}/files/rename")
def rename_file(
    instance_id: str,
    data: MccFileRenameRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    _check_file_permission(instance, user)
    result = file_service.rename_file(instance, data)
    audit.log(db, user=user, action="file.rename", resource_type="file", instance_id=instance_id, resource_path=data.source_path, after=result)
    db.commit()
    return result


@router.get("/{instance_id}/account-config", response_model=MccAccountConfigResponse)
def read_account_config(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    return MccAccountConfigResponse(**file_service.read_account_config(instance))


@router.post("/{instance_id}/account-config/apply-profile", response_model=MccAccountConfigSaveResponse)
def apply_account_profile(
    instance_id: str,
    data: MccApplyAccountProfileRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    profile = profile_service.get_profile(db, user, data.profile_id)
    try:
        result = file_service.update_account_config(db, instance, user, profile_service.to_config_update(profile))
        instance.account_profile_id = profile.profile_id
        audit.log(db, user=user, action="account_config.apply_profile", resource_type="file", instance_id=instance_id, resource_path="MinecraftClient.ini", after={"profile_id": profile.profile_id})
        db.commit()
        db.refresh(instance)
        return MccAccountConfigSaveResponse(**result)
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="account_config.apply_profile", resource_type="file", instance_id=instance_id, resource_path="MinecraftClient.ini", success=False, error_message=str(exc))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{instance_id}/account-config", response_model=MccAccountConfigSaveResponse)
def save_account_config(
    instance_id: str,
    data: MccAccountConfigUpdate,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    try:
        result = file_service.update_account_config(db, instance, user, data)
        instance.account_profile_id = None
        audit.log(db, user=user, action="account_config.write", resource_type="file", instance_id=instance_id, resource_path="MinecraftClient.ini", after=data.model_dump())
        db.commit()
        db.refresh(instance)
        return MccAccountConfigSaveResponse(**result)
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="account_config.write", resource_type="file", instance_id=instance_id, resource_path="MinecraftClient.ini", success=False, error_message=str(exc))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc
