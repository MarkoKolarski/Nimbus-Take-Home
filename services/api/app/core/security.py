from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

ACCESS_TOKEN_COOKIE_NAME = "access_token"


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), password_hash.encode())


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Raises jwt.PyJWTError (expired, bad signature, malformed) on failure."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return uuid.UUID(payload["sub"])


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str


def get_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """The only place a request's identity is derived. Every route that needs
    to know who is asking depends on this — never on a user_id parameter."""
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    if access_token is None:
        raise unauthorized

    try:
        user_id = decode_access_token(access_token)
    except jwt.PyJWTError:
        raise unauthorized

    row = db.execute(
        text("SELECT id, email, display_name FROM users WHERE id = :id"),
        {"id": user_id},
    ).first()
    if row is None:
        raise unauthorized

    return CurrentUser(id=row.id, email=row.email, display_name=row.display_name)
