from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.marketplace import build_marketplace_search_url
from discogs_vinyl_optimizer.marketplace import build_master_marketplace_url
from discogs_vinyl_optimizer.marketplace import build_release_marketplace_url
from discogs_vinyl_optimizer.models import AlbumRequest


class MarketplaceUrlTests(unittest.TestCase):
    def test_release_marketplace_url_contains_uk_vinyl_and_one_condition(self):
        url = build_release_marketplace_url(123, condition="Very Good Plus (VG+)")
        self.assertTrue(url.startswith("https://www.discogs.com/sell/release/123?"))
        self.assertIn("ships_from=United+Kingdom", url)
        self.assertIn("format=Vinyl", url)
        self.assertIn("sort=price%2Casc", url)
        self.assertIn("condition=Very+Good+Plus+%28VG%2B%29", url)
        self.assertLess(url.index("condition="), url.index("sort="))
        self.assertNotIn("condition=Mint+%28M%29", url)

    def test_search_marketplace_url_filters_before_lowest_price_sort(self):
        album = AlbumRequest(artist="Dave Brubeck", album="Time Out")
        url = build_marketplace_search_url(album, condition="Near Mint (NM or M-)")

        self.assertTrue(url.startswith("https://www.discogs.com/sell/list?"))
        self.assertIn("q=Dave+Brubeck+Time+Out", url)
        self.assertIn("ships_from=United+Kingdom", url)
        self.assertIn("format=Vinyl", url)
        self.assertIn("sort=price%2Casc", url)
        self.assertIn("condition=Near+Mint+%28NM+or+M-%29", url)
        self.assertLess(url.index("condition="), url.index("sort="))

    def test_master_marketplace_url_uses_master_filter(self):
        url = build_master_marketplace_url(4264, condition="Near Mint (NM or M-)", page=2)

        self.assertTrue(url.startswith("https://www.discogs.com/sell/list?"))
        self.assertIn("master_id=4264", url)
        self.assertIn("ev=mb", url)
        self.assertIn("ships_from=United+Kingdom", url)
        self.assertIn("format=Vinyl", url)
        self.assertIn("condition=Near+Mint+%28NM+or+M-%29", url)
        self.assertIn("sort=price%2Casc", url)
        self.assertIn("page=2", url)


if __name__ == "__main__":
    unittest.main()
