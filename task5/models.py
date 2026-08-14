# -*- coding: utf-8 -*-
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata: MetaData = MetaData()

raw_logs: Table = Table(
    "raw_logs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=True),
    Column("event_type", String(100), nullable=True),
    Column("message", Text, nullable=True),
    Column("ip_address", String(45), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=True),
)

logs_optimized: Table = Table(
    "logs_optimized",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("message", Text, nullable=False),
    Column("ip_address", String(45), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "user_id", "event_type", "created_at", "message", name="uq_logs_optimized_natural_key"
    ),
)

migration_checkpoint: Table = Table(
    "migration_checkpoint",
    metadata,
    Column("migration_name", String(100), primary_key=True),
    Column("last_processed_id", BigInteger, nullable=False, server_default="0"),
)