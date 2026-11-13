# -*- coding: utf-8 -*-
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, load_settings
from app.errors import DomainError
from app.routers import fbo, fbs, movements, operations, stock, warehouses
from app.routers.common import DbSession
from app.security import BodySizeLimitMiddleware, basic_auth_matches, is_same_origin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger: logging.Logger = logging.getLogger("checkstock")

settings: Settings = load_settings()

STATIC_DIR: Path = Path(__file__).resolve().parent.parent / "static"
PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})
DOCS_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json")
RETRYABLE_PGCODES: frozenset[str] = frozenset({"55P03", "57014", "40001", "40P01"})
CSP: str = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

app: FastAPI = FastAPI(title="CheckStock", version="1.0.0", description="Учёт остатков на складах ФФ")

api: APIRouter = APIRouter(prefix="/api")
for module in (warehouses, stock, movements, fbs, fbo, operations):
    api.include_router(module.router)
app.include_router(api)


def _error(status: int, code: str, message: str, headers: Optional[dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


@app.middleware("http")
async def access_control(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path: str = request.url.path
    client: str = request.client.host if request.client else "-"

    if path not in PUBLIC_PATHS:
        authorization: Optional[str] = request.headers.get("authorization")
        if not basic_auth_matches(authorization, settings.auth_username, settings.auth_password):
            if authorization:
                logger.warning("authentication failed: client=%s path=%s", client, path)
            response: Response = _error(
                401, "unauthorized", "Требуется авторизация",
                headers={"WWW-Authenticate": 'Basic realm="CheckStock", charset="UTF-8"'},
            )
        elif not is_same_origin(request.method, request.headers):
            logger.warning("cross-site request blocked: client=%s method=%s path=%s", client, request.method, path)
            response = _error(403, "cross_site_request", "Межсайтовый запрос отклонён")
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)

    for header, value in STATIC_HEADERS.items():
        response.headers[header] = value
    if not path.startswith(DOCS_PREFIXES):
        response.headers["Content-Security-Policy"] = CSP
    if path.startswith("/api") or path in PUBLIC_PATHS:
        response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields: list[dict[str, str]] = [
        {"field": ".".join(str(part) for part in err["loc"][1:]) or str(err["loc"][0]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Некорректные данные запроса", "fields": fields}},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail), headers=exc.headers)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    logger.warning("integrity violation: %s", getattr(exc.orig, "pgcode", None))
    return _error(409, "integrity_violation", "Операция нарушает целостность учёта")


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    pgcode: Optional[str] = getattr(exc.orig, "pgcode", None)
    if pgcode in RETRYABLE_PGCODES:
        logger.warning("contention on %s %s: pgcode=%s", request.method, request.url.path, pgcode)
        return _error(503, "busy", "Документ сейчас обрабатывается, повторите запрос", headers={"Retry-After": "1"})
    logger.error("database unavailable on %s %s: pgcode=%s", request.method, request.url.path, pgcode)
    return _error(503, "database_unavailable", "База данных недоступна", headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _error(500, "internal_error", "Внутренняя ошибка сервера")


@app.get("/health", include_in_schema=False)
def health(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
