"""Разбор страниц каталога: товары и ссылка на следующую страницу."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


@dataclass(frozen=True)
class Product:
    url: str
    title: str
    price: Decimal
    currency: str
    in_stock: bool
    rating: int


class ParseError(ValueError):
    """Страница не похожа на каталог: вёрстка сайта изменилась или пришла ошибка."""


def parse_price(text: str) -> tuple[Decimal, str]:
    """'£51.77' -> (Decimal('51.77'), '£'). Цена — Decimal, чтобы не было ошибок округления float."""
    raw = text.strip().replace("\xa0", "").replace(" ", "")
    digits = "".join(ch for ch in raw if ch.isdigit() or ch in ".,").replace(",", ".")
    currency = "".join(ch for ch in raw if not (ch.isdigit() or ch in ".,"))
    try:
        price = Decimal(digits)
    except InvalidOperation as exc:
        raise ParseError(f"Не удалось разобрать цену: {text!r}") from exc
    if price < 0:
        raise ParseError(f"Отрицательная цена: {text!r}")
    return price, currency


def _text(node: Tag | None) -> str:
    return node.get_text(strip=True) if node else ""


def parse_catalogue(html: str, page_url: str) -> tuple[list[Product], str | None]:
    """Возвращает товары со страницы и абсолютную ссылку на следующую страницу (или None)."""
    soup = BeautifulSoup(html, "lxml")
    pods = soup.select("article.product_pod")
    if not pods:
        raise ParseError(f"На странице {page_url} не найдено ни одного товара")
    products: list[Product] = []
    for pod in pods:
        link = pod.select_one("h3 a")
        price_node = pod.select_one("p.price_color")
        if link is None or price_node is None:
            raise ParseError(f"Карточка товара без ссылки или цены на {page_url}")
        title = str(link.get("title") or _text(link))
        price, currency = parse_price(_text(price_node))
        rating_node = pod.select_one("p.star-rating")
        raw_classes = rating_node.get("class") if rating_node else None
        # атрибут class обычно список, но может прийти и строкой
        classes = list(raw_classes) if isinstance(raw_classes, list) else str(raw_classes or "").split()
        rating = next((RATINGS[c] for c in classes if c in RATINGS), 0)
        availability = _text(pod.select_one("p.availability")).lower()
        products.append(
            Product(
                url=urljoin(page_url, str(link.get("href", ""))),
                title=title,
                price=price,
                currency=currency,
                in_stock="in stock" in availability,
                rating=rating,
            )
        )
    next_link = soup.select_one("li.next a")
    next_url = urljoin(page_url, str(next_link.get("href"))) if next_link and next_link.get("href") else None
    return products, next_url
