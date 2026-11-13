# -*- coding: utf-8 -*-
import os
from dataclasses import dataclass

MIN_PASSWORD_LENGTH: int = 12


@dataclass(frozen=True)
class Settings:
    auth_username: str
    auth_password: str
    allowed_hosts: tuple[str, ...]
    max_body_bytes: int


def _require(name: str) -> str:
    value: str = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"environment variable {name} is required")
    return value


def load_settings() -> Settings:
    password: str = _require("CHECKSTOCK_PASSWORD")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"CHECKSTOCK_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
    hosts: tuple[str, ...] = tuple(
        h.strip() for h in os.getenv("CHECKSTOCK_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
    )
    return Settings(
        auth_username=_require("CHECKSTOCK_USERNAME"),
        auth_password=password,
        allowed_hosts=hosts,
        max_body_bytes=int(os.getenv("CHECKSTOCK_MAX_BODY_BYTES", "65536")),
    )
