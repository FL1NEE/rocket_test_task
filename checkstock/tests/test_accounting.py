# -*- coding: utf-8 -*-
from typing import Any

from tests.conftest import Api, stock


def test_seed_matches_task_table(api: Api) -> None:
    assert api.cell("SKU-101", "Север") == stock(10)
    assert api.cell("SKU-101", "Юг") == stock(6)
    assert api.cell("SKU-102", "Север") == stock(5)
    assert api.cell("SKU-102", "Юг") == stock(0)
    assert api.cell("SKU-103", "Север") == stock(0)
    assert api.cell("SKU-103", "Юг") == stock(4)
    api.reconciled()


def test_receipt_adds_physical_and_available(api: Api) -> None:
    api.ok(api.post("/receipts", {
        "product_id": api.product("SKU-103"), "warehouse_id": api.warehouse("Север"), "qty": 7,
    }), 201)
    assert api.cell("SKU-103", "Север") == stock(7)
    api.reconciled()


def test_fbs_lifecycle(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    north: int = api.warehouse("Север")

    order: dict[str, Any] = api.ok(api.post("/fbs", {"product_id": sku101, "warehouse_id": north, "qty": 4}), 201)
    assert order["status"] == "reserved"
    assert api.cell("SKU-101", "Север") == stock(10, reserved=4)

    api.ok(api.post(f"/fbs/{order['id']}/ship"))
    assert api.cell("SKU-101", "Север") == stock(6)
    row: dict[str, Any] = api.row("SKU-101")
    assert row["in_transit_to_client"] == 4
    assert any(i["kind"] == "fbs" and i["document_id"] == order["id"] for i in api.get("/stock/in-transit").json())

    api.ok(api.post(f"/fbs/{order['id']}/deliver"))
    assert api.row("SKU-101")["in_transit_to_client"] == 0
    api.reconciled()


def test_fbs_cancel_releases_reserve(api: Api) -> None:
    order: dict[str, Any] = api.ok(api.post("/fbs", {
        "product_id": api.product("SKU-101"), "warehouse_id": api.warehouse("Юг"), "qty": 6,
    }), 201)
    assert api.cell("SKU-101", "Юг") == stock(6, reserved=6)
    api.ok(api.post(f"/fbs/{order['id']}/cancel"))
    assert api.cell("SKU-101", "Юг") == stock(6)
    api.reconciled()


def test_movement_send_and_confirm(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"),
        "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"),
        "qty": 3,
    }), 201)
    assert api.cell("SKU-101", "Север") == stock(7)
    assert api.cell("SKU-101", "Юг") == stock(6)
    assert api.row("SKU-101")["in_transit_between_ff"] == 3
    api.reconciled()

    api.ok(api.post(f"/movements/{movement['id']}/confirm"))
    assert api.cell("SKU-101", "Юг") == stock(9)
    assert api.row("SKU-101")["in_transit_between_ff"] == 0
    api.reconciled()


def test_movement_cancel_returns_to_source(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-102"),
        "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"),
        "qty": 5,
    }), 201)
    api.ok(api.post(f"/movements/{movement['id']}/cancel"))
    assert api.cell("SKU-102", "Север") == stock(5)
    assert api.cell("SKU-102", "Юг") == stock(0)
    api.reconciled()


def test_fbo_ship_receive_and_cancel(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    south: int = api.warehouse("Юг")

    first: dict[str, Any] = api.ok(api.post("/fbo", {"product_id": sku101, "warehouse_id": south, "qty": 2}), 201)
    second: dict[str, Any] = api.ok(api.post("/fbo", {"product_id": sku101, "warehouse_id": south, "qty": 3}), 201)
    assert api.cell("SKU-101", "Юг") == stock(1)
    assert api.row("SKU-101")["in_transit_to_fbo"] == 5

    api.ok(api.post(f"/fbo/{first['id']}/receive"))
    api.ok(api.post(f"/fbo/{second['id']}/cancel"))
    assert api.cell("SKU-101", "Юг") == stock(4)
    assert api.row("SKU-101")["in_transit_to_fbo"] == 0
    api.reconciled()


def test_reserved_stock_cannot_leave_by_other_channels(api: Api) -> None:
    sku102: int = api.product("SKU-102")
    north: int = api.warehouse("Север")
    api.ok(api.post("/fbs", {"product_id": sku102, "warehouse_id": north, "qty": 4}), 201)

    api.error(api.post("/fbo", {"product_id": sku102, "warehouse_id": north, "qty": 2}), 409, "insufficient_stock")
    api.error(api.post("/movements", {
        "product_id": sku102, "from_warehouse_id": north, "to_warehouse_id": api.warehouse("Юг"), "qty": 2,
    }), 409, "insufficient_stock")
    assert api.cell("SKU-102", "Север") == stock(5, reserved=4)


def test_journal_records_what_where_and_how_many(api: Api) -> None:
    api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"),
        "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"),
        "qty": 2,
    }), 201)
    entry: dict[str, Any] = api.get("/operations").json()[0]
    assert entry["operation"] == "movement_sent"
    assert (entry["product_sku"], entry["qty"], entry["source"], entry["destination"]) == ("SKU-101", 2, "Север", "Юг")


def test_full_day_scenario_stays_balanced(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    north: int = api.warehouse("Север")
    south: int = api.warehouse("Юг")

    api.ok(api.post("/receipts", {"product_id": sku101, "warehouse_id": south, "qty": 4}), 201)
    order: dict[str, Any] = api.ok(api.post("/fbs", {"product_id": sku101, "warehouse_id": north, "qty": 2}), 201)
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": sku101, "from_warehouse_id": north, "to_warehouse_id": south, "qty": 5,
    }), 201)
    shipment: dict[str, Any] = api.ok(api.post("/fbo", {"product_id": sku101, "warehouse_id": south, "qty": 7}), 201)
    api.ok(api.post(f"/fbs/{order['id']}/ship"))
    api.ok(api.post(f"/movements/{movement['id']}/confirm"))
    api.ok(api.post(f"/fbo/{shipment['id']}/receive"))

    assert api.cell("SKU-101", "Север") == stock(3)
    assert api.cell("SKU-101", "Юг") == stock(8)
    report: dict[str, Any] = api.ok(api.get("/stock/reconcile"))
    sku_report: dict[str, Any] = next(p for p in report["products"] if p["product"]["sku"] == "SKU-101")
    assert sku_report == {
        **sku_report, "received": 20, "on_hand": 11, "in_transit_between_ff": 0,
        "shipped_fbo": 7, "shipped_fbs": 2, "balanced": True,
    }
    assert report["ok"]
