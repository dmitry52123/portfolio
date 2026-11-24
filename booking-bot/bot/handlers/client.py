"""Сценарий клиента: запись, мои записи, отмена, контакты."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.config import SERVICES_BY_CODE, Settings
from bot.db import Database
from bot.services import booking_days, fmt_day, fmt_dt, free_slots, normalize_phone, valid_name

router = Router(name="client")
log = logging.getLogger(__name__)


class Booking(StatesGroup):
    service = State()
    day = State()
    slot = State()
    name = State()
    phone = State()
    confirm = State()


def now_in(settings: Settings) -> datetime:
    return datetime.now(settings.tz)


async def _slots_for(day: date, minutes: int, db: Database, settings: Settings) -> list[datetime]:
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=settings.tz)
    busy = await db.busy_intervals(day_start, day_start + timedelta(days=1))
    return free_slots(
        day,
        minutes,
        busy,
        now_in(settings),
        settings.tz,
        settings.open_time,
        settings.close_time,
        settings.slot_step_min,
        settings.min_lead_min,
    )


async def _edit(cq: CallbackQuery, text: str, **kwargs: object) -> None:
    """Редактирует сообщение с кнопками; если оно недоступно — отправляет новое."""
    if isinstance(cq.message, Message):
        await cq.message.edit_text(text, **kwargs)  # type: ignore[arg-type]
    elif cq.from_user and cq.bot:
        await cq.bot.send_message(cq.from_user.id, text, **kwargs)  # type: ignore[arg-type]


# ---------- старт и меню ----------
@router.message(CommandStart())
async def start(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    name = escape(message.from_user.first_name) if message.from_user else "друг"
    await message.answer(
        f"Здравствуйте, {name}! 👋\nЭто бот записи в <b>{escape(settings.salon_name)}</b>.\nВыберите, что сделать:",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("cancel"))
@router.message(F.text == kb.BTN_CANCEL_FLOW)
async def abort_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Запись отменена. Чем ещё помочь?", reply_markup=kb.main_menu())


@router.message(F.text == kb.BTN_CONTACTS)
async def contacts(message: Message, settings: Settings) -> None:
    await message.answer(
        f"<b>{escape(settings.salon_name)}</b>\n📍 {escape(settings.address)}\n☎️ {escape(settings.phone)}\n"
        f"🕙 Ежедневно {settings.open_time:%H:%M}–{settings.close_time:%H:%M}"
    )


# ---------- запись: услуга → день → время → имя → телефон → подтверждение ----------
@router.message(F.text == kb.BTN_BOOK)
async def choose_service(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Booking.service)
    await message.answer("Выберите услугу:", reply_markup=kb.services_kb())


@router.callback_query(kb.NavCb.filter(F.to == "abort"))
async def nav_abort(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(cq, "Запись отменена.")
    await cq.answer()


@router.callback_query(kb.NavCb.filter(F.to == "services"))
async def nav_services(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Booking.service)
    await _edit(cq, "Выберите услугу:", reply_markup=kb.services_kb())
    await cq.answer()


async def _show_days(cq: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    service = SERVICES_BY_CODE.get(str(data.get("service", "")))
    if service is None:
        await nav_services(cq, state)
        return
    await state.set_state(Booking.day)
    days = booking_days(now_in(settings).date(), settings.days_ahead)
    await _edit(
        cq,
        f"<b>{escape(service.title)}</b> · {service.minutes} мин · {service.price} ₽\nВыберите день:",
        reply_markup=kb.days_kb(days),
    )


@router.callback_query(kb.ServiceCb.filter())
async def service_chosen(cq: CallbackQuery, callback_data: kb.ServiceCb, state: FSMContext, settings: Settings) -> None:
    if callback_data.code not in SERVICES_BY_CODE:
        await cq.answer("Такой услуги нет", show_alert=True)
        return
    await state.update_data(service=callback_data.code)
    await _show_days(cq, state, settings)
    await cq.answer()


@router.callback_query(kb.NavCb.filter(F.to == "days"))
async def nav_days(cq: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await _show_days(cq, state, settings)
    await cq.answer()


@router.callback_query(kb.DayCb.filter())
async def day_chosen(
    cq: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    data = await state.get_data()
    service = SERVICES_BY_CODE.get(str(data.get("service", "")))
    try:
        day = date.fromisoformat(callback_data.iso)
    except ValueError:
        day = None
    allowed = booking_days(now_in(settings).date(), settings.days_ahead)
    if service is None or day not in allowed:
        await cq.answer("Выбор устарел, начните заново", show_alert=True)
        await nav_services(cq, state)
        return
    slots = await _slots_for(day, service.minutes, db, settings)
    if not slots:
        await cq.answer("На этот день свободного времени нет", show_alert=True)
        return
    await state.update_data(day=day.isoformat())
    await state.set_state(Booking.slot)
    await _edit(cq, f"<b>{escape(service.title)}</b>, {fmt_day(day)}\nВыберите время:", reply_markup=kb.slots_kb(slots))
    await cq.answer()


@router.callback_query(kb.SlotCb.filter())
async def slot_chosen(
    cq: CallbackQuery, callback_data: kb.SlotCb, state: FSMContext, db: Database, settings: Settings
) -> None:
    data = await state.get_data()
    service = SERVICES_BY_CODE.get(str(data.get("service", "")))
    start = datetime.fromtimestamp(callback_data.ts, settings.tz)
    if service is None or start not in await _slots_for(start.date(), service.minutes, db, settings):
        await cq.answer("Это время уже недоступно, выберите другое", show_alert=True)
        return
    await state.update_data(start_ts=callback_data.ts)
    await state.set_state(Booking.name)
    await _edit(cq, f"<b>{escape(service.title)}</b>\n🗓 {fmt_dt(start)}")
    if cq.from_user and cq.bot:
        await cq.bot.send_message(cq.from_user.id, "Как вас зовут?", reply_markup=kb.cancel_only())
    await cq.answer()


@router.message(Booking.name, F.text)
async def name_entered(message: Message, state: FSMContext) -> None:
    name = valid_name(message.text or "")
    if name is None:
        await message.answer("Напишите имя буквами, от 2 до 40 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await message.answer(
        "Ваш номер телефона? Нажмите кнопку ниже или напишите номер.", reply_markup=kb.contact_request()
    )


@router.message(Booking.phone, F.contact | F.text)
async def phone_entered(message: Message, state: FSMContext, settings: Settings) -> None:
    raw = message.contact.phone_number if message.contact else (message.text or "")
    if message.contact and message.from_user and message.contact.user_id not in (None, message.from_user.id):
        await message.answer("Отправьте, пожалуйста, свой номер.")
        return
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer("Не похоже на мобильный номер. Пример: +7 900 123-45-67")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    service = SERVICES_BY_CODE[str(data["service"])]
    start = datetime.fromtimestamp(int(data["start_ts"]), settings.tz)
    await state.set_state(Booking.confirm)
    await message.answer("Проверьте запись:", reply_markup=kb.main_menu())
    await message.answer(
        f"💈 <b>{escape(service.title)}</b> — {service.price} ₽\n🗓 {fmt_dt(start)}\n"
        f"👤 {escape(str(data['name']))}\n📱 {phone}",
        reply_markup=kb.confirm_kb(),
    )


@router.callback_query(Booking.confirm, kb.ConfirmCb.filter())
async def confirmed(
    cq: CallbackQuery, callback_data: kb.ConfirmCb, state: FSMContext, db: Database, settings: Settings, bot: Bot
) -> None:
    if not callback_data.yes:
        await state.clear()
        await _edit(cq, "Запись отменена.")
        await cq.answer()
        return
    data = await state.get_data()
    service = SERVICES_BY_CODE[str(data["service"])]
    start = datetime.fromtimestamp(int(data["start_ts"]), settings.tz)
    end = start + timedelta(minutes=service.minutes)
    user_id = cq.from_user.id
    if start < now_in(settings) + timedelta(minutes=settings.min_lead_min):
        await state.clear()
        await _edit(cq, "Это время уже прошло. Нажмите «Записаться», чтобы выбрать другое.")
        await cq.answer()
        return
    booking_id = await db.create_booking(
        user_id, str(data["name"]), str(data["phone"]), service.code, start, end, now_in(settings)
    )
    if booking_id is None:
        await state.clear()
        await _edit(cq, "😔 Это время только что заняли. Нажмите «Записаться» и выберите другое.")
        await cq.answer()
        return
    await state.clear()
    await _edit(
        cq,
        f"✅ Вы записаны!\n💈 <b>{escape(service.title)}</b>\n🗓 {fmt_dt(start)}\n"
        f"📍 {escape(settings.address)}\nНапомним за {settings.remind_before_min // 60} ч до визита.",
        reply_markup=kb.cancel_booking_kb(booking_id),
    )
    await cq.answer("Готово!")
    text = (
        f"🆕 Новая запись №{booking_id}\n💈 {escape(service.title)}\n🗓 {fmt_dt(start)}\n"
        f"👤 {escape(str(data['name']))}, {data['phone']}"
    )
    for admin in settings.admin_ids:
        try:
            await bot.send_message(admin, text, reply_markup=kb.admin_cancel_kb(booking_id))
        except Exception:  # администратор мог не запустить бота — запись от этого не должна ломаться
            log.warning("Не удалось уведомить администратора %s", admin)


# ---------- мои записи и отмена ----------
@router.message(F.text == kb.BTN_MY)
async def my_bookings(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    items = await db.user_upcoming(message.from_user.id, now_in(settings))
    if not items:
        await message.answer("У вас нет предстоящих записей.", reply_markup=kb.main_menu())
        return
    for b in items:
        service = SERVICES_BY_CODE.get(b.service_code)
        title = service.title if service else b.service_code
        await message.answer(f"💈 <b>{escape(title)}</b>\n🗓 {fmt_dt(b.start)}", reply_markup=kb.cancel_booking_kb(b.id))


@router.callback_query(kb.CancelBookingCb.filter())
async def cancel_booking(
    cq: CallbackQuery, callback_data: kb.CancelBookingCb, db: Database, settings: Settings, bot: Bot
) -> None:
    booking = await db.get(callback_data.id)
    if booking is None or booking.user_id != cq.from_user.id or not await db.cancel(booking.id, cq.from_user.id):
        await cq.answer("Эту запись нельзя отменить", show_alert=True)
        return
    await _edit(cq, f"Запись на {fmt_dt(booking.start)} отменена.")
    await cq.answer("Отменено")
    for admin in settings.admin_ids:
        try:
            await bot.send_message(
                admin,
                f"❌ Клиент отменил запись №{booking.id} на {fmt_dt(booking.start)} "
                f"({escape(booking.client_name)}, {booking.phone})",
            )
        except Exception:
            log.warning("Не удалось уведомить администратора %s", admin)


@router.message(Booking.name)
@router.message(Booking.phone)
async def wrong_input(message: Message) -> None:
    await message.answer("Пожалуйста, ответьте текстом или нажмите кнопку.")
