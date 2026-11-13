# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.models import Movement
from app.routers.common import DbSession, IdPath, Limit
from app.schemas import MovementCreate, MovementOut
from app.services import commands, queries

router: APIRouter = APIRouter(prefix="/movements", tags=["movements"])


@router.get("", response_model=list[MovementOut])
def list_movements(db: DbSession, limit: Limit = 100) -> list[Movement]:
    return queries.list_movements(db, limit)


@router.post("", response_model=MovementOut, status_code=201)
def create_movement(body: MovementCreate, db: DbSession) -> Movement:
    movement: Movement = commands.create_movement(
        db, body.product_id, body.from_warehouse_id, body.to_warehouse_id, body.qty
    )
    return queries.get_movement(db, movement.id)


@router.post("/{movement_id}/confirm", response_model=MovementOut)
def confirm_movement(movement_id: IdPath, db: DbSession) -> Movement:
    commands.confirm_movement(db, movement_id)
    return queries.get_movement(db, movement_id)


@router.post("/{movement_id}/cancel", response_model=MovementOut)
def cancel_movement(movement_id: IdPath, db: DbSession) -> Movement:
    commands.cancel_movement(db, movement_id)
    return queries.get_movement(db, movement_id)
