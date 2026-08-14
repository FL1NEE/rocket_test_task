# -*- coding: utf-8 -*-
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from migrate import get_engine
from models import metadata, raw_logs

TOTAL_ROWS: int = 200_000
DUPLICATE_RATIO: float = 0.15
INVALID_RATIO: float = 0.05
INSERT_BATCH_SIZE: int = 5_000
EVENT_TYPES: list[str] = ["login", "logout", "purchase", "error", "page_view"]


def generate_rows(total_rows: int) -> list[dict]:
    rows: list[dict] = []
    base_time: datetime = datetime.now(timezone.utc) - timedelta(days=30)

    unique_rows_needed: int = int(total_rows * (1 - DUPLICATE_RATIO - INVALID_RATIO))
    base_rows: list[dict] = []
    for i in range(unique_rows_needed):
        base_rows.append(
            {
                "user_id": random.randint(1, 5000),
                "event_type": random.choice(EVENT_TYPES),
                "message": f"event #{i} payload",
                "ip_address": f"192.168.{random.randint(0, 255)}.{random.randint(0, 255)}",
                "created_at": base_time + timedelta(seconds=random.randint(0, 30 * 24 * 3600))
            }
        )
    rows.extend(base_rows)

    duplicates_needed: int = int(total_rows * DUPLICATE_RATIO)
    for _ in range(duplicates_needed):
        rows.append(dict(random.choice(base_rows)))

    invalid_needed: int = total_rows - len(rows)
    for _ in range(invalid_needed):
        rows.append(
            {
                "user_id": None,
                "event_type": random.choice(EVENT_TYPES),
                "message": "invalid row (missing user_id)",
                "ip_address": None,
                "created_at": base_time
            }
        )

    random.shuffle(rows)
    return rows


def populate_raw_logs(total_rows: int = TOTAL_ROWS) -> None:
    engine: Engine = get_engine()
    metadata.create_all(engine, tables = [raw_logs], checkfirst = True)

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE raw_logs RESTART IDENTITY"))

    rows: list[dict] = generate_rows(total_rows)
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch: list[dict] = rows[start : start + INSERT_BATCH_SIZE]
        with engine.begin() as connection:
            connection.execute(raw_logs.insert(), batch)
        print(f"Вставлено {min(start + INSERT_BATCH_SIZE, len(rows))} / {len(rows)}")

    print(f"Готово: raw_logs заполнена {len(rows)} строками (с дублями и невалидными записями)")


if __name__ == "__main__":
    populate_raw_logs()