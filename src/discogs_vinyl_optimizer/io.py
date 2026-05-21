from __future__ import annotations

import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from .models import (
    AlbumRequest,
    Offer,
    canonical_media_condition,
    is_uk_ships_from,
)


ALBUM_REQUIRED_COLUMNS = {"artist", "album"}
OFFER_REQUIRED_COLUMNS = {
    "artist",
    "album",
    "seller",
    "ships_from",
    "media_condition",
    "item_price",
    "shipping_price",
    "currency",
    "listing_url",
}


def read_albums(path: str | Path) -> list[AlbumRequest]:
    rows = _read_csv(path)
    _ensure_columns(rows.fieldnames, ALBUM_REQUIRED_COLUMNS, path)
    albums: list[AlbumRequest] = []
    for row_number, row in enumerate(rows.rows, start=2):
        artist = _required_text(row, "artist", row_number)
        album = _required_text(row, "album", row_number)
        release_id = _optional_int(row.get("release_id"), "release_id", row_number)
        albums.append(AlbumRequest(artist=artist, album=album, release_id=release_id))
    if not albums:
        raise ValueError(f"No album rows found in {path}")
    return albums


def read_offers(path: str | Path) -> list[Offer]:
    rows = _read_csv(path)
    _ensure_columns(rows.fieldnames, OFFER_REQUIRED_COLUMNS, path)
    offers: list[Offer] = []
    for row_number, row in enumerate(rows.rows, start=2):
        ships_from = _required_text(row, "ships_from", row_number)
        if not is_uk_ships_from(ships_from):
            continue
        media_condition = canonical_media_condition(_required_text(row, "media_condition", row_number))
        item_price = _money(row.get("item_price", ""), "item_price", row_number)
        shipping_price = _money(row.get("shipping_price", ""), "shipping_price", row_number)
        currency = _required_text(row, "currency", row_number).upper()
        offers.append(
            Offer(
                artist=_required_text(row, "artist", row_number),
                album=_required_text(row, "album", row_number),
                release_id=_optional_int(row.get("release_id"), "release_id", row_number),
                listing_id=_optional_text(row.get("listing_id")),
                seller=_required_text(row, "seller", row_number),
                ships_from=ships_from,
                media_condition=media_condition,
                item_price=item_price,
                shipping_price=shipping_price,
                currency=currency,
                listing_url=_required_text(row, "listing_url", row_number),
                seller_rating=_optional_decimal(row.get("seller_rating"), "seller_rating", row_number),
                seller_reviews=_optional_int(row.get("seller_reviews"), "seller_reviews", row_number),
                source=dict(row),
            )
        )
    return offers


def write_offers_csv(offers: Iterable[Offer], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "artist",
        "album",
        "release_id",
        "listing_id",
        "seller",
        "ships_from",
        "media_condition",
        "item_price",
        "shipping_price",
        "currency",
        "listing_url",
        "listing_title",
        "seller_rating",
        "seller_reviews",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for offer in offers:
            writer.writerow(
                {
                    "artist": offer.artist,
                    "album": offer.album,
                    "release_id": offer.release_id or "",
                    "listing_id": offer.listing_id or "",
                    "seller": offer.seller,
                    "ships_from": offer.ships_from,
                    "media_condition": offer.media_condition,
                    "item_price": f"{offer.item_price:.2f}",
                    "shipping_price": f"{offer.shipping_price:.2f}",
                    "currency": offer.currency,
                    "listing_url": offer.listing_url,
                    "listing_title": (offer.source or {}).get("listing_title", ""),
                    "seller_rating": offer.seller_rating if offer.seller_rating is not None else "",
                    "seller_reviews": offer.seller_reviews if offer.seller_reviews is not None else "",
                }
            )


def write_marketplace_links_html(rows: Iterable[dict[str, str]], path: str | Path) -> None:
    from .reports import html_escape

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head><meta charset=\"utf-8\"><title>Discogs Marketplace Links</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f3f3f3}</style>",
        "</head><body>",
        "<h1>Discogs Marketplace Links</h1>",
        "<p>Links are filtered for Vinyl, UK sellers, and media condition Mint, Near Mint, or Very Good Plus.</p>",
        "<p><strong>Pricing status:</strong> Discogs does not expose marketplace listing prices and shipping through a public GET API endpoint. Fill the generated offers template or provide an offers CSV to calculate album costs, total spend, and percentage differences between options.</p>",
        "<table><thead><tr><th>Album</th><th>Release</th><th>Title</th><th>Condition</th><th>Pricing</th><th>Link</th></tr></thead><tbody>",
    ]
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html_escape(row['album'])}</td>"
            f"<td>{html_escape(row['release_id'])}</td>"
            f"<td>{html_escape(row['title'])}</td>"
            f"<td>{html_escape(row.get('condition', ''))}</td>"
            "<td>Not available from Discogs GET API</td>"
            f"<td><a href=\"{html_escape(row['url'])}\">Open Discogs marketplace</a></td>"
            "</tr>"
        )
    body.extend(["</tbody></table>", "</body></html>"])
    output_path.write_text("\n".join(body), encoding="utf-8")


def write_offers_template_csv(albums: Iterable[AlbumRequest], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "artist",
        "album",
        "release_id",
        "seller",
        "ships_from",
        "media_condition",
        "item_price",
        "shipping_price",
        "currency",
        "listing_url",
        "seller_rating",
        "seller_reviews",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for album in albums:
            writer.writerow(
                {
                    "artist": album.artist,
                    "album": album.album,
                    "release_id": album.release_id or "",
                    "seller": "",
                    "ships_from": "United Kingdom",
                    "media_condition": "",
                    "item_price": "",
                    "shipping_price": "",
                    "currency": "GBP",
                    "listing_url": "",
                    "seller_rating": "",
                    "seller_reviews": "",
                }
            )


class CsvRows:
    def __init__(self, fieldnames: set[str], rows: list[dict[str, str]]) -> None:
        self.fieldnames = fieldnames
        self.rows = rows


def _read_csv(path: str | Path) -> CsvRows:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"CSV file not found: {input_path}")
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {_normalise_header(name) for name in (reader.fieldnames or [])}
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({_normalise_header(key): value for key, value in row.items() if key is not None})
    return CsvRows(fieldnames=fieldnames, rows=rows)


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _ensure_columns(fieldnames: set[str], required: set[str], path: str | Path) -> None:
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError(f"{path} is missing required column(s): {', '.join(missing)}")


def _required_text(row: dict[str, str], column: str, row_number: int) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise ValueError(f"Row {row_number}: missing required value for '{column}'")
    return value


def _optional_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _optional_int(value: str | None, column: str, row_number: int) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Row {row_number}: '{column}' must be an integer") from exc


def _optional_decimal(value: str | None, column: str, row_number: int) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    return _money(value, column, row_number)


def _money(value: str, column: str, row_number: int) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", value.strip())
    if not cleaned:
        raise ValueError(f"Row {row_number}: missing required value for '{column}'")
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Row {row_number}: '{column}' must be a money amount") from exc
    if amount < Decimal("0.00"):
        raise ValueError(f"Row {row_number}: '{column}' cannot be negative")
    return amount
