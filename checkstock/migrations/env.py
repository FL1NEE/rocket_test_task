# -*- coding: utf-8 -*-
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import Engine

import app.models  # noqa: F401  registers tables on Base.metadata
from app.database import DATABASE_URL, Base

engine: Engine = create_engine(DATABASE_URL)
config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as conn:
        run_migrations(conn)
    engine.dispose()
