from decimal import Decimal
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.seller_watchlist import build_seller_watchlist_from_offer_files


class SellerWatchlistTests(unittest.TestCase):
    def test_build_watchlist_filters_by_rating_and_reviews(self):
        offers = Path(__file__).resolve().parent / "fixtures" / "watchlist_offers.csv"
        entries = build_seller_watchlist_from_offer_files(
            [offers],
            min_rating=Decimal("99.00"),
            min_reviews=500,
            max_sellers=10,
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].username, "HighSeller")
        self.assertEqual(entries[0].observed_offer_count, 2)
        self.assertEqual(entries[0].seller_reviews, 1200)


if __name__ == "__main__":
    unittest.main()
