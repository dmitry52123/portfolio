"""Выгрузка в Excel: лист «Товары» и лист «Изменения»."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from monitor.parse import Product
from monitor.storage import Change

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
KIND_RU = {"new": "Новый товар", "price": "Цена изменилась", "stock_out": "Закончился", "stock_in": "Снова в наличии"}


def _header(ws: Worksheet, titles: Sequence[str], widths: Sequence[int]) -> None:
    ws.append(list(titles))
    for i, w in enumerate(widths, start=1):
        cell = ws.cell(row=1, column=i)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def export_excel(path: str | Path, products: Sequence[Product], changes: Sequence[Change]) -> Path:
    wb = Workbook()
    ws = wb.active if wb.active is not None else wb.create_sheet()
    ws.title = "Товары"
    _header(ws, ["Название", "Цена", "Валюта", "В наличии", "Рейтинг", "Ссылка"], [60, 10, 8, 11, 9, 70])
    for p in products:
        ws.append([p.title, float(p.price), p.currency, "да" if p.in_stock else "нет", p.rating, p.url])
        ws.cell(row=ws.max_row, column=2).number_format = "0.00"
        ws.cell(row=ws.max_row, column=6).hyperlink = p.url
    ws.auto_filter.ref = f"A1:F{max(ws.max_row, 1)}"

    ch = wb.create_sheet("Изменения")
    _header(ch, ["Что случилось", "Название", "Было", "Стало", "Изменение, %", "Ссылка"], [18, 60, 10, 10, 14, 70])
    for c in changes:
        ch.append(
            [
                KIND_RU.get(c.kind, c.kind),
                c.product.title,
                float(c.old_price) if c.old_price is not None else None,
                float(c.product.price),
                float(c.percent) if c.percent is not None else None,
                c.product.url,
            ]
        )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
