from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import quote

from .catalog import search_releases
from .http_client import DiscogsClient, DiscogsHttpError
from .models import ALLOWED_MEDIA_CONDITIONS, AlbumRequest, Offer, is_uk_ships_from
from .seller_watchlist import SellerWatchlistEntry


@dataclass(frozen=True)
class InventorySearchResult:
    offers: list[Offer]
    warnings: list[str]


ARTIST_FILLER_TOKENS = {
    "band",
    "ensemble",
    "group",
    "orchestra",
    "quartet",
    "quintet",
    "sextet",
    "the",
    "trio",
}


def search_seller_inventory_offers(
    client: DiscogsClient,
    albums: list[AlbumRequest],
    sellers: Iterable[SellerWatchlistEntry],
    per_query: int = 10,
    max_pages_per_query: int = 1,
    catalog_per_album: int = 25,
) -> InventorySearchResult:
    if per_query < 1 or per_query > 100:
        raise ValueError("per_query must be between 1 and 100")
    if max_pages_per_query < 1:
        raise ValueError("max_pages_per_query must be at least 1")
    if catalog_per_album < 0:
        raise ValueError("catalog_per_album cannot be negative")

    candidate_ids, candidate_warnings = _candidate_release_ids(client, albums, catalog_per_album)
    offers: list[Offer] = []
    warnings = list(candidate_warnings)
    seen: set[tuple[str, str]] = set()

    for seller in sellers:
        for album in albums:
            query = _inventory_query(album)
            for page in range(1, max_pages_per_query + 1):
                try:
                    data = client.get_json(
                        f"/users/{quote(seller.username)}/inventory",
                        params={
                            "status": "For Sale",
                            "sort": "price",
                            "sort_order": "asc",
                            "per_page": per_query,
                            "page": page,
                            "q": query,
                        },
                    )
                except DiscogsHttpError as exc:
                    warnings.append(f"Could not read inventory for seller {seller.username}: {exc}")
                    break

                listings = data.get("listings") or []
                if not listings:
                    break
                for listing in listings:
                    offer = _offer_from_inventory_listing(listing, album, seller, candidate_ids.get(album.key, set()))
                    if offer is None:
                        continue
                    key = (offer.album_key, offer.listing_id or offer.listing_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    offers.append(offer)

    return InventorySearchResult(offers=_sort_offers(offers), warnings=warnings)


def refresh_seller_watchlist_entries(
    client: DiscogsClient,
    entries: Iterable[SellerWatchlistEntry],
    checked_at_utc: str,
) -> tuple[list[SellerWatchlistEntry], list[str]]:
    refreshed: list[SellerWatchlistEntry] = []
    warnings: list[str] = []
    for entry in entries:
        try:
            data = client.get_json(f"/users/{quote(entry.username)}")
        except DiscogsHttpError as exc:
            warnings.append(f"Could not refresh seller {entry.username}: {exc}")
            refreshed.append(entry)
            continue
        refreshed.append(
            SellerWatchlistEntry(
                username=entry.username,
                seller_rating=_decimal_or_none(data.get("seller_rating")) or entry.seller_rating,
                seller_reviews=_int_or_none(data.get("seller_num_ratings")) or entry.seller_reviews,
                observed_offer_count=entry.observed_offer_count,
                source=entry.source or "api_refresh",
                last_checked_utc=checked_at_utc,
            )
        )
    refreshed.sort(
        key=lambda item: (
            -(item.seller_reviews or 0),
            -(item.seller_rating or Decimal("0")),
            item.username.casefold(),
        )
    )
    return refreshed, warnings


def inventory_listing_matches_album(listing: dict, album: AlbumRequest, candidate_release_ids: set[int]) -> bool:
    release = listing.get("release") or {}
    release_id = _int_or_none(release.get("id"))
    if release_id is not None and release_id in candidate_release_ids:
        return _format_is_album_vinyl(release.get("format"))
    return _artist_matches(album.artist, str(release.get("artist") or "")) and _title_matches(
        album.album,
        str(release.get("title") or ""),
    ) and _format_is_album_vinyl(release.get("format"))


def _candidate_release_ids(
    client: DiscogsClient,
    albums: list[AlbumRequest],
    catalog_per_album: int,
) -> tuple[dict[str, set[int]], list[str]]:
    if catalog_per_album == 0:
        return {album.key: set() for album in albums}, []
    values: dict[str, set[int]] = {}
    warnings: list[str] = []
    for album in albums:
        try:
            candidates = search_releases(client, album, per_album=catalog_per_album)
        except DiscogsHttpError as exc:
            warnings.append(f"Could not search Discogs catalog for {album.display}: {exc}")
            candidates = []
        values[album.key] = {candidate.release_id for candidate in candidates}
    return values, warnings


def _inventory_query(album: AlbumRequest) -> str:
    return " ".join(
        re.findall(
            r"[A-Za-z0-9]+",
            unicodedata.normalize("NFKD", f"{album.artist} {album.album}")
            .encode("ascii", "ignore")
            .decode("ascii"),
        )
    )


def _offer_from_inventory_listing(
    listing: dict,
    album: AlbumRequest,
    seller: SellerWatchlistEntry,
    candidate_release_ids: set[int],
) -> Offer | None:
    condition = str(listing.get("condition") or "")
    if condition not in ALLOWED_MEDIA_CONDITIONS:
        return None
    ships_from = str(listing.get("ships_from") or "")
    if not is_uk_ships_from(ships_from):
        return None
    if not inventory_listing_matches_album(listing, album, candidate_release_ids):
        return None

    price_value, currency = _money_from_price_object(listing.get("price"))
    shipping_value, shipping_currency = _money_from_price_object(listing.get("shipping_price"))
    if price_value is None or shipping_value is None:
        return None
    if currency != "GBP" or shipping_currency not in {"", "GBP"}:
        return None

    release = listing.get("release") or {}
    listing_id = str(listing.get("id") or "").strip() or None
    listing_url = str(listing.get("uri") or "")
    if not listing_url and listing_id:
        listing_url = f"https://www.discogs.com/sell/item/{listing_id}"
    if not listing_url:
        return None

    seller_data = listing.get("seller") or {}
    seller_stats = seller_data.get("stats") or {}
    return Offer(
        artist=album.artist,
        album=album.album,
        seller=str(seller_data.get("username") or seller.username),
        ships_from=ships_from,
        media_condition=condition,
        item_price=price_value,
        shipping_price=shipping_value,
        currency=currency,
        listing_url=listing_url,
        release_id=_int_or_none(release.get("id")),
        listing_id=listing_id,
        seller_rating=_decimal_or_none(seller_stats.get("rating")) or seller.seller_rating,
        seller_reviews=_int_or_none(seller_stats.get("total")) or seller.seller_reviews,
        source={
            "source": "seller_inventory_api",
            "release_artist": str(release.get("artist") or ""),
            "release_title": str(release.get("title") or ""),
            "release_format": str(release.get("format") or ""),
        },
    )


def _money_from_price_object(value: object) -> tuple[Decimal | None, str]:
    if not isinstance(value, dict):
        return None, ""
    amount = _decimal_or_none(value.get("value"))
    currency = str(value.get("currency") or "").upper()
    return amount, currency


def _artist_matches(requested: str, actual: str) -> bool:
    requested_tokens = _artist_tokens(requested)
    actual_tokens = _artist_tokens(actual)
    if not requested_tokens or not actual_tokens:
        return False
    overlap = requested_tokens & actual_tokens
    if requested_tokens <= actual_tokens:
        return True
    if len(overlap) >= min(2, len(requested_tokens)) and overlap == actual_tokens:
        return True
    return False


def _title_matches(requested: str, actual: str) -> bool:
    requested_tokens = _normalised_tokens(requested)
    actual_tokens = _normalised_tokens(actual)
    if not requested_tokens or not actual_tokens:
        return False
    if requested_tokens == actual_tokens:
        return True
    return requested_tokens <= actual_tokens


def _format_is_album_vinyl(value: object) -> bool:
    text = str(value or "").casefold()
    if "vinyl" not in text and "lp" not in _normalised_tokens(text):
        return False
    return "lp" in _normalised_tokens(text) or "album" in _normalised_tokens(text)


def _artist_tokens(value: str) -> set[str]:
    return {token for token in _normalised_tokens(value) if token not in ARTIST_FILLER_TOKENS}


def _normalised_tokens(value: str) -> set[str]:
    normalised = unicodedata.normalize("NFKD", value)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"\([^)]*\)", " ", ascii_text)
    ascii_text = ascii_text.replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", ascii_text.casefold())
    return {_canonical_token(token) for token in tokens if token}


def _canonical_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_offers(offers: Iterable[Offer]) -> list[Offer]:
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
