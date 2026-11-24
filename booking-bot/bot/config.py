"""Настройки бота: читаются из переменных окружения или файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Service:
    code: str
    title: str
    minutes: int
    price: int


SERVICES: tuple[Service, ...] = (
    Service("haircut", "Мужская стрижка", 60, 1500),
    Service("beard", "Оформление бороды", 30, 800),
    Service("combo", "Стрижка + борода", 90, 2000),
    Service("kids", "Детская стрижка", 45, 1000),
)
SERVICES_BY_CODE: dict[str, Service] = {s.code: s for s in SERVICES}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    db_path: str = "bookings.db"
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Moscow"))
    open_time: time = time(10, 0)
    close_time: time = time(21, 0)
    slot_step_min: int = 30
    days_ahead: int = 7
    min_lead_min: int = 60
    remind_before_min: int = 120
    salon_name: str = "Барбершоп «Бритва»"
    address: str = "ул. Примерная, 1"
    phone: str = "+7 900 000-00-00"


def _read_env_file(path: Path) -> dict[str, str]:
    """Минимальный разбор .env: строки KEY=VALUE, комментарии с #."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_time(value: str) -> time:
    hours, _, minutes = value.partition(":")
    return time(int(hours), int(minutes or 0))


def load_settings(env_file: str | os.PathLike[str] = ".env") -> Settings:
    env = {**_read_env_file(Path(env_file)), **os.environ}
    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN: укажите его в .env или переменных окружения")
    admin_ids = frozenset(int(x) for x in env.get("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    defaults = Settings(bot_token=token)
    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=env.get("DB_PATH", defaults.db_path),
        tz=ZoneInfo(env.get("TIMEZONE", "Europe/Moscow")),
        open_time=_parse_time(env["OPEN_TIME"]) if "OPEN_TIME" in env else defaults.open_time,
        close_time=_parse_time(env["CLOSE_TIME"]) if "CLOSE_TIME" in env else defaults.close_time,
        salon_name=env.get("SALON_NAME", defaults.salon_name),
        address=env.get("SALON_ADDRESS", defaults.address),
        phone=env.get("SALON_PHONE", defaults.phone),
    )
