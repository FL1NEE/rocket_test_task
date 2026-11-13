# -*- coding: utf-8 -*-
from typing import Annotated, Optional

from fastapi import APIRouter, Query

from app.models import OperationLog
from app.routers.common import DbSession, Limit
from app.schemas import MAX_ID, OperationOut
from app.services import queries

router: APIRouter = APIRouter(prefix="/operations", tags=["operations"])


@router.get("", response_model=list[OperationOut])
def list_operations(
    db: DbSession,
    limit: Limit = 200,
    product_id: Annotated[Optional[int], Query(gt=0, le=MAX_ID)] = None,
) -> list[OperationLog]:
    return queries.list_operations(db, limit, product_id)
