# -*- coding: utf-8 -*-
from typing import Any

import pytest

from tests.conftest import Api


@pytest.mark.parametrize("qty", [0, -1, 1.5, "5", True, None, 1_000_001, 2**40])
def test_bad_qty_is_422(api: Api, qty: Any) -> None:
    api.error(api.post("/receipts", {
        "product_id": api.product("SKU-101"), "warehouse_id": api.warehouse("Север"), "qty": qty,
    }), 422, "validation_error")


@pytest.mark.parametrize("body", [
    {},
    {"product_id": 1, "warehouse_id": 1},
    {"product_id": 1, "warehouse_id": 1, "qty": 1, "extra": "x"},
    {"product_id": 2**40, "warehouse_id": 1, "qty": 1},
    [1, 2, 3],
])
def test_malformed_body_is_422(api: Api, body: Any) -> None:
    api.error(api.post("/fbs", body), 422, "validation_error")


def test_same_source_and_destination_is_422(api: Api) -> None:
    north: int = api.warehouse("Север")
    api.error(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": north, "to_warehouse_id": north, "qty": 1,
    }), 422, "validation_error")


@pytest.mark.parametrize("path", ["/movements/0/confirm", "/fbs/-1/ship", "/fbo/99999999999/receive"])
def test_bad_path_id_is_422(api: Api, path: str) -> None:
    api.error(api.post(path), 422, "validation_error")


def test_unknown_references_are_404(api: Api) -> None:
    api.error(api.post("/receipts", {"product_id": 999, "warehouse_id": 1, "qty": 1}), 404, "not_found")
    api.error(api.post("/receipts", {"product_id": 1, "warehouse_id": 999, "qty": 1}), 404, "not_found")


def test_limit_is_bounded(api: Api) -> None:
    api.error(api.get("/operations", limit=10_000), 422, "validation_error")


def test_health(api: Api) -> None:
    assert api.client.get("/health").json() == {"status": "ok"}
