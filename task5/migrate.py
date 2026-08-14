# -*- coding: utf-8 -*-
import logging
import os
import time

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from models import logs_optimized, metadata, migration_checkpoint, raw_logs

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/logs_db"
)
CLEAN_BATCH_SIZE: int = 20_000
MIGRATE_BATCH_SIZE: int = 20_000
MIGRATION_NAME: str = "raw_logs_to_logs_optimized"
DUPLICATES_STAGING_TABLE: str = "raw_logs_duplicate_ids"

logging.basicConfig(level = logging.INFO, format = "%(asctime)s [%(levelname)s] %(message)s")
logger: logging.Logger = logging.getLogger("migrate")


def get_engine() -> Engine:
    engine: Engine = create_engine(DATABASE_URL, pool_pre_ping = True, pool_size = 5, future = True)
    return engine


def ensure_control_tables(engine: Engine) -> None:
    metadata.create_all(engine, tables = [logs_optimized, migration_checkpoint], checkfirst = True)
    logger.info("Целевая таблица logs_optimized и таблица чекпоинтов готовы")


def delete_invalid_rows_in_batches(engine: Engine, batch_size: int = CLEAN_BATCH_SIZE) -> int:
    delete_query: text = text(
        """
        WITH batch AS (
            SELECT id FROM raw_logs
            WHERE user_id IS NULL OR event_type IS NULL OR created_at IS NULL
            LIMIT :batch_size
        )
        DELETE FROM raw_logs USING batch WHERE raw_logs.id = batch.id
        """
    )

    total_deleted: int = 0
    while True:
        with engine.begin() as connection:
            result = connection.execute(delete_query, {"batch_size": batch_size})
            deleted_in_batch: int = result.rowcount or 0
        total_deleted += deleted_in_batch
        if deleted_in_batch > 0:
            logger.info("Удалено невалидных строк: %s (всего: %s)", deleted_in_batch, total_deleted)
        if deleted_in_batch < batch_size:
            break

    logger.info("Очистка невалидных строк завершена, удалено всего: %s", total_deleted)
    return total_deleted


def stage_duplicate_ids(connection: Connection) -> None:
    connection.execute(text(f"DROP TABLE IF EXISTS {DUPLICATES_STAGING_TABLE}"))
    connection.execute(
        text(
            f"""
            CREATE UNLOGGED TABLE {DUPLICATES_STAGING_TABLE} AS
            SELECT id FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, event_type, created_at, message
                        ORDER BY id
                    ) AS row_num
                FROM raw_logs
            ) ranked
            WHERE row_num > 1
            """
        )
    )
    connection.execute(
        text(f"CREATE INDEX ON {DUPLICATES_STAGING_TABLE} (id)")
    )


def delete_staged_duplicates_in_batches(engine: Engine, batch_size: int = CLEAN_BATCH_SIZE) -> int:
    delete_query: text = text(
        f"""
        WITH batch AS (
            SELECT id FROM {DUPLICATES_STAGING_TABLE} LIMIT :batch_size
        )
        DELETE FROM raw_logs USING batch WHERE raw_logs.id = batch.id
        """
    )
    cleanup_staged_query: text = text(
        f"""
        DELETE FROM {DUPLICATES_STAGING_TABLE}
        WHERE id IN (SELECT id FROM {DUPLICATES_STAGING_TABLE} LIMIT :batch_size)
        """
    )

    total_deleted: int = 0
    while True:
        with engine.begin() as connection:
            result = connection.execute(delete_query, {"batch_size": batch_size})
            deleted_in_batch: int = result.rowcount or 0
            connection.execute(cleanup_staged_query, {"batch_size": batch_size})
        total_deleted += deleted_in_batch
        if deleted_in_batch > 0:
            logger.info("Удалено дублей: %s (всего: %s)", deleted_in_batch, total_deleted)
        if deleted_in_batch < batch_size:
            break

    logger.info("Удаление дублей завершено, удалено всего: %s", total_deleted)
    return total_deleted


def clean_raw_logs(engine: Engine) -> None:
    logger.info("Шаг 1: очистка raw_logs")
    delete_invalid_rows_in_batches(engine)

    with engine.begin() as connection:
        stage_duplicate_ids(connection)

    delete_staged_duplicates_in_batches(engine)

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {DUPLICATES_STAGING_TABLE}"))


def get_checkpoint(engine: Engine) -> int:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT last_processed_id FROM migration_checkpoint WHERE migration_name = :name"),
            {"name": MIGRATION_NAME},
        ).fetchone()
        if row is None:
            connection.execute(
                text(
                    "INSERT INTO migration_checkpoint (migration_name, last_processed_id) "
                    "VALUES (:name, 0)"
                ),
                {"name": MIGRATION_NAME},
            )
            return 0
        return int(row[0])


def save_checkpoint(connection: Connection, last_id: int) -> None:
    connection.execute(
        text(
            "UPDATE migration_checkpoint SET last_processed_id = :last_id "
            "WHERE migration_name = :name"
        ),
        {"last_id": last_id, "name": MIGRATION_NAME},
    )


def migrate_to_optimized(engine: Engine, batch_size: int = MIGRATE_BATCH_SIZE) -> int:
    logger.info("Шаг 2: перенос данных в logs_optimized")
    last_id: int = get_checkpoint(engine)
    total_migrated: int = 0

    batch_query: text = text(
        """
        WITH batch AS (
            SELECT id, user_id, event_type, message, ip_address, created_at
            FROM raw_logs
            WHERE id > :last_id
            ORDER BY id
            LIMIT :batch_size
        ),
        inserted AS (
            INSERT INTO logs_optimized (id, user_id, event_type, message, ip_address, created_at)
            SELECT id, user_id, event_type, message, ip_address, created_at FROM batch
            ON CONFLICT ON CONSTRAINT uq_logs_optimized_natural_key DO NOTHING
            RETURNING id
        )
        SELECT
            (SELECT MAX(id) FROM batch) AS batch_max_id,
            (SELECT COUNT(*) FROM batch) AS batch_count,
            (SELECT COUNT(*) FROM inserted) AS inserted_count
        """
    )

    while True:
        with engine.begin() as connection:
            row = connection.execute(
                batch_query, {"last_id": last_id, "batch_size": batch_size}
            ).one()
            batch_max_id, batch_count, inserted_count = row

            if batch_count == 0:
                break

            total_migrated += inserted_count
            last_id = int(batch_max_id)
            save_checkpoint(connection, last_id)

        logger.info(
            "Обработан батч из %s строк, вставлено новых: %s (checkpoint id=%s, всего вставлено: %s)",
            batch_count,
            inserted_count,
            last_id,
            total_migrated,
        )

    logger.info("Перенос данных завершён, всего вставлено новых строк: %s", total_migrated)
    return total_migrated

def create_indexes(engine: Engine) -> None:
    logger.info("Шаг 3: создание индексов на logs_optimized")
    index_statements: list[str] = [
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_logs_optimized_user_id "
        "ON logs_optimized (user_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_logs_optimized_event_type "
        "ON logs_optimized (event_type)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_logs_optimized_created_at "
        "ON logs_optimized (created_at)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_logs_optimized_user_created "
        "ON logs_optimized (user_id, created_at)",
    ]

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in index_statements:
            started_at: float = time.monotonic()
            connection.execute(text(statement))
            elapsed_seconds: float = time.monotonic() - started_at
            logger.info("Индекс создан за %.1f сек: %s", elapsed_seconds, statement.split(" ON ")[0])

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("VACUUM ANALYZE logs_optimized"))
    logger.info("VACUUM ANALYZE выполнен")


def run_migration() -> None:
    engine: Engine = get_engine()
    ensure_control_tables(engine)
    clean_raw_logs(engine)
    migrate_to_optimized(engine)
    create_indexes(engine)
    logger.info("Миграция завершена успешно")


if __name__ == "__main__":
    run_migration()