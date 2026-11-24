from decimal import Decimal

import pytest

from monitor.parse import ParseError, parse_catalogue, parse_price
from tests.conftest import BASE, fixture_html


def test_first_page_real_markup() -> None:
    products, next_url = parse_catalogue(fixture_html("catalogue_page1.html"), BASE + "page-1.html")
    assert len(products) == 20
    first = products[0]
    assert first.title == "A Light in the Attic"  # полное название из title, а не обрезанное «A Light in the ...»
    assert first.price == Decimal("51.77")
    assert first.currency == "£"
    assert first.rating == 3
    assert first.in_stock is True
    assert first.url == BASE + "a-light-in-the-attic_1000/index.html"
    assert next_url == BASE + "page-2.html"
    assert len({p.url for p in products}) == 20  # без дублей


def test_last_page_has_no_next() -> None:
    products, next_url = parse_catalogue(fixture_html("catalogue_page50.html"), BASE + "page-50.html")
    assert products and next_url is None


def test_all_prices_positive_and_ratings_known() -> None:
    products, _ = parse_catalogue(fixture_html("catalogue_page1.html"), BASE + "page-1.html")
    assert all(p.price > 0 for p in products)
    assert all(1 <= p.rating <= 5 for p in products)


@pytest.mark.parametrize(
    ("raw", "price", "currency"),
    [
        ("£51.77", Decimal("51.77"), "£"),
        ("1 299,50 ₽", Decimal("1299.50"), "₽"),
        ("$5", Decimal("5"), "$"),
        (" 10.00\xa0€ ", Decimal("10.00"), "€"),
    ],
)
def test_parse_price(raw: str, price: Decimal, currency: str) -> None:
    assert parse_price(raw) == (price, currency)


def test_parse_price_garbage() -> None:
    with pytest.raises(ParseError):
        parse_price("нет в наличии")


def test_not_a_catalogue_page() -> None:
    with pytest.raises(ParseError):
        parse_catalogue("<html><body><h1>Сайт на обслуживании</h1></body></html>", BASE)
