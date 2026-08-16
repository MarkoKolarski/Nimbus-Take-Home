from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    ACCESS_TOKEN_COOKIE_NAME,
    CurrentUser,
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    row = db.execute(
        text("SELECT id, email, display_name, password_hash FROM users WHERE email = :email"),
        {"email": body.email},
    ).first()
    # Same 401 whether the email is unknown or the password is wrong —
    # doesn't confirm which account exists.
    if row is None or not verify_password(body.password, row.password_hash):
        raise INVALID_CREDENTIALS

    token = create_access_token(row.id)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return UserOut(id=str(row.id), email=row.email, display_name=row.display_name)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser = Depends(get_current_user)) -> UserOut:
    return UserOut(id=str(current_user.id), email=current_user.email, display_name=current_user.display_name)
