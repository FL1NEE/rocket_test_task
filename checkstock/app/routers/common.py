# -*- coding: utf-8 -*-
from typing import Annotated

from fastapi import Depends, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import MAX_ID

DbSession = Annotated[Session, Depends(get_db)]
IdPath = Annotated[int, Path(gt=0, le=MAX_ID)]
Limit = Annotated[int, Query(ge=1, le=500)]
