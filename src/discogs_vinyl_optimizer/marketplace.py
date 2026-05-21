from __future__ import annotations

from urllib.parse import urlencode

from .models import ALLOWED_MEDIA_CONDITIONS, AlbumRequest, ReleaseCandidate


DISCOGS_SITE_BASE = "https://www.discogs.com"
UK_SELLER_FILTER = "United Kingdom"
PRICE_LOWEST_SORT = "price,asc"


def build_release_marketplace_url(release_id: int, condition: str | None = None, page: int | None = None) -> str:
    params = [
        ("ships_from", UK_SELLER_FILTER),
        ("format", "Vinyl"),
    ]
    if condition:
        params.append(("condition", condition))
    params.append(("sort", PRICE_LOWEST_SORT))
    if page and page > 1:
        params.append(("page", str(page)))
    return f"{DISCOGS_SITE_BASE}/sell/release/{release_id}?{urlencode(params)}"


def build_master_marketplace_url(master_id: int, condition: str | None = None, page: int | None = None) -> str:
    params = [
        ("master_id", str(master_id)),
        ("ev", "mb"),
        ("ships_from", UK_SELLER_FILTER),
        ("format", "Vinyl"),
    ]
    if condition:
        params.append(("condition", condition))
    params.append(("sort", PRICE_LOWEST_SORT))
    if page and page > 1:
        params.append(("page", str(page)))
    return f"{DISCOGS_SITE_BASE}/sell/list?{urlencode(params)}"


def build_marketplace_search_url(album: AlbumRequest, condition: str | None = None, page: int | None = None) -> str:
    params = [
        ("q", f"{album.artist} {album.album}"),
        ("ships_from", UK_SELLER_FILTER),
        ("format", "Vinyl"),
    ]
    if condition:
        params.append(("condition", condition))
    params.append(("sort", PRICE_LOWEST_SORT))
    if page and page > 1:
        params.append(("page", str(page)))
    return f"{DISCOGS_SITE_BASE}/sell/list?{urlencode(params)}"


def marketplace_rows(candidates: list[ReleaseCandidate], albums: list[AlbumRequest]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_album_keys = {candidate.album_key for candidate in candidates}
    for candidate in candidates:
        for condition in sorted(ALLOWED_MEDIA_CONDITIONS):
            rows.append(
                {
                    "album": candidate.album_display,
                    "release_id": str(candidate.release_id),
                    "title": candidate.title,
                    "condition": condition,
                    "type": "release",
                    "url": build_release_marketplace_url(candidate.release_id, condition=condition),
                }
            )
    for album in albums:
        if album.key not in seen_album_keys:
            for condition in sorted(ALLOWED_MEDIA_CONDITIONS):
                rows.append(
                    {
                        "album": album.display,
                        "release_id": "",
                        "title": "No release candidate returned by the Discogs API",
                        "condition": condition,
                        "type": "search",
                        "url": build_marketplace_search_url(album, condition=condition),
                    }
                )
    return rows
