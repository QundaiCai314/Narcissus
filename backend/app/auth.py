from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, StringConstraints, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from argon2.exceptions import VerificationError
from .db import db_session
from .models import User, LoginSession
from .security import passwords, rate_limit, login_cookie, current_user, COOKIE, digest
from .errors import fail
from . import registration_email
from .registration_security import validate_password

router = APIRouter(prefix="/auth", tags=["认证"])


class Credentials(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]


class Registration(Credentials):
    confirm_password: Annotated[str, StringConstraints(min_length=10, max_length=128)]
    challenge_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    verification_code: str = Field(pattern=r'^[0-9]{6}$')


class EmailCodeRequest(BaseModel):
    email: EmailStr


@router.get('/registration-options')
def registration_options():
    return dict(email_verification_required=True, email_delivery_available=registration_email.configured(),
                password_min_length=10, password_max_length=128, recommended_password_length=15,
                code_expires_in=registration_email.TTL, code_retry_after=registration_email.COOLDOWN)


@router.post('/email-code', status_code=202)
def email_code(data: EmailCodeRequest, request: Request):
    return registration_email.issue(str(data.email).lower(), request.client.host)


def throttle(request, email):
    rate_limit("auth-ip:" + request.client.host, 40, 900)
    rate_limit("auth-email:" + email, 12, 900)


@router.post("/register", status_code=201)
def register(
    data: Registration, request: Request, response: Response, db=Depends(db_session)
):
    email = str(data.email).lower()
    throttle(request, email)
    if data.password != data.confirm_password:
        fail(422, 'password_mismatch', '两次输入的密码不一致')
    validate_password(data.password)
    registration_email.consume(email, data.challenge_id, data.verification_code)
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
