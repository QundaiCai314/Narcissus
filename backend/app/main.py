import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from starlette.datastructures import Headers
from .config import settings
from .db import SessionLocal
from .security import redis
from . import auth, notebooks, documents, conversations, qa, storage, writings, exports, learning, audio, research, visuals

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("narcissus.api")


@asynccontextmanager
async def lifespan(app):
    storage.initialize_bucket()
    yield


app = FastAPI(
    title="Narcissus API",
    version="7.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


class RequestGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = Headers(scope=scope)
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin = headers.get("origin")
            if (origin and origin != settings().public_origin) or headers.get(
                "x-requested-with"
            ) != "narcissus":
                return await JSONResponse(
                    {
                        "error": {
                            "code": "invalid_origin",
                            "message": "请求来源无效",
                            "request_id": request_id,
                        }
                    },
                    403,
                )(scope, receive, send)
        length = headers.get("content-length", "0")
        if (
            not length.isdigit()
            or int(length) > (settings().max_upload_mb + 1) * 1024 * 1024
        ):
            return await JSONResponse(
                {
                    "error": {
                        "code": "too_large",
                        "message": "上传文件过大",
                        "request_id": request_id,
                    }
                },
                413,
            )(scope, receive, send)

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                message["headers"].extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"same-origin"),
                    ]
                )
                log.info(
                    "request_id=%s method=%s path=%s status=%s",
                    request_id,
                    scope["method"],
                    scope["path"],
                    message["status"],
                )
            await send(message)

        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > (settings().max_upload_mb + 1) * 1024 * 1024:
                    raise HTTPException(
                        413, detail={"code": "too_large", "message": "上传文件过大"}
                    )
            return message

        await self.app(scope, bounded_receive, wrapped_send)


app.add_middleware(RequestGuard)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "http_error", "message": str(exc.detail)}
    )
    return JSONResponse(
        {"error": {**detail, "request_id": request.state.request_id}},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "输入格式有误，请检查必填内容、长度及数量范围",
                "fields": [".".join(str(p) for p in e["loc"]) for e in exc.errors()],
                "request_id": request.state.request_id,
            }
        },
        422,
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, exc):
    log.error(
        "request_id=%s error_type=%s", request.state.request_id, type(exc).__name__
    )
    return JSONResponse(
        {
            "error": {
                "code": "internal_error",
                "message": "服务暂时出错，请稍后重试",
                "request_id": request.state.request_id,
            }
        },
        500,
    )


for router in (
    auth.router,
    notebooks.router,
    documents.router,
    conversations.router,
    qa.router,
    writings.router,
    exports.router,
    learning.router,
    audio.router,
    research.router,
    visuals.router,
):
    app.include_router(router, prefix="/api")


@app.get("/api/health", tags=["运行状态"])
def health():
    return {"status": "ok"}


@app.get("/api/ready", tags=["运行状态"])
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        redis.ping()
        storage.s3().head_bucket(Bucket=settings().s3_bucket)
        return {
            "status": "ready",
            "models_configured": bool(
                settings().chat_api_key and settings().embedding_api_key
            ),
        }
    except Exception:
        return JSONResponse({"status": "unavailable"}, 503)
