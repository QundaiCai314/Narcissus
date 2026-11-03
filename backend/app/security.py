import hashlib
import hmac
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session
from redis import Redis
from .config import settings
from .db import db_session
from .models import LoginSession, User, now
from .errors import fail

passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
redis = Redis.from_url(
    settings().redis_url,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)
COOKIE = "narcissus_session"


def digest(value: str):
    return hmac.new(
        settings().app_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def rate_limit(key: str, limit: int, seconds: int):
    script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n"
    try:
        count = redis.eval(script, 1, "limit:" + digest(key), seconds)
    except Exception:
        fail(503, "rate_limit_unavailable", "服务暂时繁忙，请稍后重试")
    if count > limit:
        fail(429, "rate_limited", "操作过于频繁，请稍后重试")


def current_user(request: Request, db: Session = Depends(db_session)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(token)) if token else None
    if not session or session.expires_at <= now():
        fail(401, "unauthenticated", "登录已过期，请重新登录")
    user = db.get(User, session.user_id)
    if not user:
        fail(401, "unauthenticated", "请重新登录")
    return user


def login_cookie(db: Session, user: User, response: Response):
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=now() + timedelta(days=settings().session_days),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings().environment == "production",
        samesite="lax",
        max_age=settings().session_days * 86400,
        path="/",
    )
