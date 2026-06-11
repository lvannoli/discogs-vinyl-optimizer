from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decimal import Decimal

from discogs_vinyl_optimizer.models import AlbumRequest, Offer
from discogs_vinyl_optimizer.optimizer import optimise_purchases


def offer(artist, album, seller, item, shipping):
    return Offer(
        artist=artist,
        album=album,
        seller=seller,
        ships_from="United Kingdom",
        media_condition="Near Mint (NM or M-)",
        item_price=Decimal(item),
        shipping_price=Decimal(shipping),
        currency="GBP",
        listing_url=f"https://www.discogs.com/sell/item/{seller}-{album}",
    )


class OptimizerTests(unittest.TestCase):
    def test_optimiser_accounts_for_combined_shipping_by_seller(self):
        albums = [
            AlbumRequest("Artist A", "Album A"),
            AlbumRequest("Artist B", "Album B"),
        ]
        offers = [
            offer("Artist A", "Album A", "seller_one", "18.00", "4.50"),
            offer("Artist B", "Album B", "seller_one", "12.00", "4.50"),
            offer("Artist A", "Album A", "seller_two", "14.00", "5.00"),
            offer("Artist B", "Album B", "seller_three", "11.00", "3.50"),
        ]

        options = optimise_purchases(albums, offers, top_n=3)

        self.assertEqual(options[0].total, Decimal("33.50"))
        self.assertEqual([selected.seller for selected in options[0].offers], ["seller_two", "seller_three"])
        self.assertEqual(options[1].total, Decimal("34.50"))
        self.assertEqual([selected.seller for selected in options[1].offers], ["seller_one", "seller_one"])

    def test_optimiser_can_build_partial_options_when_allowed(self):
        albums = [
            AlbumRequest("Artist A", "Album A"),
            AlbumRequest("Artist B", "Album B"),
        ]
        offers = [
            offer("Artist A", "Album A", "seller_one", "18.00", "4.50"),
        ]

        options = optimise_purchases(albums, offers, allow_missing=True)

        self.assertEqual(len(options), 1)
        self.assertEqual([selected.album for selected in options[0].offers], ["Album A"])


if __name__ == "__main__":
    unittest.main()
