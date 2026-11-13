# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

from app.models import FBOStatus, FBSStatus, MovementStatus

MAX_QTY: int = 1_000_000
MAX_ID: int = 2_147_483_647

Qty = Annotated[StrictInt, Field(gt=0, le=MAX_QTY)]
EntityId = Annotated[StrictInt, Field(gt=0, le=MAX_ID)]
WarehouseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WarehouseCreate(_In):
    name: WarehouseName


class WarehouseRename(_In):
    name: WarehouseName


class ReceiptCreate(_In):
    product_id: EntityId
    warehouse_id: EntityId
    qty: Qty


class MovementCreate(_In):
    product_id: EntityId
    from_warehouse_id: EntityId
    to_warehouse_id: EntityId
    qty: Qty

    @model_validator(mode="after")
    def _distinct_warehouses(self) -> "MovementCreate":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("склад отправления и склад назначения должны различаться")
        return self


class ShipmentCreate(_In):
    product_id: EntityId
    warehouse_id: EntityId
    qty: Qty


class FBSAllocate(_In):
    product_id: EntityId
    qty: Qty
    preferred_warehouse_id: Optional[EntityId] = None


class ProductOut(_Out):
    id: int
    sku: str
    name: str


class WarehouseRef(_Out):
    id: int
    name: str
    is_deleted: bool


class WarehouseOut(WarehouseRef):
    created_at: datetime
    deleted_at: Optional[datetime]


class ReceiptOut(_Out):
    id: int
    product: ProductOut
    warehouse: WarehouseRef
    qty: int
    created_at: datetime


class MovementOut(_Out):
    id: int
    product: ProductOut
    from_warehouse: WarehouseRef
    to_warehouse: WarehouseRef
    qty: int
    status: MovementStatus
    created_at: datetime
    confirmed_at: Optional[datetime]
    cancelled_at: Optional[datetime]


class FBSOut(_Out):
    id: int
    product: ProductOut
    warehouse: WarehouseRef
    qty: int
    status: FBSStatus
    created_at: datetime
    shipped_at: Optional[datetime]
    delivered_at: Optional[datetime]
    cancelled_at: Optional[datetime]


class FBOOut(_Out):
    id: int
    product: ProductOut
    warehouse: WarehouseRef
    qty: int
    status: FBOStatus
    created_at: datetime
    received_at: Optional[datetime]
    cancelled_at: Optional[datetime]


class StockCell(BaseModel):
    warehouse_id: int
    physical: int
    reserved_fbs: int
    available: int


class StockRow(BaseModel):
    product: ProductOut
    cells: list[StockCell]
    total_physical: int
    total_reserved_fbs: int
    total_available: int
    in_transit_between_ff: int
    in_transit_to_fbo: int
    in_transit_to_client: int


class StockMatrixOut(BaseModel):
    warehouses: list[WarehouseRef]
    rows: list[StockRow]


class InTransitItem(BaseModel):
    kind: Literal["movement", "fbo", "fbs"]
    document_id: int
    product: ProductOut
    qty: int
    source: str
    destination: str
    since: datetime


class OperationOut(_Out):
    id: int
    operation: str
    document_type: Optional[str]
    document_id: Optional[int]
    product_sku: Optional[str]
    qty: Optional[int]
    source: Optional[str]
    destination: Optional[str]
    details: dict[str, Any]
    created_at: datetime


class ReconcileProduct(BaseModel):
    product: ProductOut
    received: int
    on_hand: int
    in_transit_between_ff: int
    shipped_fbo: int
    shipped_fbs: int
    balanced: bool


class ReserveMismatch(BaseModel):
    product_id: int
    warehouse_id: int
    inventory_reserved: int
    orders_reserved: int


class ReconcileOut(BaseModel):
    ok: bool
    products: list[ReconcileProduct]
    reserve_mismatches: list[ReserveMismatch]
