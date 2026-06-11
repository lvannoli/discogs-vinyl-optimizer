from __future__ import annotations

import re
import unicodedata


def split_artist_album_display(display: str) -> tuple[str, str]:
    parts = re.split(r"\s+[-\u2013\u2014]\s+", display, maxsplit=1)
    if len(parts) != 2:
        return "", display
    artist, album = parts
    return artist, album


def title_matches_artist_album(title: str, artist: str, album: str) -> bool:
    row_artist, row_album = split_artist_album_display(title)
    if not row_artist or not row_album:
        return False
    return normalise_artist_match_text(row_artist) == normalise_artist_match_text(artist) and normalise_match_text(
        strip_discogs_format_suffix(row_album)
    ) == normalise_match_text(album)


def strip_discogs_format_suffix(value: str) -> str:
    return re.sub(r"\s+\([^)]*\)\s*$", "", value).strip()


def normalise_match_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_discogs_suffixes = re.sub(r"\s*\([0-9]+\)\s*$", "", without_accents)
    without_punctuation = without_discogs_suffixes.replace("&", " and ")
    without_punctuation = re.sub(r"[*'\u2019`]", "", without_punctuation)
    without_punctuation = re.sub(r"[^a-zA-Z0-9]+", " ", without_punctuation)
    return " ".join(without_punctuation.casefold().split())


def normalise_artist_match_text(value: str) -> str:
    normalised = normalise_match_text(value)
    if normalised.startswith("the "):
        return normalised[4:]
    return normalised
