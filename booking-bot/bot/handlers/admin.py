"""Панель администратора: расписание на неделю и отмена записей."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot.config import SERVICES_BY_CODE, Settings
from bot.db import Database
from bot.services import fmt_day, fmt_dt

router = Router(name="admin")
log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, settings: Settings, **_: Any) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in settings.admin_ids)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("admin"))
async def schedule(message: Message, db: Database, settings: Settings) -> None:
    now = datetime.now(settings.tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    items = await db.upcoming(start, start + timedelta(days=settings.days_ahead))
    if not items:
        await message.answer("На ближайшие дни записей нет.")
        return
    await message.answer(f"📋 Записи на {settings.days_ahead} дн.: {len(items)}")
    current_day = None
    for b in items:
        if b.start.date() != current_day:
            current_day = b.start.date()
            await message.answer(f"<b>{fmt_day(current_day)}</b>")
        service = SERVICES_BY_CODE.get(b.service_code)
        title = service.title if service else b.service_code
        mark = " ✔️ прошла" if b.end <= now else ""
        await message.answer(
            f"№{b.id} · {b.start:%H:%M}–{b.end:%H:%M} · {escape(title)}{mark}\n👤 {escape(b.client_name)}, {b.phone}",
            reply_markup=None if b.end <= now else kb.admin_cancel_kb(b.id),
        )


@router.callback_query(kb.AdminCancelCb.filter())
async def admin_cancel(cq: CallbackQuery, callback_data: kb.AdminCancelCb, db: Database, bot: Bot) -> None:
    booking = await db.get(callback_data.id)
    if booking is None or not await db.cancel(booking.id):
        await cq.answer("Запись уже отменена", show_alert=True)
        return
    if isinstance(cq.message, Message):
        await cq.message.edit_text(f"❌ Запись №{booking.id} на {fmt_dt(booking.start)} отменена администратором.")
    await cq.answer("Отменено")
    try:
        await bot.send_message(
            booking.user_id,
            f"К сожалению, ваша запись на {fmt_dt(booking.start)} отменена "
            "салоном. Выберите другое время: «📅 Записаться».",
        )
    except Exception:
        log.warning("Не удалось уведомить клиента %s об отмене", booking.user_id)
