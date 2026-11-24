from collections.abc import Callable

import httpx
import pytest

from monitor.fetch import Fetcher
from tests.conftest import BASE, fixture_html, site_transport


def make(transport: httpx.MockTransport, sleep: Callable[[float], None]) -> Fetcher:
    return Fetcher(client=httpx.Client(transport=transport), delay_sec=0, sleep=sleep)


def test_pound_sign_is_not_broken(no_sleep: Callable[[float], None]) -> None:
    """Сервер не присылает charset: проверяем, что «£» не превращается в «Â£» (классическая ошибка парсеров)."""
    f = make(site_transport({BASE + "page-1.html": fixture_html("catalogue_page1.html")}), no_sleep)
    products = list(f.crawl(BASE + "page-1.html", max_pages=1))
    assert products[0].currency == "£"


def test_crawl_follows_next_and_respects_limit(no_sleep: Callable[[float], None]) -> None:
    page1 = fixture_html("catalogue_page1.html")
    pages = {BASE + f"page-{i}.html": page1.replace("page-2.html", f"page-{i + 1}.html") for i in range(1, 6)}
    calls: list[str] = []
    f = make(site_transport(pages, calls), no_sleep)
    products = list(f.crawl(BASE + "page-1.html", max_pages=3))
    assert calls == [BASE + "page-1.html", BASE + "page-2.html", BASE + "page-3.html"]
    assert len(products) == 60


def test_crawl_stops_on_loop(no_sleep: Callable[[float], None]) -> None:
    looped = fixture_html("catalogue_page1.html").replace("page-2.html", "page-1.html")
    calls: list[str] = []
    f = make(site_transport({BASE + "page-1.html": looped}, calls), no_sleep)
    assert len(list(f.crawl(BASE + "page-1.html", max_pages=10))) == 20
    assert calls == [BASE + "page-1.html"]


def test_retries_temporary_errors_then_succeeds() -> None:
    answers = iter([httpx.Response(503), httpx.Response(429)])
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nxt = next(answers, None)
        return nxt or httpx.Response(200, content=b"<html>ok</html>")

    f = Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), retries=3, delay_sec=1, sleep=waits.append)
    assert f.get(BASE) == "<html>ok</html>"
    assert waits == [2, 4]  # экспоненциальная пауза между попытками


def test_404_fails_immediately_without_retries() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404)

    f = Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), retries=3, sleep=lambda _s: None)
    with pytest.raises(httpx.HTTPStatusError):
        f.get(BASE)
    assert len(calls) == 1


def test_gives_up_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    f = Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), retries=2, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="за 2 попыток"):
        f.get(BASE)
