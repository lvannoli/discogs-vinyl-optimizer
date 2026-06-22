from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from .catalog import search_releases
from .http_client import DiscogsClient, DiscogsHttpError
from .models import ALLOWED_MEDIA_CONDITIONS, AlbumRequest, Offer, is_uk_ships_from
from .seller_watchlist import SellerWatchlistEntry


@dataclass(frozen=True)
class InventorySearchResult:
    offers: list[Offer]
    warnings: list[str]


@dataclass(frozen=True)
class InventorySearchProgress:
    current_seller: int
    total_sellers: int
    seller: str
    seller_offers: int
    total_offers: int
    warnings: int
    elapsed_seconds: float
    skipped: bool = False
    checkpoint_path: str | None = None


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
    checkpoint_path: str | Path | None = None,
    progress_callback: Callable[[InventorySearchProgress], None] | None = None,
) -> InventorySearchResult:
    if per_query < 1 or per_query > 100:
        raise ValueError("per_query must be between 1 and 100")
    if max_pages_per_query < 1:
        raise ValueError("max_pages_per_query must be at least 1")
    if catalog_per_album < 0:
        raise ValueError("catalog_per_album cannot be negative")

    sellers_list = list(sellers)
    started_at = time.monotonic()
    checkpoint = _load_checkpoint(
        checkpoint_path,
        signature=_checkpoint_signature(
            albums=albums,
            sellers=sellers_list,
            per_query=per_query,
            max_pages_per_query=max_pages_per_query,
            catalog_per_album=catalog_per_album,
        ),
    )
    candidate_ids = checkpoint.candidate_ids
    offers = checkpoint.offers
    warnings = checkpoint.warnings
    completed_sellers = set(checkpoint.completed_sellers)
    seen: set[tuple[str, str]] = set()
    for offer in offers:
        seen.add((offer.album_key, offer.listing_id or offer.listing_url))

    if not candidate_ids:
        candidate_ids, candidate_warnings = _candidate_release_ids(client, albums, catalog_per_album)
        warnings.extend(candidate_warnings)
        _write_checkpoint(
            checkpoint_path,
            signature=checkpoint.signature,
            candidate_ids=candidate_ids,
            offers=offers,
            warnings=warnings,
            completed_sellers=completed_sellers,
        )

    total_sellers = len(sellers_list)
    for seller_index, seller in enumerate(sellers_list, start=1):
        if seller.username in completed_sellers:
            if progress_callback is not None:
                progress_callback(
                    InventorySearchProgress(
                        current_seller=seller_index,
                        total_sellers=total_sellers,
                        seller=seller.username,
                        seller_offers=0,
                        total_offers=len(offers),
                        warnings=len(warnings),
                        elapsed_seconds=time.monotonic() - started_at,
                        skipped=True,
                        checkpoint_path=str(checkpoint_path) if checkpoint_path is not None else None,
                    )
                )
            continue
        seller_offer_count = 0
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
                    seller_offer_count += 1

        completed_sellers.add(seller.username)
        _write_checkpoint(
            checkpoint_path,
            signature=checkpoint.signature,
            candidate_ids=candidate_ids,
            offers=offers,
            warnings=warnings,
            completed_sellers=completed_sellers,
        )
        if progress_callback is not None:
            progress_callback(
                InventorySearchProgress(
                    current_seller=seller_index,
                    total_sellers=total_sellers,
                    seller=seller.username,
                    seller_offers=seller_offer_count,
                    total_offers=len(offers),
                    warnings=len(warnings),
                    elapsed_seconds=time.monotonic() - started_at,
                    checkpoint_path=str(checkpoint_path) if checkpoint_path is not None else None,
                )
            )
    return InventorySearchResult(offers=_sort_offers(offers), warnings=warnings)


@dataclass(frozen=True)
class _InventoryCheckpoint:
    signature: dict[str, object]
    candidate_ids: dict[str, set[int]]
    offers: list[Offer]
    warnings: list[str]
    completed_sellers: set[str]


def _checkpoint_signature(
    albums: list[AlbumRequest],
    sellers: list[SellerWatchlistEntry],
    per_query: int,
    max_pages_per_query: int,
    catalog_per_album: int,
) -> dict[str, object]:
    return {
        "album_keys": [album.key for album in albums],
        "seller_usernames": [seller.username for seller in sellers],
        "per_query": per_query,
        "max_pages_per_query": max_pages_per_query,
        "catalog_per_album": catalog_per_album,
    }


def _load_checkpoint(path: str | Path | None, signature: dict[str, object]) -> _InventoryCheckpoint:
    if path is None:
        return _InventoryCheckpoint(
            signature=signature,
            candidate_ids={},
            offers=[],
            warnings=[],
            completed_sellers=set(),
        )
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return _InventoryCheckpoint(
            signature=signature,
            candidate_ids={},
            offers=[],
            warnings=[],
            completed_sellers=set(),
        )
    data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if data.get("signature") != signature:
        raise ValueError(
            f"Checkpoint {checkpoint_path} does not match the current album/seller search. "
            "Use a different --out-dir or remove the checkpoint file."
        )
    candidate_ids = {
        str(album_key): {int(release_id) for release_id in release_ids}
        for album_key, release_ids in (data.get("candidate_ids") or {}).items()
    }
    return _InventoryCheckpoint(
        signature=signature,
        candidate_ids=candidate_ids,
        offers=[_offer_from_checkpoint(row) for row in data.get("offers", [])],
        warnings=[str(warning) for warning in data.get("warnings", [])],
        completed_sellers={str(seller) for seller in data.get("completed_sellers", [])},
    )


def _write_checkpoint(
    path: str | Path | None,
    signature: dict[str, object],
    candidate_ids: dict[str, set[int]],
    offers: list[Offer],
    warnings: list[str],
    completed_sellers: set[str],
) -> None:
    if path is None:
        return
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "signature": signature,
        "candidate_ids": {
            album_key: sorted(release_ids)
            for album_key, release_ids in sorted(candidate_ids.items())
        },
        "completed_sellers": sorted(completed_sellers),
        "warnings": warnings,
        "offers": [_offer_to_checkpoint(offer) for offer in _sort_offers(offers)],
    }
    temp_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(checkpoint_path)


def _offer_to_checkpoint(offer: Offer) -> dict[str, object]:
    return {
        "artist": offer.artist,
        "album": offer.album,
        "seller": offer.seller,
        "ships_from": offer.ships_from,
        "media_condition": offer.media_condition,
        "item_price": str(offer.item_price),
        "shipping_price": str(offer.shipping_price),
        "currency": offer.currency,
        "listing_url": offer.listing_url,
        "release_id": offer.release_id,
        "listing_id": offer.listing_id,
        "seller_rating": str(offer.seller_rating) if offer.seller_rating is not None else None,
        "seller_reviews": offer.seller_reviews,
        "source": offer.source or {},
    }


def _offer_from_checkpoint(row: dict[str, Any]) -> Offer:
    seller_rating = row.get("seller_rating")
    return Offer(
        artist=str(row["artist"]),
        album=str(row["album"]),
        seller=str(row["seller"]),
        ships_from=str(row["ships_from"]),
        media_condition=str(row["media_condition"]),
        item_price=Decimal(str(row["item_price"])).quantize(Decimal("0.01")),
        shipping_price=Decimal(str(row["shipping_price"])).quantize(Decimal("0.01")),
        currency=str(row["currency"]),
        listing_url=str(row["listing_url"]),
        release_id=_int_or_none(row.get("release_id")),
        listing_id=str(row["listing_id"]) if row.get("listing_id") else None,
        seller_rating=Decimal(str(seller_rating)).quantize(Decimal("0.01")) if seller_rating is not None else None,
        seller_reviews=_int_or_none(row.get("seller_reviews")),
        source=dict(row.get("source") or {}),
    )


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
