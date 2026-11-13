# -*- coding: utf-8 -*-
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")
TEST_DATABASE_URL: str = os.environ.setdefault(
    "TEST_DATABASE_URL",
    f"postgresql+psycopg2://checkstock:{os.environ.get('POSTGRES_PASSWORD', '')}@127.0.0.1:55432/checkstock_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
TEST_USERNAME: str = "manager"
TEST_PASSWORD: str = "test-password-not-for-prod"
os.environ["CHECKSTOCK_USERNAME"] = TEST_USERNAME
os.environ["CHECKSTOCK_PASSWORD"] = TEST_PASSWORD
os.environ["CHECKSTOCK_ALLOWED_HOSTS"] = "testserver"

import httpx2 as httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402


def _ensure_database(url: str) -> None:
    target: URL = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists: Any = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    _ensure_database(TEST_DATABASE_URL)
    from app.database import engine

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    config: Config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_data(_schema: None) -> Iterator[None]:
    from app.database import Base, SessionLocal, engine
    from app.seed import seed

    tables: str = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        seed(db)
    yield


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client: TestClient = client
        self._products: dict[str, int] = {p["sku"]: p["id"] for p in self.get("/products").json()}

    def get(self, path: str, **params: Any) -> httpx.Response:
        return self.client.get(f"/api{path}", params=params)

    def post(self, path: str, body: Any = None) -> httpx.Response:
        return self.client.post(f"/api{path}", json=body)

    def patch(self, path: str, body: Any) -> httpx.Response:
        return self.client.patch(f"/api{path}", json=body)

    def delete(self, path: str) -> httpx.Response:
        return self.client.delete(f"/api{path}")

    def product(self, sku: str) -> int:
        return self._products[sku]

    def warehouse(self, name: str) -> int:
        for wh in self.get("/warehouses", include_deleted=True).json():
            if wh["name"] == name:
                return wh["id"]
        raise KeyError(name)

    def row(self, sku: str) -> dict[str, Any]:
        matrix: dict[str, Any] = self.get("/stock").json()
        return next(r for r in matrix["rows"] if r["product"]["sku"] == sku)

    def cell(self, sku: str, warehouse: str) -> dict[str, Any]:
        warehouse_id: int = self.warehouse(warehouse)
        cell: dict[str, Any] = next(c for c in self.row(sku)["cells"] if c["warehouse_id"] == warehouse_id)
        return {k: cell[k] for k in ("physical", "reserved_fbs", "available")}

    def ok(self, response: httpx.Response, status: int = 200) -> Any:
        assert response.status_code == status, response.text
        return response.json()

    def error(self, response: httpx.Response, status: int, code: str) -> dict[str, Any]:
        assert response.status_code == status, response.text
        payload: dict[str, Any] = response.json()["error"]
        assert payload["code"] == code, payload
        return payload

    def reconciled(self) -> None:
        report: dict[str, Any] = self.ok(self.get("/stock/reconcile"))
        assert report["ok"], report


@pytest.fixture
def anonymous() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def api(anonymous: TestClient) -> Api:
    anonymous.auth = (TEST_USERNAME, TEST_PASSWORD)
    return Api(anonymous)


def stock(physical: int, reserved: int = 0) -> dict[str, int]:
    return {"physical": physical, "reserved_fbs": reserved, "available": physical - reserved}
