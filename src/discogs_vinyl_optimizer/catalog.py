from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .http_client import DiscogsClient
from .models import AlbumRequest, ReleaseCandidate


def search_releases(client: DiscogsClient, album: AlbumRequest, per_album: int = 5) -> list[ReleaseCandidate]:
    if album.release_id is not None:
        return [_release_from_id(client, album)]

    params = {
        "artist": album.artist,
        "release_title": album.album,
        "type": "release",
        "format": "Vinyl",
        "per_page": per_album,
    }
    data = client.get_json("/database/search", params=params)
    results = data.get("results", [])
    candidates: list[ReleaseCandidate] = []
    for result in results:
        formats = result.get("format") or []
        if "Vinyl" not in formats:
            continue
        release_id = result.get("id")
        if release_id is None:
            continue
        candidates.append(
            ReleaseCandidate(
                album_key=album.key,
                album_display=album.display,
                release_id=int(release_id),
                title=str(result.get("title", "")),
                country=str(result.get("country", "")),
                year=str(result.get("year", "")),
                format_summary=", ".join(str(value) for value in formats),
                uri=str(result.get("uri", "")),
                resource_url=str(result.get("resource_url", "")),
                want=_community_count(result, "want"),
                have=_community_count(result, "have"),
                master_id=_optional_int_value(result.get("master_id")),
            )
        )
    return candidates


def write_releases_csv(candidates: Iterable[ReleaseCandidate], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "album",
        "release_id",
        "title",
        "country",
        "year",
        "format",
        "want",
        "have",
        "master_id",
        "discogs_url",
        "resource_url",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "album": candidate.album_display,
                    "release_id": candidate.release_id,
                    "title": candidate.title,
                    "country": candidate.country,
                    "year": candidate.year,
                    "format": candidate.format_summary,
                    "want": candidate.want if candidate.want is not None else "",
                    "have": candidate.have if candidate.have is not None else "",
                    "master_id": candidate.master_id if candidate.master_id is not None else "",
                    "discogs_url": candidate.discogs_url,
                    "resource_url": candidate.resource_url,
                }
            )


def read_releases_csv(path: str | Path, albums: list[AlbumRequest]) -> list[ReleaseCandidate]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Release CSV not found: {input_path}")
    albums_by_display = {album.display: album for album in albums}
    candidates: list[ReleaseCandidate] = []
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"album", "release_id", "title", "country", "year", "format", "discogs_url", "resource_url"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{input_path} is missing required column(s): {', '.join(sorted(missing))}")
        for row_number, row in enumerate(reader, start=2):
            display = (row.get("album") or "").strip()
            album = albums_by_display.get(display)
            if album is None:
                raise ValueError(f"Row {row_number}: release album '{display}' is not present in the album input CSV")
            release_id_text = (row.get("release_id") or "").strip()
            if not release_id_text:
                raise ValueError(f"Row {row_number}: missing release_id")
            discogs_url = (row.get("discogs_url") or "").strip()
            uri = discogs_url.replace("https://www.discogs.com", "") if discogs_url else ""
            candidates.append(
                ReleaseCandidate(
                    album_key=album.key,
                    album_display=album.display,
                    release_id=int(release_id_text),
                    title=str(row.get("title", "")),
                    country=str(row.get("country", "")),
                    year=str(row.get("year", "")),
                    format_summary=str(row.get("format", "")),
                    uri=uri,
                    resource_url=str(row.get("resource_url", "")),
                    want=_optional_int(row.get("want")),
                    have=_optional_int(row.get("have")),
                    master_id=_optional_int(row.get("master_id")),
                )
            )
    return candidates


def _release_from_id(client: DiscogsClient, album: AlbumRequest) -> ReleaseCandidate:
    data = client.get_json(f"/releases/{album.release_id}")
    formats = []
    for item in data.get("formats", []):
        name = item.get("name")
        descriptions = item.get("descriptions") or []
        if name:
            formats.append(str(name))
        formats.extend(str(description) for description in descriptions)
    artists = ", ".join(artist.get("name", "") for artist in data.get("artists", []))
    title = data.get("title", "")
    return ReleaseCandidate(
        album_key=album.key,
        album_display=album.display,
        release_id=int(album.release_id),
        title=f"{artists} - {title}".strip(" -"),
        country=str(data.get("country", "")),
        year=str(data.get("year", "")),
        format_summary=", ".join(formats),
        uri=str(data.get("uri", "")),
        resource_url=str(data.get("resource_url", "")),
        want=None,
        have=None,
        master_id=_optional_int_value(data.get("master_id")),
    )


def _community_count(result: dict, key: str) -> int | None:
    community = result.get("community") or {}
    value = community.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_int_value(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed or None
