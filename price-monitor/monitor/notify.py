"""Уведомления об изменениях в Telegram."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from html import escape

import httpx

from monitor.storage import Change

log = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4096


def format_change(c: Change) -> str:
    p = c.product
    title = f'<a href="{escape(p.url, quote=True)}">{escape(p.title)}</a>'
    price = f"{p.currency}{p.price}"
    if c.kind == "price" and c.old_price is not None:
        arrow = "📉" if p.price < c.old_price else "📈"
        sign = "+" if c.percent is not None and c.percent > 0 else ""
        return f"{arrow} {title}: {p.currency}{c.old_price} → <b>{price}</b> ({sign}{c.percent}%)"
    if c.kind == "stock_out":
        return f"❌ Закончился: {title} ({price})"
    if c.kind == "stock_in":
        return f"✅ Снова в наличии: {title} — <b>{price}</b>"
    return f"🆕 Новый товар: {title} — <b>{price}</b>"


def build_messages(changes: Sequence[Change], header: str = "Изменения цен") -> list[str]:
    """Собирает сообщения, каждое не длиннее лимита Telegram. Строки не разрезаются посередине."""
    if not changes:
        return []
    order = {"price": 0, "stock_out": 1, "stock_in": 2, "new": 3}
    lines = [format_change(c) for c in sorted(changes, key=lambda c: order.get(c.kind, 9))]
    messages: list[str] = []
    current = f"<b>{escape(header)}</b> ({len(changes)})"
    for line in lines:
        if len(current) + 1 + len(line) > TELEGRAM_LIMIT:
            messages.append(current)
            current = line
        else:
            current += "\n" + line
    messages.append(current)
    return messages


def send_telegram(token: str, chat_id: str, messages: Sequence[str], client: httpx.Client | None = None) -> int:
    """Отправляет сообщения. Возвращает число успешно отправленных; ошибки пишет в лог, а не роняет мониторинг."""
    own = client is None
    http = client or httpx.Client(timeout=15)
    sent = 0
    try:
        for text in messages:
            try:
                resp = http.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    sent += 1
                else:
                    log.error("Telegram ответил %s: %s", resp.status_code, resp.text[:200])
            except httpx.HTTPError as exc:
                log.error("Не удалось отправить сообщение в Telegram: %s", exc)
    finally:
        if own:
            http.close()
    return sent
