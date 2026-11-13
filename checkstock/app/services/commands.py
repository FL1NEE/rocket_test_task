# -*- coding: utf-8 -*-
"""Write side. Lock order is always: warehouse -> document -> inventory, which rules out deadlocks."""
import enum
from typing import Any, Optional, TypeVar

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, InsufficientStock, InvalidState, NotFound
from app.models import (
    FBOShipment, FBOStatus, FBSOrder, FBSStatus, Inventory, Movement, MovementStatus,
    OperationLog, Product, Receipt, Warehouse, utcnow,
)

T = TypeVar("T", Movement, FBSOrder, FBOShipment)

FBO_DESTINATION: str = "Склад маркетплейса (FBO)"
FBS_DESTINATION: str = "Клиент (FBS)"

STATUS_LABELS: dict[enum.Enum, str] = {
    MovementStatus.in_transit: "в пути",
    MovementStatus.confirmed: "принято",
    MovementStatus.cancelled: "отменено",
    FBSStatus.reserved: "в резерве",
    FBSStatus.shipped: "отправлен",
    FBSStatus.delivered: "доставлен",
    FBSStatus.cancelled: "отменён",
    FBOStatus.in_transit: "в пути",
    FBOStatus.received: "принято маркетплейсом",
    FBOStatus.cancelled: "отменено",
}


def _product(db: Session, product_id: int) -> Product:
    product: Optional[Product] = db.get(Product, product_id)
    if product is None:
        raise NotFound("Товар не найден", product_id=product_id)
    return product


def _lock_warehouse(
    db: Session, warehouse_id: int, *, require_active: bool, exclusive: bool = False
) -> Warehouse:
    lock: Any = True if exclusive else {"read": True}
    warehouse: Optional[Warehouse] = db.get(
        Warehouse, warehouse_id, with_for_update=lock, populate_existing=True
    )
    if warehouse is None:
        raise NotFound("Склад не найден", warehouse_id=warehouse_id)
    if require_active and warehouse.is_deleted:
        raise Conflict(
            f"Склад «{warehouse.name}» удалён: с него можно только вывезти товар",
            code="warehouse_deleted", warehouse_id=warehouse_id,
        )
    return warehouse


def _lock_inventory(db: Session, product_id: int, warehouse_id: int) -> Inventory:
    db.execute(
        insert(Inventory)
        .values(product_id=product_id, warehouse_id=warehouse_id)
        .on_conflict_do_nothing(index_elements=["product_id", "warehouse_id"])
    )
    return db.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _lock_document(db: Session, model: type[T], document_id: int, not_found: str) -> T:
    document: Optional[T] = db.get(model, document_id, with_for_update=True, populate_existing=True)
    if document is None:
        raise NotFound(not_found, document_id=document_id)
    return document


def _require_status(document: T, expected: enum.Enum, action: str) -> None:
    if document.status != expected:
        raise InvalidState(
            f"Нельзя {action}: документ уже в статусе «{STATUS_LABELS[document.status]}»",
            status=document.status.value,
        )


def _availability(db: Session, product_id: int, exclude_warehouse_id: int) -> list[dict[str, Any]]:
    available = Inventory.physical_qty - Inventory.reserved_fbs_qty
    rows = db.execute(
        select(Warehouse.id, Warehouse.name, available)
        .join(Inventory, Inventory.warehouse_id == Warehouse.id)
        .where(
            Inventory.product_id == product_id,
            Warehouse.is_deleted.is_(False),
            Warehouse.id != exclude_warehouse_id,
            available > 0,
        )
        .order_by(available.desc(), Warehouse.id)
    ).all()
    return [{"warehouse_id": wid, "warehouse": name, "available": qty} for wid, name, qty in rows]


def _insufficient(
    db: Session, product: Product, warehouse: Warehouse, inventory: Inventory, qty: int
) -> InsufficientStock:
    alternatives: list[dict[str, Any]] = _availability(db, product.id, warehouse.id)
    total: int = inventory.available_qty + sum(a["available"] for a in alternatives)
    return InsufficientStock(
        f"На складе «{warehouse.name}» доступно {inventory.available_qty} шт. {product.sku}, "
        f"запрошено {qty}",
        requested=qty,
        available=inventory.available_qty,
        total_available=total,
        alternatives=alternatives,
        can_split=total >= qty,
    )


def _journal(
    db: Session,
    operation: str,
    *,
    product: Optional[Product] = None,
    qty: Optional[int] = None,
    source: Optional[str] = None,
    destination: Optional[str] = None,
    document_type: Optional[str] = None,
    document_id: Optional[int] = None,
    **details: Any,
) -> None:
    db.add(OperationLog(
        operation=operation,
        document_type=document_type,
        document_id=document_id,
        product_id=product.id if product else None,
        product_sku=product.sku if product else None,
        qty=qty,
        source=source,
        destination=destination,
        details=details,
    ))


def _ensure_unique_name(db: Session, name: str, exclude_id: Optional[int] = None) -> None:
    query = select(Warehouse.id).where(
        func.lower(Warehouse.name) == name.lower(), Warehouse.is_deleted.is_(False)
    )
    if exclude_id is not None:
        query = query.where(Warehouse.id != exclude_id)
    if db.scalar(query) is not None:
        raise Conflict(f"Склад «{name}» уже существует", code="duplicate_name")


def _commit_unique_name(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Склад «{name}» уже существует", code="duplicate_name") from exc


def create_warehouse(db: Session, name: str) -> Warehouse:
    _ensure_unique_name(db, name)
    warehouse: Warehouse = Warehouse(name=name)
    db.add(warehouse)
    db.flush()
    _journal(db, "warehouse_created", destination=name, document_type="warehouse", document_id=warehouse.id)
    _commit_unique_name(db, name)
    return warehouse


def rename_warehouse(db: Session, warehouse_id: int, name: str) -> Warehouse:
    warehouse: Warehouse = _lock_warehouse(db, warehouse_id, require_active=True, exclusive=True)
    if warehouse.name == name:
        return warehouse
    _ensure_unique_name(db, name, exclude_id=warehouse.id)
    old_name: str = warehouse.name
    warehouse.name = name
    _journal(
        db, "warehouse_renamed", source=old_name, destination=name,
        document_type="warehouse", document_id=warehouse.id,
    )
    _commit_unique_name(db, name)
    return warehouse


def delete_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse: Warehouse = _lock_warehouse(db, warehouse_id, require_active=True, exclusive=True)

    inbound: int = db.scalar(
        select(func.count()).select_from(Movement).where(
            Movement.to_warehouse_id == warehouse.id,
            Movement.status == MovementStatus.in_transit,
        )
    ) or 0
    if inbound:
        raise Conflict(
            f"На склад «{warehouse.name}» едут перемещения ({inbound} шт.): "
            "подтвердите или отмените их перед удалением",
            code="inbound_in_transit", movements=inbound,
        )

    physical_left, reserved_left = db.execute(
        select(
            func.coalesce(func.sum(Inventory.physical_qty), 0),
            func.coalesce(func.sum(Inventory.reserved_fbs_qty), 0),
        ).where(Inventory.warehouse_id == warehouse.id)
    ).one()

    warehouse.is_deleted = True
    warehouse.deleted_at = utcnow()
    _journal(
        db, "warehouse_deleted", source=warehouse.name, document_type="warehouse",
        document_id=warehouse.id, physical_left=int(physical_left), reserved_left=int(reserved_left),
    )
    db.commit()
    return warehouse


def create_receipt(db: Session, product_id: int, warehouse_id: int, qty: int) -> Receipt:
    warehouse: Warehouse = _lock_warehouse(db, warehouse_id, require_active=True)
    product: Product = _product(db, product_id)

    inventory: Inventory = _lock_inventory(db, product.id, warehouse.id)
    inventory.physical_qty += qty

    receipt: Receipt = Receipt(product_id=product.id, warehouse_id=warehouse.id, qty=qty)
    db.add(receipt)
    db.flush()
    _journal(
        db, "receipt", product=product, qty=qty, source="Поставщик", destination=warehouse.name,
        document_type="receipt", document_id=receipt.id,
    )
    db.commit()
    return receipt


def create_movement(
    db: Session, product_id: int, from_warehouse_id: int, to_warehouse_id: int, qty: int
) -> Movement:
    source: Warehouse = _lock_warehouse(db, from_warehouse_id, require_active=False)
    destination: Warehouse = _lock_warehouse(db, to_warehouse_id, require_active=True)
    product: Product = _product(db, product_id)

    inventory: Inventory = _lock_inventory(db, product.id, source.id)
    if inventory.available_qty < qty:
        raise _insufficient(db, product, source, inventory, qty)
    inventory.physical_qty -= qty

    movement: Movement = Movement(
        product_id=product.id, from_warehouse_id=source.id, to_warehouse_id=destination.id, qty=qty
    )
    db.add(movement)
    db.flush()
    _journal(
        db, "movement_sent", product=product, qty=qty, source=source.name,
        destination=destination.name, document_type="movement", document_id=movement.id,
    )
    db.commit()
    return movement


def confirm_movement(db: Session, movement_id: int) -> Movement:
    movement: Movement = _lock_document(db, Movement, movement_id, "Перемещение не найдено")
    _require_status(movement, MovementStatus.in_transit, "принять перемещение")

    inventory: Inventory = _lock_inventory(db, movement.product_id, movement.to_warehouse_id)
    inventory.physical_qty += movement.qty
    movement.status = MovementStatus.confirmed
    movement.confirmed_at = utcnow()

    source: Warehouse = db.get_one(Warehouse, movement.from_warehouse_id)
    destination: Warehouse = db.get_one(Warehouse, movement.to_warehouse_id)
    _journal(
        db, "movement_received", product=db.get_one(Product, movement.product_id), qty=movement.qty,
        source=source.name, destination=destination.name,
        document_type="movement", document_id=movement.id,
    )
    db.commit()
    return movement


def cancel_movement(db: Session, movement_id: int) -> Movement:
    movement: Movement = _lock_document(db, Movement, movement_id, "Перемещение не найдено")
    _require_status(movement, MovementStatus.in_transit, "отменить перемещение")

    inventory: Inventory = _lock_inventory(db, movement.product_id, movement.from_warehouse_id)
    inventory.physical_qty += movement.qty
    movement.status = MovementStatus.cancelled
    movement.cancelled_at = utcnow()

    source: Warehouse = db.get_one(Warehouse, movement.from_warehouse_id)
    _journal(
        db, "movement_cancelled", product=db.get_one(Product, movement.product_id), qty=movement.qty,
        source="В пути", destination=source.name, document_type="movement", document_id=movement.id,
    )
    db.commit()
    return movement


def create_fbs(db: Session, product_id: int, warehouse_id: int, qty: int) -> FBSOrder:
    warehouse: Warehouse = _lock_warehouse(db, warehouse_id, require_active=True)
    product: Product = _product(db, product_id)

    inventory: Inventory = _lock_inventory(db, product.id, warehouse.id)
    if inventory.available_qty < qty:
        raise _insufficient(db, product, warehouse, inventory, qty)

    order: FBSOrder = _reserve(db, product, warehouse, inventory, qty)
    db.commit()
    return order


def allocate_fbs(
    db: Session, product_id: int, qty: int, preferred_warehouse_id: Optional[int]
) -> list[FBSOrder]:
    product: Product = _product(db, product_id)
    warehouses: dict[int, Warehouse] = {
        wh.id: wh for wh in db.scalars(
            select(Warehouse)
            .where(Warehouse.is_deleted.is_(False))
            .order_by(Warehouse.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    if preferred_warehouse_id is not None and preferred_warehouse_id not in warehouses:
        raise NotFound("Склад не найден или удалён", warehouse_id=preferred_warehouse_id)

    inventories: list[Inventory] = list(db.scalars(
        select(Inventory)
        .where(Inventory.product_id == product.id, Inventory.warehouse_id.in_(list(warehouses)))
        .order_by(Inventory.warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ))
    total: int = sum(max(inv.available_qty, 0) for inv in inventories)
    if total < qty:
        raise InsufficientStock(
            f"На всех складах доступно {total} шт. {product.sku}, запрошено {qty}",
            requested=qty, available=total, total_available=total, alternatives=[], can_split=False,
        )

    inventories.sort(key=lambda inv: (
        inv.warehouse_id != preferred_warehouse_id, -inv.available_qty, inv.warehouse_id
    ))
    orders: list[FBSOrder] = []
    remaining: int = qty
    for inventory in inventories:
        take: int = min(inventory.available_qty, remaining)
        if take <= 0:
            continue
        orders.append(_reserve(db, product, warehouses[inventory.warehouse_id], inventory, take))
        remaining -= take
        if remaining == 0:
            break

    db.commit()
    return orders


def _reserve(
    db: Session, product: Product, warehouse: Warehouse, inventory: Inventory, qty: int
) -> FBSOrder:
    inventory.reserved_fbs_qty += qty
    order: FBSOrder = FBSOrder(product_id=product.id, warehouse_id=warehouse.id, qty=qty)
    db.add(order)
    db.flush()
    _journal(
        db, "fbs_reserved", product=product, qty=qty, source=warehouse.name,
        destination=f"Резерв FBS · {warehouse.name}", document_type="fbs", document_id=order.id,
    )
    return order


def ship_fbs(db: Session, order_id: int) -> FBSOrder:
    order: FBSOrder = _lock_document(db, FBSOrder, order_id, "Заказ FBS не найден")
    _require_status(order, FBSStatus.reserved, "отправить заказ")

    inventory: Inventory = _lock_inventory(db, order.product_id, order.warehouse_id)
    inventory.reserved_fbs_qty -= order.qty
    inventory.physical_qty -= order.qty
    order.status = FBSStatus.shipped
    order.shipped_at = utcnow()

    _journal(
        db, "fbs_shipped", product=db.get_one(Product, order.product_id), qty=order.qty,
        source=db.get_one(Warehouse, order.warehouse_id).name, destination=FBS_DESTINATION,
        document_type="fbs", document_id=order.id,
    )
    db.commit()
    return order


def deliver_fbs(db: Session, order_id: int) -> FBSOrder:
    order: FBSOrder = _lock_document(db, FBSOrder, order_id, "Заказ FBS не найден")
    _require_status(order, FBSStatus.shipped, "отметить доставку")

    order.status = FBSStatus.delivered
    order.delivered_at = utcnow()
    _journal(
        db, "fbs_delivered", product=db.get_one(Product, order.product_id), qty=order.qty,
        source="В пути", destination=FBS_DESTINATION, document_type="fbs", document_id=order.id,
    )
    db.commit()
    return order


def cancel_fbs(db: Session, order_id: int) -> FBSOrder:
    order: FBSOrder = _lock_document(db, FBSOrder, order_id, "Заказ FBS не найден")
    _require_status(order, FBSStatus.reserved, "снять резерв")

    inventory: Inventory = _lock_inventory(db, order.product_id, order.warehouse_id)
    inventory.reserved_fbs_qty -= order.qty
    order.status = FBSStatus.cancelled
    order.cancelled_at = utcnow()

    warehouse_name: str = db.get_one(Warehouse, order.warehouse_id).name
    _journal(
        db, "fbs_cancelled", product=db.get_one(Product, order.product_id), qty=order.qty,
        source=f"Резерв FBS · {warehouse_name}", destination=warehouse_name,
        document_type="fbs", document_id=order.id,
    )
    db.commit()
    return order


def create_fbo(db: Session, product_id: int, warehouse_id: int, qty: int) -> FBOShipment:
    warehouse: Warehouse = _lock_warehouse(db, warehouse_id, require_active=False)
    product: Product = _product(db, product_id)

    inventory: Inventory = _lock_inventory(db, product.id, warehouse.id)
    if inventory.available_qty < qty:
        raise _insufficient(db, product, warehouse, inventory, qty)
    inventory.physical_qty -= qty

    shipment: FBOShipment = FBOShipment(product_id=product.id, warehouse_id=warehouse.id, qty=qty)
    db.add(shipment)
    db.flush()
    _journal(
        db, "fbo_shipped", product=product, qty=qty, source=warehouse.name,
        destination=FBO_DESTINATION, document_type="fbo", document_id=shipment.id,
    )
    db.commit()
    return shipment


def receive_fbo(db: Session, shipment_id: int) -> FBOShipment:
    shipment: FBOShipment = _lock_document(db, FBOShipment, shipment_id, "Поставка FBO не найдена")
    _require_status(shipment, FBOStatus.in_transit, "подтвердить приёмку")

    shipment.status = FBOStatus.received
    shipment.received_at = utcnow()
    _journal(
        db, "fbo_received", product=db.get_one(Product, shipment.product_id), qty=shipment.qty,
        source="В пути", destination=FBO_DESTINATION, document_type="fbo", document_id=shipment.id,
    )
    db.commit()
    return shipment


def cancel_fbo(db: Session, shipment_id: int) -> FBOShipment:
    shipment: FBOShipment = _lock_document(db, FBOShipment, shipment_id, "Поставка FBO не найдена")
    _require_status(shipment, FBOStatus.in_transit, "отменить поставку")

    inventory: Inventory = _lock_inventory(db, shipment.product_id, shipment.warehouse_id)
    inventory.physical_qty += shipment.qty
    shipment.status = FBOStatus.cancelled
    shipment.cancelled_at = utcnow()

    _journal(
        db, "fbo_cancelled", product=db.get_one(Product, shipment.product_id), qty=shipment.qty,
        source="В пути", destination=db.get_one(Warehouse, shipment.warehouse_id).name,
        document_type="fbo", document_id=shipment.id,
    )
    db.commit()
    return shipment
