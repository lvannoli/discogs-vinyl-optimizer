from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from .matching import normalise_match_text, split_artist_album_display, strip_discogs_format_suffix
from .models import AlbumRequest, ReleaseCandidate


@dataclass(frozen=True)
class SpellingSuggestion:
    original: AlbumRequest
    corrected: AlbumRequest
    source_title: str
    score: float


def suggest_album_correction(
    album: AlbumRequest,
    candidates: Iterable[ReleaseCandidate],
) -> SpellingSuggestion | None:
    best: SpellingSuggestion | None = None
    for candidate in candidates:
        artist, title = split_artist_album_display(candidate.title)
        title = strip_discogs_format_suffix(title)
        if not artist or not title:
            continue
        artist_score = _text_similarity(album.artist, artist)
        album_score = _text_similarity(album.album, title)
        if not _is_spelling_variant(album.artist, artist, artist_score):
            continue
        if not _is_spelling_variant(album.album, title, album_score):
            continue
        corrected = AlbumRequest(artist=artist, album=title, release_id=album.release_id)
        if normalise_match_text(corrected.display) == normalise_match_text(album.display):
            continue
        suggestion = SpellingSuggestion(
            original=album,
            corrected=corrected,
            source_title=candidate.title,
            score=(artist_score + album_score) / 2,
        )
        if best is None or suggestion.score > best.score:
            best = suggestion
    return best


def _text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalise_match_text(left), normalise_match_text(right)).ratio()


def _is_spelling_variant(left: str, right: str, score: float) -> bool:
    normalised_left = normalise_match_text(left)
    normalised_right = normalise_match_text(right)
    if not normalised_left or not normalised_right:
        return False
    if normalised_left == normalised_right:
        return True
    shortest = min(len(normalised_left), len(normalised_right))
    threshold = 0.75 if shortest <= 4 else 0.86
    return score >= threshold and abs(len(normalised_left) - len(normalised_right)) <= 2
