from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


WATCHLIST_FIELDS = [
    "username",
    "seller_rating",
    "seller_reviews",
    "observed_offer_count",
    "source",
    "last_checked_utc",
]


@dataclass(frozen=True)
class SellerWatchlistEntry:
    username: str
    seller_rating: Decimal | None = None
    seller_reviews: int | None = None
    observed_offer_count: int = 0
    source: str = ""
    last_checked_utc: str = ""


def read_seller_watchlist(
    path: str | Path,
    min_rating: Decimal | None = None,
    min_reviews: int | None = None,
    limit: int | None = None,
) -> list[SellerWatchlistEntry]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Seller watchlist not found: {input_path}")
    entries: list[SellerWatchlistEntry] = []
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"username"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{input_path} is missing required column(s): {', '.join(sorted(missing))}")
        for row in reader:
            username = (row.get("username") or "").strip()
            if not username:
                continue
            entry = SellerWatchlistEntry(
                username=username,
                seller_rating=_optional_decimal(row.get("seller_rating")),
                seller_reviews=_optional_int(row.get("seller_reviews")),
                observed_offer_count=_optional_int(row.get("observed_offer_count")) or 0,
                source=(row.get("source") or "").strip(),
                last_checked_utc=(row.get("last_checked_utc") or "").strip(),
            )
            if min_rating is not None and (entry.seller_rating is None or entry.seller_rating < min_rating):
                continue
            if min_reviews is not None and (entry.seller_reviews is None or entry.seller_reviews < min_reviews):
                continue
            entries.append(entry)
    entries.sort(
        key=lambda item: (
            -(item.seller_reviews or 0),
            -(item.seller_rating or Decimal("0")),
            item.username.casefold(),
        )
    )
    return entries[:limit] if limit is not None else entries


def write_seller_watchlist(entries: Iterable[SellerWatchlistEntry], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=WATCHLIST_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "username": entry.username,
                    "seller_rating": _format_decimal(entry.seller_rating),
                    "seller_reviews": entry.seller_reviews if entry.seller_reviews is not None else "",
                    "observed_offer_count": entry.observed_offer_count,
                    "source": entry.source,
                    "last_checked_utc": entry.last_checked_utc,
                }
            )


def build_seller_watchlist_from_offer_files(
    paths: Iterable[str | Path],
    min_rating: Decimal = Decimal("99.00"),
    min_reviews: int = 500,
    max_sellers: int | None = 200,
) -> list[SellerWatchlistEntry]:
    by_username: dict[str, SellerWatchlistEntry] = {}
    for path in paths:
        input_path = Path(path)
        if not input_path.exists():
            raise FileNotFoundError(f"Offers CSV not found: {input_path}")
        with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"seller", "seller_rating", "seller_reviews"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{input_path} is missing required column(s): {', '.join(sorted(missing))}")
            for row in reader:
                username = (row.get("seller") or "").strip()
                if not username:
                    continue
                rating = _optional_decimal(row.get("seller_rating"))
                reviews = _optional_int(row.get("seller_reviews"))
                if rating is None or reviews is None:
                    continue
                if rating < min_rating or reviews < min_reviews:
                    continue
                existing = by_username.get(username)
                observed_count = (existing.observed_offer_count if existing else 0) + 1
                best_rating = max(rating, existing.seller_rating) if existing and existing.seller_rating else rating
                best_reviews = max(reviews, existing.seller_reviews or 0) if existing else reviews
                by_username[username] = SellerWatchlistEntry(
                    username=username,
                    seller_rating=best_rating,
                    seller_reviews=best_reviews,
                    observed_offer_count=observed_count,
                    source="local_offers",
                    last_checked_utc=existing.last_checked_utc if existing else "",
                )
    entries = list(by_username.values())
    entries.sort(
        key=lambda item: (
            -(item.seller_reviews or 0),
            -(item.seller_rating or Decimal("0")),
            item.username.casefold(),
        )
    )
    return entries[:max_sellers] if max_sellers is not None else entries


def checked_now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_decimal(value: str | None) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _optional_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _format_decimal(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else ""
