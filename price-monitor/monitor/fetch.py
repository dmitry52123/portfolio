"""Загрузка страниц: таймауты, повторы при временных сбоях, вежливая пауза между запросами."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator

import httpx

from monitor.parse import Product, parse_catalogue

log = logging.getLogger(__name__)
USER_AGENT = "price-monitor/1.0 (+https://github.com/dmitry52123/portfolio)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class Fetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        retries: int = 3,
        delay_sec: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15.0), headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self.retries = retries
        self.delay_sec = delay_sec
        self.sleep = sleep

    def get(self, url: str) -> str:
        """HTML страницы. Повторяет запрос при сетевой ошибке и кодах 429/5xx, на 4xx падает сразу."""
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.client.get(url)
                if resp.status_code in RETRY_STATUSES:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                # Сайт не указывает кодировку в заголовке: декодируем как UTF-8 явно.
                # (requests в такой ситуации выбирает latin-1, и «£» превращается в «Â£».)
                return resp.content.decode("utf-8")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in RETRY_STATUSES:
                    raise
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            wait = self.delay_sec * 2**attempt
            log.warning(
                "Попытка %s/%s для %s не удалась (%s), жду %.1f с", attempt, self.retries, url, last_error, wait
            )
            self.sleep(wait)
        raise RuntimeError(f"Не удалось загрузить {url} за {self.retries} попыток") from last_error

    def crawl(self, start_url: str, max_pages: int) -> Iterator[Product]:
        """Обходит страницы каталога по ссылке «next», не больше max_pages."""
        url: str | None = start_url
        seen: set[str] = set()
        pages = 0
        while url and pages < max_pages and url not in seen:
            seen.add(url)
            products, url = parse_catalogue(self.get(url), url)
            pages += 1
            log.info("Страница %s: %s товаров", pages, len(products))
            yield from products
            if url and pages < max_pages:
                self.sleep(self.delay_sec)

    def close(self) -> None:
        self.client.close()
