from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from argon2.exceptions import VerificationError
from .db import db_session
from .models import User, LoginSession
from .security import passwords, rate_limit, login_cookie, current_user, COOKIE, digest
from .errors import fail

router = APIRouter(prefix="/auth", tags=["认证"])


class Credentials(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]


def throttle(request, email):
    rate_limit("auth-ip:" + request.client.host, 40, 900)
    rate_limit("auth-email:" + email, 12, 900)


@router.post("/register", status_code=201)
def register(
    data: Credentials, request: Request, response: Response, db=Depends(db_session)
):
    email = str(data.email).lower()
    throttle(request, email)
    user = User(email=email, password_hash=passwords.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "email_exists", "该邮箱已注册，请直接登录")
    login_cookie(db, user, response)
    return {"id": user.id, "email": user.email}


@router.post("/login")
def login(
    data: Credentials, request: Request, response: Response, db=Depends(db_session)
):
    email = str(data.email).lower()
    throttle(request, email)
    user = db.scalar(select(User).where(User.email == email))
    # Same expensive path for unknown accounts.
    hashed = user.password_hash if user else DUMMY_HASH
    try:
        valid = passwords.verify(hashed, data.password)
    except VerificationError:
        valid = False
    if not user or not valid:
        fail(401, "bad_credentials", "邮箱或密码不正确")
    login_cookie(db, user, response)
    return {"id": user.id, "email": user.email}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "email": user.email}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db=Depends(db_session)):
    token = request.cookies.get(COOKIE)
    session = db.get(LoginSession, digest(token)) if token else None
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


DUMMY_HASH = passwords.hash("dummy-password-never-used")
