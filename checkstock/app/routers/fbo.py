# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.models import FBOShipment
from app.routers.common import DbSession, IdPath, Limit
from app.schemas import FBOOut, ShipmentCreate
from app.services import commands, queries

router: APIRouter = APIRouter(prefix="/fbo", tags=["fbo"])


@router.get("", response_model=list[FBOOut])
def list_fbo(db: DbSession, limit: Limit = 100) -> list[FBOShipment]:
    return queries.list_fbo(db, limit)


@router.post("", response_model=FBOOut, status_code=201)
def create_fbo(body: ShipmentCreate, db: DbSession) -> FBOShipment:
    shipment: FBOShipment = commands.create_fbo(db, body.product_id, body.warehouse_id, body.qty)
    return queries.get_fbo(db, shipment.id)


@router.post("/{shipment_id}/receive", response_model=FBOOut)
def receive_fbo(shipment_id: IdPath, db: DbSession) -> FBOShipment:
    commands.receive_fbo(db, shipment_id)
    return queries.get_fbo(db, shipment_id)


@router.post("/{shipment_id}/cancel", response_model=FBOOut)
def cancel_fbo(shipment_id: IdPath, db: DbSession) -> FBOShipment:
    commands.cancel_fbo(db, shipment_id)
    return queries.get_fbo(db, shipment_id)
