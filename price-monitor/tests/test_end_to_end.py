"""Два запуска подряд на «сайте», где между ними меняются цены и наличие."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from openpyxl import load_workbook

import monitor.cli as cli
from monitor.fetch import Fetcher
from monitor.storage import Storage
from tests.conftest import BASE, fixture_html, site_transport

PAGE1, PAGE2 = BASE + "page-1.html", BASE + "page-2.html"


def site(page1: str) -> dict[str, str]:
    # вторая страница — последняя страница каталога (без ссылки «next»)
    return {PAGE1: page1, PAGE2: fixture_html("catalogue_page50.html")}


def test_two_runs_detect_price_drop_and_notify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []

    def fake_send(token: str, chat: str, msgs: list[str]) -> int:
        sent.append(list(msgs))
        return len(msgs)

    monkeypatch.setattr(cli, "send_telegram", fake_send)
    storage = Storage(str(tmp_path / "p.db"))
    excel = str(tmp_path / "prices.xlsx")
    original = fixture_html("catalogue_page1.html")

    f1 = Fetcher(client=httpx.Client(transport=site_transport(site(original))), delay_sec=0, sleep=lambda _s: None)
    r1 = cli.run_once(f1, storage, PAGE1, 5, excel, tg_token="T", tg_chat="1")
    assert r1.first_run and r1.products == 40 and r1.changes == [] and sent == []  # стартовый снимок без спама

    cheaper = original.replace("£51.77", "£45.00", 1)  # «A Light in the Attic» подешевела
    f2 = Fetcher(client=httpx.Client(transport=site_transport(site(cheaper))), delay_sec=0, sleep=lambda _s: None)
    r2 = cli.run_once(f2, storage, PAGE1, 5, excel, tg_token="T", tg_chat="1")
    assert not r2.first_run
    assert [(c.kind, c.product.title, c.old_price, c.product.price) for c in r2.changes] == [
        ("price", "A Light in the Attic", Decimal("51.77"), Decimal("45.00"))
    ]
    assert len(sent) == 1 and "A Light in the Attic" in sent[0][0] and "£51.77 → <b>£45.00</b>" in sent[0][0]

    wb = load_workbook(excel)
    assert wb["Товары"].max_row == 41  # заголовок + 40 товаров
    assert wb["Изменения"]["B2"].value == "A Light in the Attic"
    storage.close()


def test_without_telegram_settings_nothing_is_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    def fake_send(*args: object) -> int:
        called.append(args)
        return 0

    monkeypatch.setattr(cli, "send_telegram", fake_send)
    storage = Storage(str(tmp_path / "p.db"))
    pages = site(fixture_html("catalogue_page1.html"))
    for page1 in (pages[PAGE1], pages[PAGE1].replace("£51.77", "£40.00", 1)):
        f = Fetcher(client=httpx.Client(transport=site_transport(site(page1))), delay_sec=0, sleep=lambda _s: None)
        cli.run_once(f, storage, PAGE1, 5, str(tmp_path / "x.xlsx"))
    assert called == []
    storage.close()


def test_empty_site_is_an_error(tmp_path: Path) -> None:
    f = Fetcher(client=httpx.Client(transport=site_transport({})), retries=1, delay_sec=0, sleep=lambda _s: None)
    with pytest.raises(httpx.HTTPStatusError):
        cli.run_once(f, Storage(str(tmp_path / "p.db")), PAGE1, 5, str(tmp_path / "x.xlsx"))
