from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.inventory_api import inventory_listing_matches_album
from discogs_vinyl_optimizer.models import AlbumRequest


class InventoryApiTests(unittest.TestCase):
    def test_listing_match_rejects_keyword_false_positive(self):
        album = AlbumRequest(artist="The Beatles", album="Please Please Me")
        listing = {
            "release": {
                "id": 910351570,
                "artist": "Star Sound",
                "title": "The Greatest Rock 'N' Roll Band In The World / Beatles Medley",
                "format": '7", Single',
            }
        }

        self.assertFalse(inventory_listing_matches_album(listing, album, candidate_release_ids=set()))

    def test_listing_match_accepts_album_title_and_artist(self):
        album = AlbumRequest(artist="John Coltrane", album="A Love Supreme")
        listing = {
            "release": {
                "id": 123,
                "artist": "John Coltrane Quartet",
                "title": "A Love Supreme",
                "format": "LP, Album",
            }
        }

        self.assertTrue(inventory_listing_matches_album(listing, album, candidate_release_ids=set()))

    def test_listing_match_accepts_candidate_release_id(self):
        album = AlbumRequest(artist="The Beatles", album="Sgt. Peppers")
        listing = {
            "release": {
                "id": 999,
                "artist": "The Beatles",
                "title": "Sgt. Pepper's Lonely Hearts Club Band",
                "format": "LP, Album",
            }
        }

        self.assertTrue(inventory_listing_matches_album(listing, album, candidate_release_ids={999}))


if __name__ == "__main__":
    unittest.main()
