# -*- coding: utf-8 -*-
import logging

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Product, Warehouse
from app.services import commands

logger: logging.Logger = logging.getLogger("checkstock.seed")

SEED_LOCK_KEY: int = 7_310_001
PRODUCTS: dict[str, str] = {"SKU-101": "Органайзер", "SKU-102": "Контейнер", "SKU-103": "Корзина"}
WAREHOUSES: tuple[str, ...] = ("Север", "Юг")
INITIAL_STOCK: dict[str, dict[str, int]] = {
    "SKU-101": {"Север": 10, "Юг": 6},
    "SKU-102": {"Север": 5, "Юг": 0},
    "SKU-103": {"Север": 0, "Юг": 4},
}


def seed(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Product)):
        return False

    products: dict[str, Product] = {sku: Product(sku=sku, name=name) for sku, name in PRODUCTS.items()}
    db.add_all(products.values())
    db.commit()

    warehouses: dict[str, Warehouse] = {name: commands.create_warehouse(db, name) for name in WAREHOUSES}
    for sku, per_warehouse in INITIAL_STOCK.items():
        for warehouse_name, qty in per_warehouse.items():
            if qty > 0:
                commands.create_receipt(db, products[sku].id, warehouses[warehouse_name].id, qty)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": SEED_LOCK_KEY})
        connection.commit()
        try:
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as db:
                seeded: bool = seed(db)
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SEED_LOCK_KEY})
            connection.commit()
    logger.info("seed data %s", "created" if seeded else "already present, skipped")


if __name__ == "__main__":
    main()
