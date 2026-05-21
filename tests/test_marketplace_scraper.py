from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.marketplace_scraper import parse_marketplace_html
from discogs_vinyl_optimizer.models import ReleaseCandidate


HTML = """
<table class="table_block mpitems">
<tbody>
<tr class="shortcut_navigable" data-release-id="249504">
  <td class="item_description">
    <strong><a href="/sell/item/3761251765" class="item_description_title">Rick Astley - Never Gonna Give You Up</a></strong>
    <p>Media Condition: Very Good Plus (VG+) Will show some signs.</p>
    <p>Sleeve Condition: Generic</p>
  </td>
  <td class="seller_info">
    Ronan266
    100.0%, 35 ratings
    Ships From:United Kingdom
  </td>
  <td class="item_price">
    <span class="price" data-currency="GBP" data-pricevalue="0.50">£0.50</span>
    <span class="item_shipping">+£5.55 <button class="show-shipping-methods" data-seller-username="Ronan266" data-seller-id="8527323">shipping</button></span>
  </td>
</tr>
</tbody>
</table>
"""

UNSORTED_HTML = """
<table class="table_block mpitems">
<tbody>
<tr class="shortcut_navigable" data-release-id="249504">
  <td class="item_description">
    <strong><a href="/sell/item/1" class="item_description_title">Rick Astley - Never Gonna Give You Up</a></strong>
    <p>Media Condition: Near Mint (NM or M-)</p>
  </td>
  <td class="seller_info">ExpensiveSeller 99.0%, 10 ratings Ships From:United Kingdom</td>
  <td class="item_price">
    <span class="price" data-currency="GBP" data-pricevalue="5.00">GBP 5.00</span>
    <span class="item_shipping">+GBP 4.00 <button class="show-shipping-methods" data-seller-username="ExpensiveSeller" data-seller-id="1">shipping</button></span>
  </td>
</tr>
<tr class="shortcut_navigable" data-release-id="249504">
  <td class="item_description">
    <strong><a href="/sell/item/2" class="item_description_title">Rick Astley - Never Gonna Give You Up</a></strong>
    <p>Media Condition: Very Good Plus (VG+)</p>
  </td>
  <td class="seller_info">CheapSeller 100.0%, 20 ratings Ships From:United Kingdom</td>
  <td class="item_price">
    <span class="price" data-currency="GBP" data-pricevalue="3.00">GBP 3.00</span>
    <span class="item_shipping">+GBP 2.00 <button class="show-shipping-methods" data-seller-username="CheapSeller" data-seller-id="2">shipping</button></span>
  </td>
</tr>
</tbody>
</table>
"""

WRONG_TITLE_HTML = """
<table class="table_block mpitems">
<tbody>
<tr class="shortcut_navigable" data-release-id="999">
  <td class="item_description">
    <strong><a href="/sell/item/3" class="item_description_title">Various - A Jazz Piano Anthology From Ragtime To Free Jazz</a></strong>
    <p>Media Condition: Near Mint (NM or M-)</p>
  </td>
  <td class="seller_info">WrongSeller 99.0%, 10 ratings Ships From:UnitedKingdom</td>
  <td class="item_price">
    <span class="price" data-currency="GBP" data-pricevalue="1.00">GBP 1.00</span>
    <span class="item_shipping">+GBP 2.00 <button class="show-shipping-methods" data-seller-username="WrongSeller" data-seller-id="3">shipping</button></span>
  </td>
</tr>
</tbody>
</table>
"""


class MarketplaceScraperTests(unittest.TestCase):
    def test_parse_marketplace_listing_row(self):
        candidate = ReleaseCandidate(
            album_key="rick astley|never gonna give you up",
            album_display="Rick Astley - Never Gonna Give You Up",
            release_id=249504,
            title="Rick Astley - Never Gonna Give You Up",
            country="UK",
            year="1987",
            format_summary="Vinyl",
            uri="/release/249504",
            resource_url="https://api.discogs.com/releases/249504",
        )

        offers = parse_marketplace_html(HTML, candidate)

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].seller, "Ronan266")
        self.assertEqual(offers[0].media_condition, "Very Good Plus (VG+)")
        self.assertEqual(str(offers[0].item_price), "0.50")
        self.assertEqual(str(offers[0].shipping_price), "5.55")
        self.assertEqual(offers[0].seller_reviews, 35)
        self.assertEqual(str(offers[0].seller_rating), "100.00")

    def test_parsed_marketplace_offers_are_sorted_by_item_plus_shipping(self):
        candidate = ReleaseCandidate(
            album_key="rick astley|never gonna give you up",
            album_display="Rick Astley - Never Gonna Give You Up",
            release_id=249504,
            title="Rick Astley - Never Gonna Give You Up",
            country="UK",
            year="1987",
            format_summary="Vinyl",
            uri="/release/249504",
            resource_url="https://api.discogs.com/releases/249504",
        )

        offers = parse_marketplace_html(UNSORTED_HTML, candidate)

        self.assertEqual([offer.seller for offer in offers], ["CheapSeller", "ExpensiveSeller"])
        self.assertEqual([str(offer.single_item_total) for offer in offers], ["5.00", "9.00"])

    def test_parse_marketplace_rejects_non_matching_listing_title(self):
        candidate = ReleaseCandidate(
            album_key="dave brubeck|time out",
            album_display="Dave Brubeck - Time Out",
            release_id=0,
            title="Dave Brubeck - Time Out",
            country="",
            year="",
            format_summary="Vinyl",
            uri="",
            resource_url="",
        )

        offers = parse_marketplace_html(WRONG_TITLE_HTML, candidate)

        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
