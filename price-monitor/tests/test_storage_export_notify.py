from decimal import Decimal
from pathlib import Path

import httpx
from openpyxl import load_workbook

from monitor.export import export_excel
from monitor.notify import TELEGRAM_LIMIT, build_messages, format_change, send_telegram
from monitor.parse import Product
from monitor.storage import Change, Storage


def prod(n: int, price: str, in_stock: bool = True, title: str | None = None) -> Product:
    return Product(f"https://shop/{n}", title or f"Книга {n}", Decimal(price), "£", in_stock, 4)


def test_storage_detects_all_kinds_of_changes(tmp_path: Path) -> None:
    s = Storage(str(tmp_path / "p.db"))
    assert s.is_empty()
    first = s.update([prod(1, "10.00"), prod(2, "20.00"), prod(3, "30.00", in_stock=False)])
    assert {c.kind for c in first} == {"new"} and len(first) == 3
    assert s.update([prod(1, "10.00"), prod(2, "20.00"), prod(3, "30.00", in_stock=False)]) == []

    changes = s.update([prod(1, "8.00"), prod(2, "20.00", in_stock=False), prod(3, "30.00"), prod(4, "5.00")])
    kinds = {(c.kind, c.product.url) for c in changes}
    assert kinds == {
        ("price", "https://shop/1"),
        ("stock_out", "https://shop/2"),
        ("stock_in", "https://shop/3"),
        ("new", "https://shop/4"),
    }
    drop = next(c for c in changes if c.kind == "price")
    assert drop.old_price == Decimal("10.00") and drop.percent == Decimal("-20.0")
    assert [p for _, p in s.history("https://shop/1")] == [Decimal("10.00"), Decimal("10.00"), Decimal("8.00")]
    s.close()


def test_min_change_filters_noise(tmp_path: Path) -> None:
    s = Storage(str(tmp_path / "p.db"))
    s.update([prod(1, "100.00")])
    assert s.update([prod(1, "100.50")], min_change_pct=Decimal(1)) == []  # 0.5% — шум
    assert len(s.update([prod(1, "98.00")], min_change_pct=Decimal(1))) == 1  # 2.5% от 100.50
    s.close()


def test_excel_contents(tmp_path: Path) -> None:
    products = [prod(1, "8.00"), prod(2, "20.00", in_stock=False)]
    changes = [Change("price", products[0], Decimal("10.00"))]
    path = export_excel(tmp_path / "out" / "prices.xlsx", products, changes)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Товары", "Изменения"]
    ws = wb["Товары"]
    assert [c.value for c in ws[1]] == ["Название", "Цена", "Валюта", "В наличии", "Рейтинг", "Ссылка"]
    assert ws["A2"].value == "Книга 1" and ws["B2"].value == 8.0 and ws["D3"].value == "нет"
    assert ws["F2"].hyperlink is not None and ws["F2"].hyperlink.target == "https://shop/1"
    ch = wb["Изменения"]
    assert [c.value for c in ch[2]][:5] == ["Цена изменилась", "Книга 1", 10.0, 8.0, -20.0]


def test_format_escapes_html_and_shows_direction() -> None:
    evil = prod(1, "8.00", title='<script>alert("x")</script>')
    text = format_change(Change("price", evil, Decimal("10.00")))
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert text.startswith("📉") and "(-20.0%)" in text
    up = format_change(Change("price", prod(2, "12.00"), Decimal("10.00")))
    assert up.startswith("📈") and "(+20.0%)" in up


def test_messages_split_under_telegram_limit() -> None:
    changes = [Change("price", prod(i, "9.00", title="Очень длинное название " * 5), Decimal("10")) for i in range(200)]
    messages = build_messages(changes)
    assert len(messages) > 1
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    assert sum(m.count("📉") for m in messages) == 200  # ничего не потерялось
    assert build_messages([]) == []


def test_send_telegram_counts_success_and_survives_errors() -> None:
    seen: list[httpx.Request] = []
    replies = iter([httpx.Response(200, json={"ok": True}), httpx.Response(400, json={"ok": False})])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(replies)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert send_telegram("TOKEN", "42", ["a", "b"], client=client) == 1
    assert seen[0].url.path == "/botTOKEN/sendMessage"
    assert b'"chat_id":"42"' in seen[0].content and b'"parse_mode":"HTML"' in seen[0].content
