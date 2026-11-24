"""Точка входа: python -m bot.main"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_settings
from bot.db import Database
from bot.handlers import admin, client
from bot.reminders import reminder_loop


def create_dispatcher() -> Dispatcher:
    """Собирает диспетчер: админские команды раньше клиентских. Используется и ботом, и тестами."""
    for r in (admin.router, client.router):
        r._parent_router = None  # позволяет пересобрать диспетчер (нужно тестам)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(client.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    db = Database(settings.db_path, settings.tz)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher()
    reminders = asyncio.create_task(reminder_loop(bot, db, settings))
    try:
        await dp.start_polling(bot, db=db, settings=settings)
    finally:
        reminders.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminders
        db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
