from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from discogs_shortcut import _candidate_album_correction
from discogs_vinyl_optimizer.models import AlbumRequest, ReleaseCandidate


def candidate(title: str) -> ReleaseCandidate:
    return ReleaseCandidate(
        album_key="",
        album_display="",
        release_id=1,
        title=title,
        country="UK",
        year="1970",
        format_summary="Vinyl, LP",
        uri="/release/1",
        resource_url="https://api.discogs.com/releases/1",
    )


class DiscogsShortcutTests(unittest.TestCase):
    def test_candidate_album_correction_adds_the_to_artist(self):
        correction = _candidate_album_correction(
            AlbumRequest("Beatles", "Revolver"),
            [candidate("The Beatles - Revolver")],
        )

        self.assertIsNotNone(correction)
        self.assertEqual(correction.artist, "The Beatles")
        self.assertEqual(correction.album, "Revolver")

    def test_candidate_album_correction_does_not_keep_discogs_wildcard(self):
        correction = _candidate_album_correction(
            AlbumRequest("Puccini", "Tosca"),
            [candidate("Puccini* - Tosca")],
        )

        self.assertIsNone(correction)


if __name__ == "__main__":
    unittest.main()
