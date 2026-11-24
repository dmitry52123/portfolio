"""Запуск: python -m monitor.cli [--pages N] [--every MINUTES]"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from monitor.export import export_excel
from monitor.fetch import Fetcher
from monitor.notify import build_messages, send_telegram
from monitor.storage import Change, Storage

log = logging.getLogger("monitor")


@dataclass
class RunResult:
    products: int
    changes: list[Change]
    first_run: bool
    excel: Path
    sent: int


def load_env(path: str = ".env") -> None:
    """Подхватывает KEY=VALUE из .env, не перезаписывая уже заданные переменные."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run_once(
    fetcher: Fetcher,
    storage: Storage,
    start_url: str,
    max_pages: int,
    excel_path: str,
    min_change_pct: Decimal = Decimal(0),
    tg_token: str | None = None,
    tg_chat: str | None = None,
) -> RunResult:
    first_run = storage.is_empty()
    products = list(fetcher.crawl(start_url, max_pages))
    if not products:
        raise RuntimeError("Не найдено ни одного товара — проверьте адрес и вёрстку сайта")
    changes = storage.update(products, min_change_pct=min_change_pct)
    # В первый раз все товары «новые» — это не новость, а стартовый снимок
    notify = [] if first_run else changes
    excel = export_excel(excel_path, storage.all_products(), notify)
    sent = 0
    if notify and tg_token and tg_chat:
        sent = send_telegram(tg_token, tg_chat, build_messages(notify))
    log.info("Товаров: %s, изменений: %s, отправлено сообщений: %s", len(products), len(notify), sent)
    return RunResult(len(products), notify, first_run, excel, sent)


def main(argv: list[str] | None = None) -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Мониторинг цен: парсинг каталога, Excel и уведомления в Telegram")
    parser.add_argument("--url", default=os.getenv("START_URL", "https://books.toscrape.com/catalogue/page-1.html"))
    parser.add_argument("--pages", type=int, default=int(os.getenv("MAX_PAGES", "50")))
    parser.add_argument("--db", default=os.getenv("DB_PATH", "prices.db"))
    parser.add_argument("--excel", default=os.getenv("EXCEL_PATH", "prices.xlsx"))
    parser.add_argument("--min-change", type=Decimal, default=Decimal(os.getenv("MIN_CHANGE_PCT", "0")))
    parser.add_argument("--every", type=int, default=0, help="повторять каждые N минут (0 — один раз)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    fetcher, storage = Fetcher(), Storage(args.db)
    try:
        while True:
            try:
                res = run_once(
                    fetcher,
                    storage,
                    args.url,
                    args.pages,
                    args.excel,
                    args.min_change,
                    os.getenv("TELEGRAM_BOT_TOKEN"),
                    os.getenv("TELEGRAM_CHAT_ID"),
                )
                note = " (первый запуск: сохранён стартовый снимок)" if res.first_run else ""
                print(f"Готово: {res.products} товаров, изменений {len(res.changes)}, файл {res.excel}{note}")
            except Exception:
                if not args.every:
                    raise
                log.exception("Запуск не удался, попробую в следующий раз")
            if not args.every:
                break
            time.sleep(args.every * 60)
    finally:
        fetcher.close()
        storage.close()


if __name__ == "__main__":
    main()
