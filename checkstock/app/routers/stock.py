# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.models import Product, Receipt
from app.routers.common import DbSession, Limit
from app.schemas import (
    InTransitItem, ProductOut, ReceiptCreate, ReceiptOut, ReconcileOut, StockMatrixOut,
)
from app.services import commands, queries

router: APIRouter = APIRouter(tags=["stock"])


@router.get("/products", response_model=list[ProductOut])
def list_products(db: DbSession) -> list[Product]:
    return queries.list_products(db)


@router.get("/stock", response_model=StockMatrixOut)
def stock_matrix(db: DbSession) -> StockMatrixOut:
    return queries.stock_matrix(db)


@router.get("/stock/in-transit", response_model=list[InTransitItem])
def in_transit(db: DbSession) -> list[InTransitItem]:
    return queries.in_transit(db)


@router.get("/stock/reconcile", response_model=ReconcileOut)
def reconcile(db: DbSession) -> ReconcileOut:
    return queries.reconcile(db)


@router.get("/receipts", response_model=list[ReceiptOut])
def list_receipts(db: DbSession, limit: Limit = 100) -> list[Receipt]:
    return queries.list_receipts(db, limit)


@router.post("/receipts", response_model=ReceiptOut, status_code=201)
def create_receipt(body: ReceiptCreate, db: DbSession) -> Receipt:
    receipt: Receipt = commands.create_receipt(db, body.product_id, body.warehouse_id, body.qty)
    return queries.get_receipt(db, receipt.id)
