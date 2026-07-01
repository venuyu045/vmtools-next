"""Shared FastAPI dependencies.

Provides get_db, get_current_user, and get_app_state for dependency injection.
"""
from __future__ import annotations

from typing import Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from vmtools_next.data.db import get_session_factory
from vmtools_next.data.models.auth import UserModel
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.deps")
security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session, auto-close on exit."""
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> UserModel:
    """Validate JWT bearer token and return the user.

    Raises 401 if token is missing/invalid or user not found.
    """
    import jwt
    from vmtools_next.config import get_config

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    token = credentials.credentials
    config = get_config()
    try:
        payload = jwt.decode(token, config.server.secret_key, algorithms=[config.server.jwt_algorithm])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.status != "approved":
        raise HTTPException(status_code=403, detail="User not approved")
    return user


def get_app_state(request) -> dict:
    """Access the FastAPI app.state (holds mcc_pool, task_engine, etc.)."""
    return request.app.state
