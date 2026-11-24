"""Сквозной тест: имитируем клиента в Telegram и перехватываем все запросы бота к API."""

from __future__ import annotations

import itertools
from collections.abc import AsyncGenerator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User

from bot import keyboards as kb
from bot.config import Settings
from bot.db import Database
from bot.main import create_dispatcher
from bot.reminders import send_due_reminders

TZ = ZoneInfo("Europe/Moscow")
CLIENT = User(id=111, is_bot=False, first_name="Иван")
OTHER = User(id=222, is_bot=False, first_name="Пётр")
ADMIN_ID = 999
_ids = itertools.count(1)


class FakeSession(BaseSession):
    """Ничего не отправляет в сеть: запоминает вызовы и возвращает правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText"):
            chat_id = getattr(method, "chat_id", None) or CLIENT.id
            return Message(
                message_id=next(_ids),
                date=datetime.now(TZ),
                chat=Chat(id=int(chat_id), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def close(self) -> None:
        pass

    async def stream_content(  # pragma: no cover - бот не скачивает файлы
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""

    def texts(self, chat_id: int | None = None) -> list[str]:
        return [
            str(getattr(c, "text", ""))
            for c in self.calls
            if hasattr(c, "text") and (chat_id is None or getattr(c, "chat_id", None) == chat_id)
        ]

    def last_markup(self) -> Any:
        for c in reversed(self.calls):
            markup = getattr(c, "reply_markup", None)
            if markup is not None:
                return markup
        return None


class Harness:
    def __init__(self, tmp_path: Any) -> None:
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.settings = Settings(
            bot_token="42:TEST", admin_ids=frozenset({ADMIN_ID}), tz=TZ, min_lead_min=0, days_ahead=7
        )
        self.db = Database(str(tmp_path / "flow.db"), TZ)
        self.dp = create_dispatcher()
        self.uid = itertools.count(1)

    async def send(self, user: User, text: str | None = None, contact: Contact | None = None) -> None:
        msg = Message(
            message_id=next(_ids),
            date=datetime.now(TZ),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
            contact=contact,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=next(self.uid), message=msg), db=self.db, settings=self.settings
        )

    async def press(self, user: User, data: str) -> None:
        msg = Message(
            message_id=next(_ids),
            date=datetime.now(TZ),
            chat=Chat(id=user.id, type="private"),
            from_user=User(id=1, is_bot=True, first_name="bot"),
            text="…",
        )
        cq = CallbackQuery(id=str(next(_ids)), from_user=user, chat_instance="x", message=msg, data=data)
        await self.dp.feed_update(
            self.bot, Update(update_id=next(self.uid), callback_query=cq), db=self.db, settings=self.settings
        )


def tomorrow() -> date:
    return datetime.now(TZ).date() + timedelta(days=1)


@pytest.fixture
async def h(tmp_path):  # type: ignore[no-untyped-def]
    harness = Harness(tmp_path)
    yield harness
    harness.db.close()
    await harness.bot.session.close()


async def book(h: Harness, user: User, hour: int, phone: str = "+7 900 123-45-67") -> None:
    await h.send(user, kb.BTN_BOOK)
    await h.press(user, kb.ServiceCb(code="haircut").pack())
    await h.press(user, kb.DayCb(iso=tomorrow().isoformat()).pack())
    start = datetime.combine(tomorrow(), time(hour), tzinfo=TZ)
    await h.press(user, kb.SlotCb(ts=int(start.timestamp())).pack())
    await h.send(user, user.first_name)
    await h.send(user, phone)
    await h.press(user, kb.ConfirmCb(yes=True).pack())


async def test_full_booking_flow(h: Harness) -> None:
    await h.send(CLIENT, "/start")
    assert "Здравствуйте, Иван" in h.session.texts(CLIENT.id)[-1]
    await book(h, CLIENT, 12)

    texts = h.session.texts()
    assert any("Вы записаны" in t for t in texts), texts[-5:]
    bookings = await h.db.user_upcoming(CLIENT.id, datetime.now(TZ))
    assert len(bookings) == 1
    b = bookings[0]
    assert b.start == datetime.combine(tomorrow(), time(12), tzinfo=TZ)
    assert b.end - b.start == timedelta(minutes=60)
    assert b.phone == "+79001234567" and b.client_name == "Иван"
    assert any("Новая запись" in t for t in h.session.texts(ADMIN_ID))


async def test_taken_slot_is_hidden_and_rejected(h: Harness) -> None:
    await book(h, CLIENT, 12)
    # второй клиент выбирает тот же день: 12:00 и пересекающееся 11:30 не должны предлагаться
    await h.send(OTHER, kb.BTN_BOOK)
    await h.press(OTHER, kb.ServiceCb(code="haircut").pack())
    await h.press(OTHER, kb.DayCb(iso=tomorrow().isoformat()).pack())
    labels = [b.text for row in h.session.last_markup().inline_keyboard for b in row]
    assert "12:00" not in labels and "11:30" not in labels and "13:00" in labels
    # «подделанное» нажатие на занятое время отклоняется
    start = datetime.combine(tomorrow(), time(12), tzinfo=TZ)
    await h.press(OTHER, kb.SlotCb(ts=int(start.timestamp())).pack())
    assert any(getattr(c, "text", "") == "Это время уже недоступно, выберите другое" for c in h.session.calls)
    assert await h.db.user_upcoming(OTHER.id, datetime.now(TZ)) == []


async def test_bad_phone_and_name_are_asked_again(h: Harness) -> None:
    await h.send(CLIENT, kb.BTN_BOOK)
    await h.press(CLIENT, kb.ServiceCb(code="beard").pack())
    await h.press(CLIENT, kb.DayCb(iso=tomorrow().isoformat()).pack())
    start = datetime.combine(tomorrow(), time(15), tzinfo=TZ)
    await h.press(CLIENT, kb.SlotCb(ts=int(start.timestamp())).pack())
    await h.send(CLIENT, "<script>")
    assert "буквами" in h.session.texts(CLIENT.id)[-1]
    await h.send(CLIENT, "Иван")
    await h.send(CLIENT, "12345")
    assert "мобильный" in h.session.texts(CLIENT.id)[-1]
    await h.send(CLIENT, contact=Contact(phone_number="79001112233", first_name="Иван", user_id=CLIENT.id))
    assert any("+79001112233" in t for t in h.session.texts(CLIENT.id))


async def test_client_cancels_and_admin_is_notified(h: Harness) -> None:
    await book(h, CLIENT, 16)
    b = (await h.db.user_upcoming(CLIENT.id, datetime.now(TZ)))[0]
    await h.press(OTHER, kb.CancelBookingCb(id=b.id).pack())  # чужой не может отменить
    assert len(await h.db.user_upcoming(CLIENT.id, datetime.now(TZ))) == 1
    await h.press(CLIENT, kb.CancelBookingCb(id=b.id).pack())
    assert await h.db.user_upcoming(CLIENT.id, datetime.now(TZ)) == []
    assert any("отменил запись" in t for t in h.session.texts(ADMIN_ID))


async def test_admin_panel_only_for_admin(h: Harness) -> None:
    await book(h, CLIENT, 17)
    before = len(h.session.calls)
    await h.send(CLIENT, "/admin")  # клиенту — никакой админки
    assert not any("Записи на" in t for t in h.session.texts()[before:])
    admin_user = User(id=ADMIN_ID, is_bot=False, first_name="Админ")
    await h.send(admin_user, "/admin")
    assert any("Записи на 7 дн.: 1" in t for t in h.session.texts(ADMIN_ID))
    b = (await h.db.user_upcoming(CLIENT.id, datetime.now(TZ)))[0]
    await h.press(admin_user, kb.AdminCancelCb(id=b.id).pack())
    assert await h.db.user_upcoming(CLIENT.id, datetime.now(TZ)) == []
    assert any("отменена салоном" in t for t in h.session.texts(CLIENT.id))


async def test_reminder_sent_once(h: Harness) -> None:
    await book(h, CLIENT, 18)
    b = (await h.db.user_upcoming(CLIENT.id, datetime.now(TZ)))[0]
    assert await send_due_reminders(h.bot, h.db, h.settings, now=b.start - timedelta(hours=3)) == 0
    assert await send_due_reminders(h.bot, h.db, h.settings, now=b.start - timedelta(hours=1)) == 1
    assert await send_due_reminders(h.bot, h.db, h.settings, now=b.start - timedelta(minutes=30)) == 0
    assert any("Напоминаем" in t for t in h.session.texts(CLIENT.id))
