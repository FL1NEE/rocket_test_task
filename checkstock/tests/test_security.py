# -*- coding: utf-8 -*-
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import engine
from tests.conftest import TEST_PASSWORD, TEST_USERNAME, Api


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/api/stock", "/docs", "/openapi.json"])
def test_everything_but_health_requires_auth(anonymous: TestClient, path: str) -> None:
    response = anonymous.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")
    assert anonymous.get("/health").status_code == 200


@pytest.mark.parametrize("auth", [
    (TEST_USERNAME, "wrong-password-123"),
    ("intruder", TEST_PASSWORD),
    (TEST_USERNAME, ""),
])
def test_wrong_credentials_rejected(anonymous: TestClient, auth: tuple[str, str]) -> None:
    anonymous.auth = auth
    assert anonymous.get("/api/stock").status_code == 401


@pytest.mark.parametrize("header", ["Basic !!!", "Basic " + "bm9jb2xvbg==", "Bearer abc", "Basic"])
def test_malformed_authorization_rejected(anonymous: TestClient, header: str) -> None:
    assert anonymous.get("/api/stock", headers={"Authorization": header}).status_code == 401


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "https://evil.example"},
    {"Origin": "http://testserver.evil.example"},
])
def test_cross_site_writes_are_blocked(api: Api, headers: dict[str, str]) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"), "qty": 1,
    }), 201)

    response = api.client.post(f"/api/movements/{movement['id']}/confirm", headers=headers)
    api.error(response, 403, "cross_site_request")
    assert api.get("/movements").json()[0]["status"] == "in_transit"


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "same-origin"},
    {"Origin": "http://testserver"},
    {},
])
def test_same_origin_writes_pass(api: Api, headers: dict[str, str]) -> None:
    response = api.client.post("/api/warehouses", json={"name": "Восток"}, headers=headers)
    assert response.status_code == 201, response.text


def test_cross_site_reads_are_allowed(api: Api) -> None:
    assert api.client.get("/api/stock", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_untrusted_host_rejected(api: Api) -> None:
    assert api.client.get("/api/stock", headers={"Host": "attacker.example"}).status_code == 400


def test_oversized_body_rejected_by_content_length(api: Api) -> None:
    response = api.client.post("/api/warehouses", content=b"{" + b" " * 70_000 + b"}",
                               headers={"Content-Type": "application/json"})
    api.error(response, 413, "http_413")


def test_oversized_chunked_body_rejected(api: Api) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"name": "'
        for _ in range(20):
            yield b"x" * 8_192
        yield b'"}'

    response = api.client.post("/api/warehouses", content=chunks(), headers={"Content-Type": "application/json"})
    api.error(response, 413, "http_413")


def test_invalid_content_length_rejected(api: Api) -> None:
    response = api.client.post("/api/warehouses", content=b"{}", headers={
        "Content-Type": "application/json", "Content-Length": "abc",
    })
    assert response.status_code == 400


def test_unknown_route_uses_uniform_error(api: Api) -> None:
    api.error(api.get("/does-not-exist"), 404, "http_404")
    api.error(api.client.put("/api/stock", json={}), 405, "http_405")


def test_injection_payloads_are_plain_data(api: Api) -> None:
    payload: str = "'; DROP TABLE inventory; -- <script>alert(1)</script>"
    created: dict[str, Any] = api.ok(api.post("/warehouses", {"name": payload}), 201)
    assert created["name"] == payload
    assert api.get("/stock").status_code == 200


def test_security_headers_present(api: Api) -> None:
    response = api.client.get("/")
    assert response.status_code == 200
    csp: str = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert api.get("/stock").headers["cache-control"] == "no-store"


def test_journal_is_append_only(api: Api) -> None:
    for statement in ("UPDATE operation_log SET qty = 0", "DELETE FROM operation_log"):
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.execute(text(statement))


def test_lock_contention_returns_503_instead_of_hanging(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"), "qty": 1,
    }), 201)
    locked: threading.Event = threading.Event()
    release: threading.Event = threading.Event()

    def hold_lock() -> None:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1 FROM movements WHERE id = :id FOR UPDATE"), {"id": movement["id"]})
            locked.set()
            release.wait(timeout=20)

    holder: threading.Thread = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert locked.wait(timeout=5)
        response = api.post(f"/movements/{movement['id']}/confirm")
        api.error(response, 503, "busy")
        assert response.headers["retry-after"] == "1"
    finally:
        release.set()
        holder.join()

    api.ok(api.post(f"/movements/{movement['id']}/confirm"))
    api.reconciled()
