"""MCC remote instance management API routes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
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
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.mcc_remote import MccInstanceModel, MccProcessEventModel

router = APIRouter(prefix="/api/mcc/instances", tags=["mcc-instances"])
service = MccInstanceService()
file_service = MccFileService()
profile_service = MccAccountProfileService()
audit = MccAuditLogService()


def _process_manager():
    from vmtools_next.main import get_mcc_process_manager

    manager = get_mcc_process_manager()
    if not manager:
        raise RuntimeError("MCC process manager not initialized")
    return manager


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
    try:
        result = await _process_manager().start_instance(instance_id, extra_env=(data.env if data else None))
        db.refresh(instance)
        audit.log(db, user=user, action="instance.start", instance_id=instance_id, after=result)
        db.commit()
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
        result = await _process_manager().stop_instance(
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


@router.post("/{instance_id}/restart", response_model=MccStartStopResponse)
async def restart_instance(
    instance_id: str,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
    manager = _process_manager()
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
    lines = _process_manager().tail_logs(instance_id, tail=tail, after_seq=after_seq)
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
        await _process_manager().write_stdin(instance_id, data.input, append_newline=data.append_newline)
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id)
        db.commit()
        return {"sent": True}
    except Exception as exc:
        db.rollback()
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id, success=False, error_message=str(exc))
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    return MccFileTreeResponse(items=file_service.list_tree(instance, relative_path=path))


@router.get("/{instance_id}/files/download")
def download_file(
    instance_id: str,
    path: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    instance = service.get_instance(db, user, instance_id)
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
