# -*- coding: utf-8 -*-
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.errors import NotFound
from app.models import (
    FBOShipment, FBOStatus, FBSOrder, FBSStatus, Inventory, Movement, MovementStatus,
    OperationLog, Product, Receipt, Warehouse,
)
from app.schemas import (
    InTransitItem, ProductOut, ReconcileOut, ReconcileProduct, ReserveMismatch,
    StockCell, StockMatrixOut, StockRow, WarehouseRef,
)
from app.services.commands import FBO_DESTINATION, FBS_DESTINATION

_MOVEMENT_LOAD: tuple[Any, ...] = (
    joinedload(Movement.product), joinedload(Movement.from_warehouse), joinedload(Movement.to_warehouse),
)
_FBS_LOAD: tuple[Any, ...] = (joinedload(FBSOrder.product), joinedload(FBSOrder.warehouse))
_FBO_LOAD: tuple[Any, ...] = (joinedload(FBOShipment.product), joinedload(FBOShipment.warehouse))
_RECEIPT_LOAD: tuple[Any, ...] = (joinedload(Receipt.product), joinedload(Receipt.warehouse))


def _sum_by_product(db: Session, model: Any, *statuses: Any) -> dict[int, int]:
    rows = db.execute(
        select(model.product_id, func.sum(model.qty))
        .where(model.status.in_(statuses))
        .group_by(model.product_id)
    ).all()
    return {product_id: int(total) for product_id, total in rows}


def list_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).order_by(Product.sku)))


def list_warehouses(db: Session, include_deleted: bool) -> list[Warehouse]:
    query = select(Warehouse).order_by(Warehouse.is_deleted, Warehouse.id)
    if not include_deleted:
        query = query.where(Warehouse.is_deleted.is_(False))
    return list(db.scalars(query))


def stock_matrix(db: Session) -> StockMatrixOut:
    products: list[Product] = list_products(db)
    inventories: list[Inventory] = list(db.scalars(select(Inventory)))
    by_key: dict[tuple[int, int], Inventory] = {(i.product_id, i.warehouse_id): i for i in inventories}
    holding_stock: set[int] = {
        i.warehouse_id for i in inventories if i.physical_qty > 0 or i.reserved_fbs_qty > 0
    }
    warehouses: list[Warehouse] = [
        wh for wh in list_warehouses(db, include_deleted=True)
        if not wh.is_deleted or wh.id in holding_stock
    ]

    between: dict[int, int] = _sum_by_product(db, Movement, MovementStatus.in_transit)
    to_fbo: dict[int, int] = _sum_by_product(db, FBOShipment, FBOStatus.in_transit)
    to_client: dict[int, int] = _sum_by_product(db, FBSOrder, FBSStatus.shipped)

    rows: list[StockRow] = []
    for product in products:
        cells: list[StockCell] = []
        for wh in warehouses:
            inv: Optional[Inventory] = by_key.get((product.id, wh.id))
            physical: int = inv.physical_qty if inv else 0
            reserved: int = inv.reserved_fbs_qty if inv else 0
            cells.append(StockCell(
                warehouse_id=wh.id, physical=physical, reserved_fbs=reserved, available=physical - reserved
            ))
        rows.append(StockRow(
            product=ProductOut.model_validate(product),
            cells=cells,
            total_physical=sum(c.physical for c in cells),
            total_reserved_fbs=sum(c.reserved_fbs for c in cells),
            total_available=sum(c.available for c in cells),
            in_transit_between_ff=between.get(product.id, 0),
            in_transit_to_fbo=to_fbo.get(product.id, 0),
            in_transit_to_client=to_client.get(product.id, 0),
        ))

    return StockMatrixOut(warehouses=[WarehouseRef.model_validate(w) for w in warehouses], rows=rows)


def in_transit(db: Session) -> list[InTransitItem]:
    items: list[InTransitItem] = []
    for m in db.scalars(
        select(Movement).options(*_MOVEMENT_LOAD).where(Movement.status == MovementStatus.in_transit)
    ):
        items.append(InTransitItem(
            kind="movement", document_id=m.id, product=ProductOut.model_validate(m.product), qty=m.qty,
            source=m.from_warehouse.name, destination=m.to_warehouse.name, since=m.created_at,
        ))
    for s in db.scalars(
        select(FBOShipment).options(*_FBO_LOAD).where(FBOShipment.status == FBOStatus.in_transit)
    ):
        items.append(InTransitItem(
            kind="fbo", document_id=s.id, product=ProductOut.model_validate(s.product), qty=s.qty,
            source=s.warehouse.name, destination=FBO_DESTINATION, since=s.created_at,
        ))
    for o in db.scalars(
        select(FBSOrder).options(*_FBS_LOAD).where(FBSOrder.status == FBSStatus.shipped)
    ):
        items.append(InTransitItem(
            kind="fbs", document_id=o.id, product=ProductOut.model_validate(o.product), qty=o.qty,
            source=o.warehouse.name, destination=FBS_DESTINATION, since=o.shipped_at or o.created_at,
        ))
    items.sort(key=lambda item: item.since, reverse=True)
    return items


def list_receipts(db: Session, limit: int) -> list[Receipt]:
    return list(db.scalars(
        select(Receipt).options(*_RECEIPT_LOAD).order_by(Receipt.id.desc()).limit(limit)
    ))


def get_receipt(db: Session, receipt_id: int) -> Receipt:
    return _one(db, select(Receipt).options(*_RECEIPT_LOAD).where(Receipt.id == receipt_id), "Приход не найден")


def list_movements(db: Session, limit: int) -> list[Movement]:
    return list(db.scalars(
        select(Movement).options(*_MOVEMENT_LOAD).order_by(Movement.id.desc()).limit(limit)
    ))


def get_movement(db: Session, movement_id: int) -> Movement:
    return _one(
        db, select(Movement).options(*_MOVEMENT_LOAD).where(Movement.id == movement_id),
        "Перемещение не найдено",
    )


def list_fbs(db: Session, limit: int) -> list[FBSOrder]:
    return list(db.scalars(
        select(FBSOrder).options(*_FBS_LOAD).order_by(FBSOrder.id.desc()).limit(limit)
    ))


def get_fbs(db: Session, order_id: int) -> FBSOrder:
    return _one(db, select(FBSOrder).options(*_FBS_LOAD).where(FBSOrder.id == order_id), "Заказ FBS не найден")


def get_fbs_many(db: Session, order_ids: list[int]) -> list[FBSOrder]:
    return list(db.scalars(
        select(FBSOrder).options(*_FBS_LOAD).where(FBSOrder.id.in_(order_ids)).order_by(FBSOrder.id)
    ))


def list_fbo(db: Session, limit: int) -> list[FBOShipment]:
    return list(db.scalars(
        select(FBOShipment).options(*_FBO_LOAD).order_by(FBOShipment.id.desc()).limit(limit)
    ))


def get_fbo(db: Session, shipment_id: int) -> FBOShipment:
    return _one(
        db, select(FBOShipment).options(*_FBO_LOAD).where(FBOShipment.id == shipment_id),
        "Поставка FBO не найдена",
    )


def list_operations(db: Session, limit: int, product_id: Optional[int]) -> list[OperationLog]:
    query = select(OperationLog).order_by(OperationLog.id.desc()).limit(limit)
    if product_id is not None:
        query = query.where(OperationLog.product_id == product_id)
    return list(db.scalars(query))


def reconcile(db: Session) -> ReconcileOut:
    received: dict[int, int] = {
        pid: int(total) for pid, total in db.execute(
            select(Receipt.product_id, func.sum(Receipt.qty)).group_by(Receipt.product_id)
        ).all()
    }
    on_hand: dict[int, int] = {
        pid: int(total) for pid, total in db.execute(
            select(Inventory.product_id, func.sum(Inventory.physical_qty)).group_by(Inventory.product_id)
        ).all()
    }
    between: dict[int, int] = _sum_by_product(db, Movement, MovementStatus.in_transit)
    shipped_fbo: dict[int, int] = _sum_by_product(db, FBOShipment, FBOStatus.in_transit, FBOStatus.received)
    shipped_fbs: dict[int, int] = _sum_by_product(db, FBSOrder, FBSStatus.shipped, FBSStatus.delivered)

    products: list[ReconcileProduct] = []
    for product in list_products(db):
        pid: int = product.id
        accounted: int = (
            on_hand.get(pid, 0) + between.get(pid, 0) + shipped_fbo.get(pid, 0) + shipped_fbs.get(pid, 0)
        )
        products.append(ReconcileProduct(
            product=ProductOut.model_validate(product),
            received=received.get(pid, 0),
            on_hand=on_hand.get(pid, 0),
            in_transit_between_ff=between.get(pid, 0),
            shipped_fbo=shipped_fbo.get(pid, 0),
            shipped_fbs=shipped_fbs.get(pid, 0),
            balanced=accounted == received.get(pid, 0),
        ))

    reserved_orders: dict[tuple[int, int], int] = {
        (pid, wid): int(total) for pid, wid, total in db.execute(
            select(FBSOrder.product_id, FBSOrder.warehouse_id, func.sum(FBSOrder.qty))
            .where(FBSOrder.status == FBSStatus.reserved)
            .group_by(FBSOrder.product_id, FBSOrder.warehouse_id)
        ).all()
    }
    mismatches: list[ReserveMismatch] = [
        ReserveMismatch(
            product_id=inv.product_id, warehouse_id=inv.warehouse_id,
            inventory_reserved=inv.reserved_fbs_qty,
            orders_reserved=reserved_orders.get((inv.product_id, inv.warehouse_id), 0),
        )
        for inv in db.scalars(select(Inventory))
        if inv.reserved_fbs_qty != reserved_orders.get((inv.product_id, inv.warehouse_id), 0)
    ]

    return ReconcileOut(
        ok=all(p.balanced for p in products) and not mismatches,
        products=products,
        reserve_mismatches=mismatches,
    )


def _one(db: Session, query: Any, not_found: str) -> Any:
    result: Any = db.scalars(query).unique().one_or_none()
    if result is None:
        raise NotFound(not_found)
    return result
