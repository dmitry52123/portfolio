"""Фоновая задача: напоминание клиенту перед визитом."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape

from aiogram import Bot

from bot.config import SERVICES_BY_CODE, Settings
from bot.db import Database
from bot.services import fmt_dt

log = logging.getLogger(__name__)


async def send_due_reminders(bot: Bot, db: Database, settings: Settings, now: datetime | None = None) -> int:
    """Отправляет все назревшие напоминания. Возвращает, сколько отправлено."""
    now = now or datetime.now(settings.tz)
    sent = 0
    for b in await db.due_reminders(now, settings.remind_before_min):
        service = SERVICES_BY_CODE.get(b.service_code)
        title = service.title if service else b.service_code
        try:
            await bot.send_message(
                b.user_id,
                f"⏰ Напоминаем: сегодня в <b>{b.start:%H:%M}</b> вас ждут — "
                f"{escape(title)}.\n📍 {escape(settings.address)}\n"
                f"Если планы изменились, отмените запись в «🗂 Мои записи».",
            )
            sent += 1
        except Exception:
            log.warning("Не удалось отправить напоминание по записи %s на %s", b.id, fmt_dt(b.start))
        # помечаем в любом случае, чтобы не слать повторно каждую минуту
        await db.mark_reminded(b.id)
    return sent


async def reminder_loop(bot: Bot, db: Database, settings: Settings, interval_sec: int = 60) -> None:
    while True:
        try:
            await send_due_reminders(bot, db, settings)
        except Exception:
            log.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(interval_sec)
