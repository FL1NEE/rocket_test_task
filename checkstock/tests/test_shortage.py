# -*- coding: utf-8 -*-
from typing import Any

from tests.conftest import Api, stock


def test_fbs_shortage_suggests_other_warehouses(api: Api) -> None:
    payload: dict[str, Any] = api.error(api.post("/fbs", {
        "product_id": api.product("SKU-102"), "warehouse_id": api.warehouse("Юг"), "qty": 3,
    }), 409, "insufficient_stock")

    assert payload["available"] == 0
    assert payload["total_available"] == 5
    assert payload["can_split"] is True
    assert payload["alternatives"] == [
        {"warehouse_id": api.warehouse("Север"), "warehouse": "Север", "available": 5}
    ]
    assert api.cell("SKU-102", "Север") == stock(5)


def test_allocate_splits_reserve_starting_with_preferred(api: Api) -> None:
    orders: list[dict[str, Any]] = api.ok(api.post("/fbs/allocate", {
        "product_id": api.product("SKU-101"), "qty": 12, "preferred_warehouse_id": api.warehouse("Юг"),
    }), 201)

    assert [(o["warehouse"]["name"], o["qty"]) for o in orders] == [("Юг", 6), ("Север", 6)]
    assert api.cell("SKU-101", "Юг") == stock(6, reserved=6)
    assert api.cell("SKU-101", "Север") == stock(10, reserved=6)
    api.reconciled()


def test_allocate_fails_atomically_when_total_is_short(api: Api) -> None:
    payload: dict[str, Any] = api.error(api.post("/fbs/allocate", {
        "product_id": api.product("SKU-101"), "qty": 17,
    }), 409, "insufficient_stock")

    assert payload["total_available"] == 16
    assert api.cell("SKU-101", "Север") == stock(10)
    assert api.cell("SKU-101", "Юг") == stock(6)
    assert api.get("/fbs").json() == []


def test_shortage_respects_existing_reserves(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    api.ok(api.post("/fbs", {"product_id": sku101, "warehouse_id": api.warehouse("Север"), "qty": 9}), 201)

    payload: dict[str, Any] = api.error(api.post("/fbo", {
        "product_id": sku101, "warehouse_id": api.warehouse("Север"), "qty": 3,
    }), 409, "insufficient_stock")
    assert payload["available"] == 1
    assert payload["total_available"] == 7
