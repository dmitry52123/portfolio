"""Клавиатуры и данные кнопок."""

from __future__ import annotations

from datetime import date, datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.config import SERVICES
from bot.services import fmt_day_short

BTN_BOOK = "📅 Записаться"
BTN_MY = "🗂 Мои записи"
BTN_CONTACTS = "📍 Контакты"
BTN_CANCEL_FLOW = "✖️ Отменить"


class ServiceCb(CallbackData, prefix="svc"):
    code: str


class DayCb(CallbackData, prefix="day"):
    iso: str


class SlotCb(CallbackData, prefix="slot"):
    ts: int


class NavCb(CallbackData, prefix="nav"):
    to: str  # services | days | abort


class ConfirmCb(CallbackData, prefix="ok"):
    yes: bool


class CancelBookingCb(CallbackData, prefix="cxl"):
    id: int


class AdminCancelCb(CallbackData, prefix="acx"):
    id: int


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=BTN_BOOK)
    kb.button(text=BTN_MY)
    kb.button(text=BTN_CONTACTS)
    kb.adjust(1, 2)
    return kb.as_markup(resize_keyboard=True)


def cancel_only() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL_FLOW)]], resize_keyboard=True)


def contact_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
            [KeyboardButton(text=BTN_CANCEL_FLOW)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def services_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in SERVICES:
        kb.button(text=f"{s.title} · {s.minutes} мин · {s.price} ₽", callback_data=ServiceCb(code=s.code))
    kb.button(text="✖️ Отменить", callback_data=NavCb(to="abort"))
    kb.adjust(1)
    return kb.as_markup()


def days_kb(days: list[date]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in days:
        kb.button(text=fmt_day_short(d), callback_data=DayCb(iso=d.isoformat()))
    kb.button(text="← К услугам", callback_data=NavCb(to="services"))
    kb.adjust(*([3] * ((len(days) + 2) // 3)), 1)
    return kb.as_markup()


def slots_kb(slots: list[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        kb.button(text=f"{s:%H:%M}", callback_data=SlotCb(ts=int(s.timestamp())))
    kb.button(text="← К дням", callback_data=NavCb(to="days"))
    kb.adjust(*([4] * ((len(slots) + 3) // 4)), 1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=ConfirmCb(yes=True))
    kb.button(text="✖️ Отменить", callback_data=ConfirmCb(yes=False))
    kb.adjust(2)
    return kb.as_markup()


def cancel_booking_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Отменить эту запись", callback_data=CancelBookingCb(id=booking_id))
    return kb.as_markup()


def admin_cancel_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✖️ Отменить №{booking_id}", callback_data=AdminCancelCb(id=booking_id))
    return kb.as_markup()
