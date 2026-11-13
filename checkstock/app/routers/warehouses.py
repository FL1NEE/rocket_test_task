# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.models import Warehouse
from app.routers.common import DbSession, IdPath
from app.schemas import WarehouseCreate, WarehouseOut, WarehouseRename
from app.services import commands, queries

router: APIRouter = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("", response_model=list[WarehouseOut])
def list_warehouses(db: DbSession, include_deleted: bool = False) -> list[Warehouse]:
    return queries.list_warehouses(db, include_deleted)


@router.post("", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseCreate, db: DbSession) -> Warehouse:
    return commands.create_warehouse(db, body.name)


@router.patch("/{warehouse_id}", response_model=WarehouseOut)
def rename_warehouse(warehouse_id: IdPath, body: WarehouseRename, db: DbSession) -> Warehouse:
    return commands.rename_warehouse(db, warehouse_id, body.name)


@router.delete("/{warehouse_id}", response_model=WarehouseOut)
def delete_warehouse(warehouse_id: IdPath, db: DbSession) -> Warehouse:
    return commands.delete_warehouse(db, warehouse_id)
