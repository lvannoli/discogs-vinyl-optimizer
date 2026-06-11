from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from decimal import Decimal

from discogs_vinyl_optimizer.models import Offer, PurchaseOption
from discogs_vinyl_optimizer.reports import _options_html, _options_payload


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


def purchase_option():
    return PurchaseOption(
        rank=1,
        offers=(
            offer("Artist B", "Album B", "seller_b", "10.00", "4.00"),
            offer("Artist C", "Album C", "seller_a", "12.00", "6.00"),
            offer("Artist A", "Album A", "seller_a", "8.00", "2.00"),
        ),
        item_total=Decimal("30.00"),
        shipping_total=Decimal("10.00"),
        total=Decimal("40.00"),
        currency="GBP",
        shipping_by_seller={
            "seller_b": Decimal("4.00"),
            "seller_a": Decimal("6.00"),
        },
    )


class ReportTests(unittest.TestCase):
    def test_options_json_orders_offers_by_seller(self):
        payload = _options_payload([purchase_option()])
        offers = payload[0]["offers"]
        self.assertEqual(
            [(row["seller"], row["album"]) for row in offers],
            [
                ("seller_a", "Album A"),
                ("seller_a", "Album C"),
                ("seller_b", "Album B"),
            ],
        )

    def test_options_html_groups_rows_by_seller(self):
        html = _options_html([purchase_option()])
        seller_a = html.index("Seller: seller_a")
        album_a = html.index("Artist A - Album A")
        album_c = html.index("Artist C - Album C")
        seller_b = html.index("Seller: seller_b")
        album_b = html.index("Artist B - Album B")
        self.assertLess(seller_a, album_a)
        self.assertLess(album_a, album_c)
        self.assertLess(album_c, seller_b)
        self.assertLess(seller_b, album_b)


if __name__ == "__main__":
    unittest.main()
