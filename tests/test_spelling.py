from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.models import AlbumRequest, ReleaseCandidate
from discogs_vinyl_optimizer.spelling import suggest_album_correction


def candidate(title: str) -> ReleaseCandidate:
    return ReleaseCandidate(
        album_key="andrew loyd webber|cats",
        album_display="andrew loyd webber - cats",
        release_id=1,
        title=title,
        country="UK",
        year="1981",
        format_summary="Vinyl, LP",
        uri="/release/1",
        resource_url="https://api.discogs.com/releases/1",
    )


class SpellingTests(unittest.TestCase):
    def test_suggests_close_artist_spelling_from_candidate_title(self):
        album = AlbumRequest("andrew loyd webber", "cats")

        suggestion = suggest_album_correction(album, [candidate("Andrew Lloyd Webber - Cats")])

        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.corrected.artist, "Andrew Lloyd Webber")
        self.assertEqual(suggestion.corrected.album, "Cats")

    def test_rejects_unrelated_release_title(self):
        album = AlbumRequest("andrew loyd webber", "cats")

        suggestion = suggest_album_correction(album, [candidate("Andrew Lloyd Webber - The Phantom Of The Opera")])

        self.assertIsNone(suggestion)

    def test_rejects_release_variants_instead_of_spelling_changes(self):
        album = AlbumRequest("Andrew Lloyd Webber", "Cats")

        suggestion = suggest_album_correction(
            album,
            [candidate("Andrew Lloyd Webber - Cats: Complete Original Broadway Cast Recording")],
        )

        self.assertIsNone(suggestion)


if __name__ == "__main__":
    unittest.main()
