# -*- coding: utf-8 -*-
import base64
import binascii
import json
import logging
import secrets
from typing import Any, Optional
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger: logging.Logger = logging.getLogger("checkstock.security")

SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
TRUSTED_FETCH_SITES: frozenset[str] = frozenset({"same-origin", "none"})
TOO_LARGE_MESSAGE: str = "Тело запроса слишком большое"


def basic_auth_matches(header: Optional[str], username: str, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded: str = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    given_user, sep, given_password = decoded.partition(":")
    if not sep:
        return False
    user_ok: bool = secrets.compare_digest(given_user.encode(), username.encode())
    password_ok: bool = secrets.compare_digest(given_password.encode(), password.encode())
    return user_ok and password_ok


def is_same_origin(method: str, headers: Any) -> bool:
    """Blocks cross-site state changes: body-less POSTs are CORS-simple requests and need no preflight."""
    if method in SAFE_METHODS:
        return True
    fetch_site: Optional[str] = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site in TRUSTED_FETCH_SITES
    origin: Optional[str] = headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == (headers.get("host") or "").lower()


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app: ASGIApp = app
        self.max_bytes: int = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared: Optional[bytes] = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if not declared.isdigit():
                await self._reject(send, 400, "Некорректный Content-Length")
                return
            if int(declared) > self.max_bytes:
                await self._reject(send, 413, TOO_LARGE_MESSAGE)
                return
            await self.app(scope, receive, send)
            return

        buffered: list[Message] = []
        received: int = 0
        while True:
            event: Message = await receive()
            buffered.append(event)
            if event["type"] != "http.request":
                break
            received += len(event.get("body", b""))
            if received > self.max_bytes:
                await self._reject(send, 413, TOO_LARGE_MESSAGE)
                return
            if not event.get("more_body", False):
                break

        async def replay() -> Message:
            return buffered.pop(0) if buffered else await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Send, status: int, message: str) -> None:
        body: bytes = json.dumps(
            {"error": {"code": f"http_{status}", "message": message}}, ensure_ascii=False
        ).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
