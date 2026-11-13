# -*- coding: utf-8 -*-
import enum
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MovementStatus(str, enum.Enum):
    in_transit = "in_transit"
    confirmed = "confirmed"
    cancelled = "cancelled"


class FBSStatus(str, enum.Enum):
    reserved = "reserved"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class FBOStatus(str, enum.Enum):
    in_transit = "in_transit"
    received = "received"
    cancelled = "cancelled"


def _status_type(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_cls, name=name, native_enum=False, create_constraint=True,
        length=16, validate_strings=True,
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )


def _timestamp() -> Mapped[Optional[datetime]]:
    return mapped_column(DateTime(timezone=True))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        Index(
            "uq_warehouses_active_name", text("lower(name)"),
            unique=True, postgresql_where=text("NOT is_deleted"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()
    deleted_at: Mapped[Optional[datetime]] = _timestamp()


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id"),
        CheckConstraint("physical_qty >= 0", name="physical_nonneg"),
        CheckConstraint("reserved_fbs_qty >= 0", name="reserved_nonneg"),
        CheckConstraint("reserved_fbs_qty <= physical_qty", name="reserved_lte_physical"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    physical_qty: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    reserved_fbs_qty: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    @property
    def available_qty(self) -> int:
        return self.physical_qty - self.reserved_fbs_qty


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    qty: Mapped[int]
    created_at: Mapped[datetime] = _created_at()

    product: Mapped[Product] = relationship(lazy="raise")
    warehouse: Mapped[Warehouse] = relationship(lazy="raise")


class Movement(Base):
    __tablename__ = "movements"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("from_warehouse_id <> to_warehouse_id", name="distinct_warehouses"),
        Index("ix_movements_to_warehouse_status", "to_warehouse_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    qty: Mapped[int]
    status: Mapped[MovementStatus] = mapped_column(
        _status_type(MovementStatus, "movement_status"), default=MovementStatus.in_transit, index=True
    )
    created_at: Mapped[datetime] = _created_at()
    confirmed_at: Mapped[Optional[datetime]] = _timestamp()
    cancelled_at: Mapped[Optional[datetime]] = _timestamp()

    product: Mapped[Product] = relationship(lazy="raise")
    from_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[from_warehouse_id], lazy="raise")
    to_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[to_warehouse_id], lazy="raise")


class FBSOrder(Base):
    __tablename__ = "fbs_orders"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        Index("ix_fbs_orders_warehouse_status", "warehouse_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    qty: Mapped[int]
    status: Mapped[FBSStatus] = mapped_column(
        _status_type(FBSStatus, "fbs_status"), default=FBSStatus.reserved, index=True
    )
    created_at: Mapped[datetime] = _created_at()
    shipped_at: Mapped[Optional[datetime]] = _timestamp()
    delivered_at: Mapped[Optional[datetime]] = _timestamp()
    cancelled_at: Mapped[Optional[datetime]] = _timestamp()

    product: Mapped[Product] = relationship(lazy="raise")
    warehouse: Mapped[Warehouse] = relationship(lazy="raise")


class FBOShipment(Base):
    __tablename__ = "fbo_shipments"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    qty: Mapped[int]
    status: Mapped[FBOStatus] = mapped_column(
        _status_type(FBOStatus, "fbo_status"), default=FBOStatus.in_transit, index=True
    )
    created_at: Mapped[datetime] = _created_at()
    received_at: Mapped[Optional[datetime]] = _timestamp()
    cancelled_at: Mapped[Optional[datetime]] = _timestamp()

    product: Mapped[Product] = relationship(lazy="raise")
    warehouse: Mapped[Warehouse] = relationship(lazy="raise")


class OperationLog(Base):
    """Append-only journal. Names are snapshotted so history survives renames and deletions."""

    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), index=True)
    document_type: Mapped[Optional[str]] = mapped_column(String(16))
    document_id: Mapped[Optional[int]]
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), index=True)
    product_sku: Mapped[Optional[str]] = mapped_column(String(64))
    qty: Mapped[Optional[int]]
    source: Mapped[Optional[str]] = mapped_column(String(128))
    destination: Mapped[Optional[str]] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()
