from __future__ import annotations

import re
import time
from http.cookiejar import CookieJar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .marketplace import build_master_marketplace_url, build_release_marketplace_url
from .marketplace import build_marketplace_search_url
from .matching import split_artist_album_display, title_matches_artist_album
from .models import (
    ALLOWED_MEDIA_CONDITIONS,
    AlbumRequest,
    Offer,
    ReleaseCandidate,
    canonical_media_condition,
)


class MarketplaceScrapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScrapeResult:
    offers: list[Offer]
    warnings: list[str]


class MarketplacePageFetcher:
    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 DiscogsVinylOptimizer/0.1",
        timeout_seconds: int = 30,
        min_delay_seconds: float = 1.0,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.min_delay_seconds = min_delay_seconds
        self._last_request_at = 0.0
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def fetch_html(self, url: str) -> str:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_delay_seconds:
            time.sleep(self.min_delay_seconds - elapsed)
        self._last_request_at = time.monotonic()

        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as exc:
            raise MarketplaceScrapeError(_marketplace_http_error_message(exc.code, url)) from exc
        except URLError as exc:
            raise MarketplaceScrapeError(f"Discogs marketplace fetch failed: {exc.reason}: {url}") from exc

        html = body.decode("utf-8", errors="replace")
        if "Just a moment" in html or "__cf_chl" in html:
            raise MarketplaceScrapeError(f"Discogs returned a Cloudflare challenge instead of listings: {url}")
        return html


def _marketplace_http_error_message(status_code: int, url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    query = (params.get("q") or [""])[0]
    condition = (params.get("condition") or [""])[0]
    if query or condition:
        details = []
        if query:
            details.append(f"search '{query}'")
        if condition:
            details.append(f"condition '{condition}'")
        joined = ", ".join(details)
        return f"Skipped one optional Discogs marketplace page during scraping (HTTP {status_code}: {joined})."
    return f"Skipped one optional Discogs marketplace page during scraping (HTTP {status_code})."


def scrape_marketplace_offers(
    candidates: Iterable[ReleaseCandidate],
    pages_per_condition: int = 1,
    user_agent: str = "Mozilla/5.0 DiscogsVinylOptimizer/0.1",
) -> ScrapeResult:
    if pages_per_condition < 1:
        raise ValueError("pages_per_condition must be at least 1")

    fetcher = MarketplacePageFetcher(user_agent=user_agent)
    offers: list[Offer] = []
    warnings: list[str] = []
    seen_listing_ids: set[str] = set()

    for candidate in candidates:
        for condition in sorted(ALLOWED_MEDIA_CONDITIONS):
            for page in range(1, pages_per_condition + 1):
                url = _candidate_marketplace_url(candidate, condition=condition, page=page)
                try:
                    html = fetcher.fetch_html(url)
                except MarketplaceScrapeError as exc:
                    warnings.append(str(exc))
                    break

                page_offers = parse_marketplace_html(html, candidate)
                if not page_offers:
                    break
                for offer in page_offers:
                    dedupe_key = offer.listing_id or offer.listing_url
                    if dedupe_key in seen_listing_ids:
                        continue
                    seen_listing_ids.add(dedupe_key)
                    offers.append(offer)
    return ScrapeResult(offers=_sort_offers_lowest_total(offers), warnings=warnings)


def scrape_marketplace_search_offers(
    albums: Iterable[AlbumRequest],
    pages_per_condition: int = 1,
    user_agent: str = "Mozilla/5.0 DiscogsVinylOptimizer/0.1",
) -> ScrapeResult:
    if pages_per_condition < 1:
        raise ValueError("pages_per_condition must be at least 1")

    fetcher = MarketplacePageFetcher(user_agent=user_agent)
    offers: list[Offer] = []
    warnings: list[str] = []
    seen_listing_ids: set[str] = set()

    for album in albums:
        candidate = ReleaseCandidate(
            album_key=album.key,
            album_display=album.display,
            release_id=album.release_id or 0,
            title=album.display,
            country="",
            year="",
            format_summary="Vinyl",
            uri="",
            resource_url="",
        )
        for condition in sorted(ALLOWED_MEDIA_CONDITIONS):
            for page in range(1, pages_per_condition + 1):
                url = build_marketplace_search_url(album, condition=condition, page=page)
                try:
                    html = fetcher.fetch_html(url)
                except MarketplaceScrapeError as exc:
                    warnings.append(str(exc))
                    break

                page_offers = parse_marketplace_html(html, candidate)
                if not page_offers:
                    break
                for offer in page_offers:
                    dedupe_key = offer.listing_id or offer.listing_url
                    if dedupe_key in seen_listing_ids:
                        continue
                    seen_listing_ids.add(dedupe_key)
                    offers.append(offer)
    return ScrapeResult(offers=_sort_offers_lowest_total(offers), warnings=warnings)


def merge_scrape_results(*results: ScrapeResult) -> ScrapeResult:
    offers: list[Offer] = []
    warnings: list[str] = []
    seen_listing_ids: set[str] = set()
    for result in results:
        warnings.extend(result.warnings)
        for offer in result.offers:
            dedupe_key = offer.listing_id or offer.listing_url
            if dedupe_key in seen_listing_ids:
                continue
            seen_listing_ids.add(dedupe_key)
            offers.append(offer)
    return ScrapeResult(offers=_sort_offers_lowest_total(offers), warnings=warnings)


def _candidate_marketplace_url(candidate: ReleaseCandidate, condition: str, page: int) -> str:
    if candidate.master_id:
        return build_master_marketplace_url(candidate.master_id, condition=condition, page=page)
    return build_release_marketplace_url(candidate.release_id, condition=condition, page=page)


def parse_marketplace_html(html: str, candidate: ReleaseCandidate) -> list[Offer]:
    parser = MarketplaceHTMLParser()
    parser.feed(html)
    offers: list[Offer] = []
    artist, album = split_artist_album_display(candidate.album_display)
    for row in parser.rows:
        offer = _offer_from_row(row, candidate, artist, album)
        if offer is not None:
            offers.append(offer)
    return _sort_offers_lowest_total(offers)


def _sort_offers_lowest_total(offers: Iterable[Offer]) -> list[Offer]:
    return sorted(
        offers,
        key=lambda offer: (
            offer.single_item_total,
            offer.item_price,
            offer.shipping_price,
            offer.seller.casefold(),
            offer.listing_id or offer.listing_url,
        ),
    )


class MarketplaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None
        self.depth = 0
        self.shipping_depth: int | None = None
        self.shipping_text: list[str] = []
        self.converted_depth: int | None = None
        self.converted_text: list[str] = []
        self.title_depth: int | None = None
        self.title_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set((attrs_dict.get("class") or "").split())

        if tag == "tr" and "shortcut_navigable" in classes:
            self.current = {
                "release_id": attrs_dict.get("data-release-id"),
                "text_parts": [],
                "listing_url": None,
                "listing_title": "",
                "item_price": None,
                "currency": None,
                "seller": None,
                "seller_id": None,
                "shipping_text": "",
                "converted_text": "",
            }
            self.depth = 1
            self.shipping_depth = None
            self.shipping_text = []
            self.converted_depth = None
            self.converted_text = []
            self.title_depth = None
            self.title_text = []
            return

        if self.current is None:
            return

        self.depth += 1
        if tag == "a" and "item_description_title" in classes:
            self.current["listing_url"] = _absolute_discogs_url(attrs_dict.get("href", ""))
            self.title_depth = self.depth
            self.title_text = []
        if tag == "span" and "price" in classes and self.current.get("item_price") is None:
            self.current["item_price"] = attrs_dict.get("data-pricevalue")
            self.current["currency"] = attrs_dict.get("data-currency") or "GBP"
        if tag == "span" and "item_shipping" in classes:
            self.shipping_depth = self.depth
            self.shipping_text = []
        if tag == "span" and "converted_price" in classes:
            self.converted_depth = self.depth
            self.converted_text = []
        if tag == "button" and "show-shipping-methods" in classes:
            self.current["seller"] = attrs_dict.get("data-seller-username")
            self.current["seller_id"] = attrs_dict.get("data-seller-id")

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        self.current["text_parts"].append(data)
        if self.shipping_depth is not None:
            self.shipping_text.append(data)
        if self.converted_depth is not None:
            self.converted_text.append(data)
        if self.title_depth is not None:
            self.title_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return

        if self.shipping_depth == self.depth:
            self.current["shipping_text"] = "".join(self.shipping_text)
            self.shipping_depth = None
        if self.converted_depth == self.depth:
            self.current["converted_text"] = "".join(self.converted_text)
            self.converted_depth = None
        if self.title_depth == self.depth:
            self.current["listing_title"] = " ".join("".join(self.title_text).split())
            self.title_depth = None

        self.depth -= 1
        if self.depth == 0:
            self.current["text"] = " ".join(" ".join(self.current["text_parts"]).split())
            self.rows.append(self.current)
            self.current = None


def _offer_from_row(row: dict[str, object], candidate: ReleaseCandidate, artist: str, album: str) -> Offer | None:
    text = str(row.get("text") or "")
    try:
        condition = _condition_from_text(text)
    except ValueError:
        return None
    if condition not in ALLOWED_MEDIA_CONDITIONS:
        return None

    listing_url = str(row.get("listing_url") or "")
    if not listing_url:
        return None
    listing_title = str(row.get("listing_title") or "").strip()
    if not listing_title or not title_matches_artist_album(listing_title, artist, album):
        return None
    item_price = _decimal(row.get("item_price"))
    shipping_price = _shipping_price(str(row.get("shipping_text") or text))
    if item_price is None or shipping_price is None:
        return None

    seller = str(row.get("seller") or "").strip()
    if not seller:
        seller = _seller_from_text(text)
    if not seller:
        return None

    rating, reviews = _seller_rating_from_text(text)
    release_id = _row_release_id(row) or candidate.release_id or None
    return Offer(
        artist=artist,
        album=album,
        seller=seller,
        ships_from="United Kingdom",
        media_condition=condition,
        item_price=item_price,
        shipping_price=shipping_price,
        currency=str(row.get("currency") or "GBP").upper(),
        listing_url=listing_url,
        release_id=release_id,
        listing_id=_listing_id_from_url(listing_url),
        seller_rating=rating,
        seller_reviews=reviews,
        source={"release_title": candidate.title, "listing_title": listing_title, "title_match": "exact"},
    )

def _condition_from_text(text: str) -> str:
    for condition in sorted(ALLOWED_MEDIA_CONDITIONS, key=len, reverse=True):
        if condition in text:
            return canonical_media_condition(condition)
    raise ValueError("No allowed media condition found")


def _seller_rating_from_text(text: str) -> tuple[Decimal | None, int | None]:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*,\s*([0-9,]+)\s+ratings", text)
    if not match:
        return None, None
    return Decimal(match.group(1)).quantize(Decimal("0.01")), int(match.group(2).replace(",", ""))


def _seller_from_text(text: str) -> str | None:
    match = re.search(r"Sleeve Condition:.*?\s+([A-Za-z0-9_.-]+)\s+[0-9]+(?:\.[0-9]+)?%,", text)
    if not match:
        return None
    return match.group(1)


def _shipping_price(text: str) -> Decimal | None:
    match = re.search(r"\+\s*(?:[^\d+\-]*\s*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", text)
    if not match:
        return Decimal("0.00") if "free shipping" in text.casefold() else None
    return _decimal(match.group(1))


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _listing_id_from_url(url: str) -> str | None:
    match = re.search(r"/sell/item/([0-9]+)", url)
    return match.group(1) if match else None


def _row_release_id(row: dict[str, object]) -> int | None:
    release_id = str(row.get("release_id") or "").strip()
    if not release_id:
        return None
    try:
        return int(release_id)
    except ValueError:
        return None


def _absolute_discogs_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"https://www.discogs.com{href}"
    return href
