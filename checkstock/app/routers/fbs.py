# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.models import FBSOrder
from app.routers.common import DbSession, IdPath, Limit
from app.schemas import FBSAllocate, FBSOut, ShipmentCreate
from app.services import commands, queries

router: APIRouter = APIRouter(prefix="/fbs", tags=["fbs"])


@router.get("", response_model=list[FBSOut])
def list_fbs(db: DbSession, limit: Limit = 100) -> list[FBSOrder]:
    return queries.list_fbs(db, limit)


@router.post("", response_model=FBSOut, status_code=201)
def create_fbs(body: ShipmentCreate, db: DbSession) -> FBSOrder:
    order: FBSOrder = commands.create_fbs(db, body.product_id, body.warehouse_id, body.qty)
    return queries.get_fbs(db, order.id)


@router.post("/allocate", response_model=list[FBSOut], status_code=201)
def allocate_fbs(body: FBSAllocate, db: DbSession) -> list[FBSOrder]:
    orders: list[FBSOrder] = commands.allocate_fbs(
        db, body.product_id, body.qty, body.preferred_warehouse_id
    )
    return queries.get_fbs_many(db, [o.id for o in orders])


@router.post("/{order_id}/ship", response_model=FBSOut)
def ship_fbs(order_id: IdPath, db: DbSession) -> FBSOrder:
    commands.ship_fbs(db, order_id)
    return queries.get_fbs(db, order_id)


@router.post("/{order_id}/deliver", response_model=FBSOut)
def deliver_fbs(order_id: IdPath, db: DbSession) -> FBSOrder:
    commands.deliver_fbs(db, order_id)
    return queries.get_fbs(db, order_id)


@router.post("/{order_id}/cancel", response_model=FBSOut)
def cancel_fbs(order_id: IdPath, db: DbSession) -> FBSOrder:
    commands.cancel_fbs(db, order_id)
    return queries.get_fbs(db, order_id)
