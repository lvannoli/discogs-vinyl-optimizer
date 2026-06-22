from pathlib import Path
from decimal import Decimal
from tempfile import TemporaryDirectory
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.inventory_api import inventory_listing_matches_album, search_seller_inventory_offers
from discogs_vinyl_optimizer.models import AlbumRequest
from discogs_vinyl_optimizer.seller_watchlist import SellerWatchlistEntry


class FakeInventoryClient:
    def __init__(self) -> None:
        self.sellers: list[str] = []

    def get_json(self, path, params=None):
        seller = path.split("/")[2]
        self.sellers.append(seller)
        return {
            "listings": [
                {
                    "id": f"{seller}-1",
                    "uri": f"https://www.discogs.com/sell/item/{seller}-1",
                    "condition": "Mint (M)",
                    "ships_from": "United Kingdom",
                    "price": {"value": "10.00", "currency": "GBP"},
                    "shipping_price": {"value": "4.00", "currency": "GBP"},
                    "release": {
                        "id": 123,
                        "artist": "The Beatles",
                        "title": "Revolver",
                        "format": "LP, Album",
                    },
                    "seller": {
                        "username": seller,
                        "stats": {"rating": "99.90", "total": 1000},
                    },
                }
            ]
        }


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

    def test_inventory_search_resumes_from_checkpoint(self):
        album = AlbumRequest(artist="The Beatles", album="Revolver")
        sellers = [
            SellerWatchlistEntry("seller-a", seller_rating=Decimal("99.90"), seller_reviews=1000),
            SellerWatchlistEntry("seller-b", seller_rating=Decimal("99.90"), seller_reviews=1000),
        ]
        progress_seen = []

        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "inventory_checkpoint.json"

            def stop_after_first_seller(progress):
                progress_seen.append(progress)
                if progress.current_seller == 1:
                    raise RuntimeError("stop after checkpoint")

            first_client = FakeInventoryClient()
            with self.assertRaises(RuntimeError):
                search_seller_inventory_offers(
                    client=first_client,
                    albums=[album],
                    sellers=sellers,
                    catalog_per_album=0,
                    checkpoint_path=checkpoint_path,
                    progress_callback=stop_after_first_seller,
                )

            self.assertTrue(checkpoint_path.exists())
            self.assertEqual(first_client.sellers, ["seller-a"])
            self.assertEqual(progress_seen[0].total_offers, 1)

            second_client = FakeInventoryClient()
            resumed_progress = []
            result = search_seller_inventory_offers(
                client=second_client,
                albums=[album],
                sellers=sellers,
                catalog_per_album=0,
                checkpoint_path=checkpoint_path,
                progress_callback=resumed_progress.append,
            )

        self.assertEqual(second_client.sellers, ["seller-b"])
        self.assertEqual(len(result.offers), 2)
        self.assertEqual({offer.seller for offer in result.offers}, {"seller-a", "seller-b"})
        self.assertTrue(resumed_progress[0].skipped)
        self.assertEqual(resumed_progress[-1].total_offers, 2)


if __name__ == "__main__":
    unittest.main()
