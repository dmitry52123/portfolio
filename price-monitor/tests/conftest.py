from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://books.toscrape.com/catalogue/"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def site_transport(pages: dict[str, str], log: list[str] | None = None) -> httpx.MockTransport:
    """Имитация сайта: отдаёт HTML по URL байтами в UTF-8 и, как настоящий сайт, без charset в заголовке."""

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(str(request.url))
        body = pages.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


@pytest.fixture
def no_sleep() -> Callable[[float], None]:
    return lambda _s: None
