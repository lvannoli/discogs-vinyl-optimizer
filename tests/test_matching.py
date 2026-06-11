from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.matching import title_matches_artist_album


class MatchingTests(unittest.TestCase):
    def test_title_matches_exact_artist_and_album_after_normalisation(self):
        self.assertTrue(
            title_matches_artist_album(
                "Keith Jarrett - The K\u00f6ln Concert",
                "Keith Jarrett",
                "The Koln Concert",
            )
        )

    def test_title_matches_discogs_listing_with_format_suffix(self):
        self.assertTrue(
            title_matches_artist_album(
                "The Smiths - The Smiths (LP, Album, RE)",
                "The Smiths",
                "The Smiths",
            )
        )

    def test_title_matches_artist_with_optional_the(self):
        self.assertTrue(title_matches_artist_album("The Beatles - Revolver", "Beatles", "Revolver"))
        self.assertTrue(title_matches_artist_album("Beatles - Revolver", "The Beatles", "Revolver"))

    def test_title_rejects_wrong_artist_or_album(self):
        self.assertFalse(
            title_matches_artist_album(
                "Various - A Jazz Piano Anthology From Ragtime To Free Jazz",
                "Dave Brubeck",
                "Time Out",
            )
        )


if __name__ == "__main__":
    unittest.main()
