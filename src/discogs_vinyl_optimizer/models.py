from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


ALLOWED_MEDIA_CONDITIONS = {
    "Mint (M)",
    "Near Mint (NM or M-)",
    "Very Good Plus (VG+)",
}

CONDITION_ALIASES = {
    "m": "Mint (M)",
    "mint": "Mint (M)",
    "mint (m)": "Mint (M)",
    "nm": "Near Mint (NM or M-)",
    "near mint": "Near Mint (NM or M-)",
    "near mint (nm or m-)": "Near Mint (NM or M-)",
    "m-": "Near Mint (NM or M-)",
    "vg+": "Very Good Plus (VG+)",
    "very good plus": "Very Good Plus (VG+)",
    "very good plus (vg+)": "Very Good Plus (VG+)",
}

UK_SHIPS_FROM_VALUES = {
    "united kingdom",
    "uk",
    "u.k.",
    "gb",
    "gbr",
    "great britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
}


def normalise_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def album_key(artist: str, album: str) -> str:
    return f"{normalise_text(artist)}|{normalise_text(album)}"


def display_album_key(artist: str, album: str) -> str:
    return f"{artist.strip()} - {album.strip()}"


def canonical_media_condition(value: str) -> str:
    key = normalise_text(value)
    if key not in CONDITION_ALIASES:
        allowed = ", ".join(sorted(ALLOWED_MEDIA_CONDITIONS))
        raise ValueError(f"Unsupported media_condition '{value}'. Allowed: {allowed}")
    return CONDITION_ALIASES[key]


def is_uk_ships_from(value: str) -> bool:
    return normalise_text(value) in UK_SHIPS_FROM_VALUES


@dataclass(frozen=True)
class AlbumRequest:
    artist: str
    album: str
    release_id: int | None = None

    @property
    def key(self) -> str:
        return album_key(self.artist, self.album)

    @property
    def display(self) -> str:
        return display_album_key(self.artist, self.album)


@dataclass(frozen=True)
class ReleaseCandidate:
    album_key: str
    album_display: str
    release_id: int
    title: str
    country: str
    year: str
    format_summary: str
    uri: str
    resource_url: str
    want: int | None = None
    have: int | None = None
    master_id: int | None = None

    @property
    def discogs_url(self) -> str:
        if self.uri.startswith("http"):
            return self.uri
        return f"https://www.discogs.com{self.uri}"


@dataclass(frozen=True)
class Offer:
    artist: str
    album: str
    seller: str
    ships_from: str
    media_condition: str
    item_price: Decimal
    shipping_price: Decimal
    currency: str
    listing_url: str
    release_id: int | None = None
    listing_id: str | None = None
    seller_rating: Decimal | None = None
    seller_reviews: int | None = None
    source: dict[str, Any] | None = None

    @property
    def album_key(self) -> str:
        return album_key(self.artist, self.album)

    @property
    def album_display(self) -> str:
        return display_album_key(self.artist, self.album)

    @property
    def single_item_total(self) -> Decimal:
        return self.item_price + self.shipping_price


@dataclass(frozen=True)
class PurchaseOption:
    rank: int
    offers: tuple[Offer, ...]
    item_total: Decimal
    shipping_total: Decimal
    total: Decimal
    currency: str
    shipping_by_seller: dict[str, Decimal]
