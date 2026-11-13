# -*- coding: utf-8 -*-
import os
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("environment variable DATABASE_URL is required")

LOCK_TIMEOUT_MS: int = 5_000
STATEMENT_TIMEOUT_MS: int = 15_000
IDLE_IN_TRANSACTION_TIMEOUT_MS: int = 30_000

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={
        "options": (
            f"-c lock_timeout={LOCK_TIMEOUT_MS} "
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS} "
            f"-c idle_in_transaction_session_timeout={IDLE_IN_TRANSACTION_TIMEOUT_MS}"
        ),
        "application_name": "checkstock",
    },
)
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
