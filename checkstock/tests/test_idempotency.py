# -*- coding: utf-8 -*-
import threading
from collections.abc import Callable
from typing import Any

import pytest

from app.database import SessionLocal
from app.errors import DomainError
from app.services import commands
from tests.conftest import Api, stock


def _race(workers: int, action: Callable[[Any], Any]) -> list[str]:
    barrier: threading.Barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    guard: threading.Lock = threading.Lock()

    def run() -> None:
        with SessionLocal() as db:
            barrier.wait()
            try:
                action(db)
                outcome: str = "ok"
            except DomainError as exc:
                outcome = exc.code
        with guard:
            outcomes.append(outcome)

    threads: list[threading.Thread] = [threading.Thread(target=run) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(outcomes) == workers
    return outcomes


@pytest.mark.parametrize("action, path", [
    ("movement", "/movements/{id}/confirm"),
    ("movement", "/movements/{id}/cancel"),
    ("fbs", "/fbs/{id}/ship"),
    ("fbs", "/fbs/{id}/cancel"),
    ("fbo", "/fbo/{id}/receive"),
    ("fbo", "/fbo/{id}/cancel"),
])
def test_repeat_is_rejected_and_changes_nothing(api: Api, action: str, path: str) -> None:
    sku101: int = api.product("SKU-101")
    north: int = api.warehouse("Север")
    body: dict[str, Any] = {"product_id": sku101, "qty": 3}
    if action == "movement":
        body |= {"from_warehouse_id": north, "to_warehouse_id": api.warehouse("Юг")}
        doc: dict[str, Any] = api.ok(api.post("/movements", body), 201)
    else:
        doc = api.ok(api.post(f"/{action}", body | {"warehouse_id": north}), 201)

    api.ok(api.post(path.format(id=doc["id"])))
    before: dict[str, Any] = api.get("/stock").json()
    journal_size: int = len(api.get("/operations").json())

    api.error(api.post(path.format(id=doc["id"])), 409, "invalid_state")
    assert api.get("/stock").json() == before
    assert len(api.get("/operations").json()) == journal_size
    api.reconciled()


def test_confirm_after_cancel_is_rejected(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"), "qty": 2,
    }), 201)
    api.ok(api.post(f"/movements/{movement['id']}/cancel"))
    api.error(api.post(f"/movements/{movement['id']}/confirm"), 409, "invalid_state")
    assert api.cell("SKU-101", "Юг") == stock(6)


def test_unknown_document_is_404(api: Api) -> None:
    api.error(api.post("/movements/999/confirm"), 404, "not_found")
    api.error(api.post("/fbs/999/ship"), 404, "not_found")
    api.error(api.post("/fbo/999/receive"), 404, "not_found")


def test_concurrent_confirms_apply_once(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"), "qty": 4,
    }), 201)

    outcomes: list[str] = _race(8, lambda db: commands.confirm_movement(db, movement["id"]))

    assert outcomes.count("ok") == 1
    assert outcomes.count("invalid_state") == 7
    assert api.cell("SKU-101", "Юг") == stock(10)
    api.reconciled()


def test_concurrent_confirm_and_cancel_pick_one(api: Api) -> None:
    movement: dict[str, Any] = api.ok(api.post("/movements", {
        "product_id": api.product("SKU-101"), "from_warehouse_id": api.warehouse("Север"),
        "to_warehouse_id": api.warehouse("Юг"), "qty": 4,
    }), 201)
    turn: list[int] = [0]
    guard: threading.Lock = threading.Lock()

    def confirm_or_cancel(db: Any) -> None:
        with guard:
            turn[0] += 1
            mine: int = turn[0]
        if mine % 2:
            commands.confirm_movement(db, movement["id"])
        else:
            commands.cancel_movement(db, movement["id"])

    outcomes: list[str] = _race(6, confirm_or_cancel)

    assert outcomes.count("ok") == 1
    north: dict[str, int] = api.cell("SKU-101", "Север")
    south: dict[str, int] = api.cell("SKU-101", "Юг")
    assert (north, south) in [(stock(6), stock(10)), (stock(10), stock(6))]
    api.reconciled()


def test_concurrent_reserves_never_oversell(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    north: int = api.warehouse("Север")

    outcomes: list[str] = _race(10, lambda db: commands.create_fbs(db, sku101, north, 3))

    assert outcomes.count("ok") == 3
    assert outcomes.count("insufficient_stock") == 7
    assert api.cell("SKU-101", "Север") == stock(10, reserved=9)
    api.reconciled()


def test_concurrent_first_receipts_create_single_inventory_row(api: Api) -> None:
    east: int = api.ok(api.post("/warehouses", {"name": "Восток"}), 201)["id"]
    sku101: int = api.product("SKU-101")

    outcomes: list[str] = _race(8, lambda db: commands.create_receipt(db, sku101, east, 1))

    assert outcomes == ["ok"] * 8
    assert api.cell("SKU-101", "Восток") == stock(8)
    api.reconciled()


def test_concurrent_delete_and_inbound_movement(api: Api) -> None:
    sku101: int = api.product("SKU-101")
    north: int = api.warehouse("Север")
    south: int = api.warehouse("Юг")
    turn: list[int] = [0]
    guard: threading.Lock = threading.Lock()

    def delete_or_move(db: Any) -> None:
        with guard:
            turn[0] += 1
            mine: int = turn[0]
        if mine == 1:
            commands.delete_warehouse(db, south)
        else:
            commands.create_movement(db, sku101, north, south, 1)

    _race(4, delete_or_move)

    in_transit_to_deleted: list[dict[str, Any]] = [
        m for m in api.get("/movements").json()
        if m["status"] == "in_transit" and m["to_warehouse"]["is_deleted"]
    ]
    assert in_transit_to_deleted == []
    api.reconciled()
