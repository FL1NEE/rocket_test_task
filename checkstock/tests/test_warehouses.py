# -*- coding: utf-8 -*-
from typing import Any

from tests.conftest import Api, stock


def test_create_and_rename(api: Api) -> None:
    created: dict[str, Any] = api.ok(api.post("/warehouses", {"name": "  Восток  "}), 201)
    assert created["name"] == "Восток"
    renamed: dict[str, Any] = api.ok(api.patch(f"/warehouses/{created['id']}", {"name": "Восток-2"}))
    assert renamed["name"] == "Восток-2"
    assert api.get("/operations").json()[0]["operation"] == "warehouse_renamed"


def test_names_are_unique_case_insensitive(api: Api) -> None:
    api.error(api.post("/warehouses", {"name": "север"}), 409, "duplicate_name")
    api.error(api.patch(f"/warehouses/{api.warehouse('Юг')}", {"name": "СЕВЕР"}), 409, "duplicate_name")


def test_blank_name_rejected(api: Api) -> None:
    api.error(api.post("/warehouses", {"name": "   "}), 422, "validation_error")


def test_delete_keeps_stock_visible_and_history(api: Api) -> None:
    north: int = api.warehouse("Север")
    api.ok(api.post("/fbs", {"product_id": api.product("SKU-101"), "warehouse_id": north, "qty": 2}), 201)

    deleted: dict[str, Any] = api.ok(api.delete(f"/warehouses/{north}"))
    assert deleted["is_deleted"] is True

    matrix: dict[str, Any] = api.get("/stock").json()
    assert {"id": north, "name": "Север", "is_deleted": True} in matrix["warehouses"]
    assert api.cell("SKU-101", "Север") == stock(10, reserved=2)
    assert api.row("SKU-101")["total_physical"] == 16

    entry: dict[str, Any] = api.get("/operations").json()[0]
    assert entry["operation"] == "warehouse_deleted"
    assert entry["details"] == {"physical_left": 15, "reserved_left": 2}
    assert len(api.get("/operations").json()) > 1
    api.reconciled()


def test_deleted_warehouse_accepts_nothing_new(api: Api) -> None:
    north: int = api.warehouse("Север")
    south: int = api.warehouse("Юг")
    sku101: int = api.product("SKU-101")
    api.ok(api.delete(f"/warehouses/{north}"))

    api.error(api.post("/receipts", {"product_id": sku101, "warehouse_id": north, "qty": 1}), 409, "warehouse_deleted")
    api.error(api.post("/fbs", {"product_id": sku101, "warehouse_id": north, "qty": 1}), 409, "warehouse_deleted")
    api.error(api.post("/movements", {
        "product_id": sku101, "from_warehouse_id": south, "to_warehouse_id": north, "qty": 1,
    }), 409, "warehouse_deleted")
    api.error(api.patch(f"/warehouses/{north}", {"name": "Север-2"}), 409, "warehouse_deleted")
    api.error(api.delete(f"/warehouses/{north}"), 409, "warehouse_deleted")


def test_deleted_warehouse_can_be_unloaded(api: Api) -> None:
    north: int = api.warehouse("Север")
    south: int = api.warehouse("Юг")
    sku101: int = api.product("SKU-101")
    order: dict[str, Any] = api.ok(api.post("/fbs", {"product_id": sku101, "warehouse_id": north, "qty": 2}), 201)
    api.ok(api.delete(f"/warehouses/{north}"))

    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": sku101, "from_warehouse_id": north, "to_warehouse_id": south, "qty": 8,
    }), 201)
    api.ok(api.post(f"/movements/{movement['id']}/confirm"))
    api.ok(api.post(f"/fbs/{order['id']}/ship"))

    assert api.cell("SKU-101", "Юг") == stock(14)
    matrix: dict[str, Any] = api.get("/stock").json()
    still_holding: bool = any(
        c["physical"] or c["reserved_fbs"]
        for r in matrix["rows"] for c in r["cells"] if c["warehouse_id"] == north
    )
    assert still_holding
    api.reconciled()


def test_delete_blocked_while_goods_are_inbound(api: Api) -> None:
    south: int = api.warehouse("Юг")
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": south, "qty": 1,
    }), 201)

    payload: dict[str, Any] = api.error(api.delete(f"/warehouses/{south}"), 409, "inbound_in_transit")
    assert payload["movements"] == 1

    api.ok(api.post(f"/movements/{movement['id']}/confirm"))
    api.ok(api.delete(f"/warehouses/{south}"))


def test_new_warehouse_with_same_name_after_delete(api: Api) -> None:
    api.ok(api.delete(f"/warehouses/{api.warehouse('Юг')}"))
    api.ok(api.post("/warehouses", {"name": "Юг"}), 201)
    names: list[tuple[str, bool]] = [
        (w["name"], w["is_deleted"]) for w in api.get("/warehouses", include_deleted=True).json()
    ]
    assert ("Юг", True) in names and ("Юг", False) in names
