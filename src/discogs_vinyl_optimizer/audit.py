from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .io import read_albums, read_offers
from .matching import title_matches_artist_album
from .models import ALLOWED_MEDIA_CONDITIONS, album_key
from .reports import html_escape, money


@dataclass(frozen=True)
class AuditResult:
    passed: bool
    checks: list[str]
    failures: list[str]
    warnings: list[str]
    coverage: list[dict[str, str]]


def audit_purchase_outputs(
    albums_path: str | Path,
    offers_path: str | Path,
    options_path: str | Path,
) -> AuditResult:
    albums = read_albums(albums_path)
    offers = read_offers(offers_path)
    options = json.loads(Path(options_path).read_text(encoding="utf-8"))

    checks: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    offer_lookup = {offer.listing_url: offer for offer in offers}
    album_order = {album.key: album for album in albums}

    checks.append(f"Loaded {len(albums)} requested album(s).")
    checks.append(f"Loaded {len(offers)} scraped eligible offer(s).")
    checks.append(f"Loaded {len(options)} purchase option(s).")

    _audit_offer_pool(offers, album_order, failures, warnings)
    for option in options:
        _audit_option(option, offer_lookup, failures)

    coverage = _coverage_rows(albums, offers)
    for row in coverage:
        if row["offers"] == "0":
            failures.append(f"No eligible scraped offers for {row['album']}.")

    if not failures:
        checks.append("All arithmetic checks passed.")
        checks.append("Every selected listing exists in the scraped offers CSV.")
        checks.append("Every selected offer uses an allowed media condition, UK seller location, and one currency.")
        checks.append("Every scraped listing title matched the requested artist and album when listing titles were available.")
    return AuditResult(
        passed=not failures,
        checks=checks,
        failures=failures,
        warnings=warnings,
        coverage=coverage,
    )


def write_audit_html(result: AuditResult, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if result.passed else "FAIL"
    body = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head><meta charset=\"utf-8\"><title>Discogs Audit Report</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45;color:#222}table{border-collapse:collapse;width:100%;margin:12px 0 24px}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f3f3f3}.pass{color:#126b28;font-weight:700}.fail{color:#9b1c1c;font-weight:700}.warn{background:#fff4d6;border:1px solid #e0bd54;padding:10px;margin:8px 0}</style>",
        "</head><body>",
        f"<h1>Discogs Audit Report: <span class=\"{'pass' if result.passed else 'fail'}\">{status}</span></h1>",
        "<h2>Checks</h2><ul>",
    ]
    for check in result.checks:
        body.append(f"<li>{html_escape(check)}</li>")
    body.append("</ul>")
    if result.failures:
        body.append("<h2>Failures</h2><ul>")
        for failure in result.failures:
            body.append(f"<li>{html_escape(failure)}</li>")
        body.append("</ul>")
    if result.warnings:
        body.append("<h2>Warnings</h2>")
        for warning in result.warnings:
            body.append(f"<div class=\"warn\">{html_escape(warning)}</div>")
    body.append("<h2>Offer Coverage</h2>")
    body.append("<table><thead><tr><th>Album</th><th>Offers</th><th>Sellers</th><th>Conditions</th><th>Lowest item + shipping</th></tr></thead><tbody>")
    for row in result.coverage:
        body.append(
            "<tr>"
            f"<td>{html_escape(row['album'])}</td>"
            f"<td>{html_escape(row['offers'])}</td>"
            f"<td>{html_escape(row['sellers'])}</td>"
            f"<td>{html_escape(row['conditions'])}</td>"
            f"<td>{html_escape(row['lowest_total'])}</td>"
            "</tr>"
        )
    body.append("</tbody></table>")
    body.append("</body></html>")
    output_path.write_text("\n".join(body), encoding="utf-8")


def write_audit_json(result: AuditResult, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": result.passed,
        "checks": result.checks,
        "failures": result.failures,
        "warnings": result.warnings,
        "coverage": result.coverage,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _audit_offer_pool(offers, album_order, failures: list[str], warnings: list[str]) -> None:
    currencies = {offer.currency for offer in offers}
    if len(currencies) > 1:
        failures.append(f"Mixed currencies in offers CSV: {', '.join(sorted(currencies))}.")
    for offer in offers:
        if offer.album_key not in album_order:
            warnings.append(f"Scraped offer does not match requested albums: {offer.album_display}.")
        if offer.media_condition not in ALLOWED_MEDIA_CONDITIONS:
            failures.append(f"Disallowed media condition for {offer.listing_url}: {offer.media_condition}.")
        if offer.ships_from.strip().casefold() not in {"united kingdom", "uk", "gb", "gbr"}:
            failures.append(f"Offer is not marked as UK shipping/source: {offer.listing_url}.")
        listing_title = (offer.source or {}).get("listing_title", "")
        if listing_title and not title_matches_artist_album(str(listing_title), offer.artist, offer.album):
            failures.append(
                f"Listing title does not match requested artist/album for {offer.listing_url}: {listing_title}."
            )


def _audit_option(option: dict[str, Any], offer_lookup, failures: list[str]) -> None:
    rank = option.get("rank")
    currency = str(option.get("currency", "GBP"))
    selected = option.get("offers") or []
    item_total = sum((Decimal(str(offer["item_price"])) for offer in selected), Decimal("0.00"))
    shipping_by_seller: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    listing_ids = []

    for selected_offer in selected:
        listing_url = selected_offer.get("listing_url")
        if listing_url not in offer_lookup:
            failures.append(f"Option {rank}: selected listing is missing from offers CSV: {listing_url}.")
            continue
        source_offer = offer_lookup[listing_url]
        listing_ids.append(source_offer.listing_id or source_offer.listing_url)
        shipping_by_seller[source_offer.seller] = max(
            shipping_by_seller[source_offer.seller],
            source_offer.shipping_price,
        )

    if len(listing_ids) != len(set(listing_ids)):
        failures.append(f"Option {rank}: duplicate listing selected.")

    shipping_total = sum(shipping_by_seller.values(), Decimal("0.00"))
    total = item_total + shipping_total
    expected_item_total = Decimal(str(option.get("item_total", "0.00")))
    expected_shipping_total = Decimal(str(option.get("shipping_total_estimate", "0.00")))
    expected_total = Decimal(str(option.get("total_estimate", "0.00")))

    if item_total != expected_item_total:
        failures.append(f"Option {rank}: item total mismatch, recalculated {money(item_total, currency)}.")
    if shipping_total != expected_shipping_total:
        failures.append(f"Option {rank}: shipping total mismatch, recalculated {money(shipping_total, currency)}.")
    if total != expected_total:
        failures.append(f"Option {rank}: grand total mismatch, recalculated {money(total, currency)}.")

    reported_shipping = {
        seller: Decimal(str(amount))
        for seller, amount in (option.get("shipping_by_seller") or {}).items()
    }
    if dict(shipping_by_seller) != reported_shipping:
        failures.append(f"Option {rank}: shipping_by_seller does not match recalculated seller shipping.")


def _coverage_rows(albums, offers) -> list[dict[str, str]]:
    grouped = defaultdict(list)
    for offer in offers:
        grouped[offer.album_key].append(offer)

    rows: list[dict[str, str]] = []
    for album in albums:
        album_offers = grouped[album.key]
        sellers = {offer.seller for offer in album_offers}
        conditions = Counter(offer.media_condition for offer in album_offers)
        lowest = min((offer.single_item_total for offer in album_offers), default=None)
        currency = album_offers[0].currency if album_offers else "GBP"
        rows.append(
            {
                "album": album.display,
                "offers": str(len(album_offers)),
                "sellers": str(len(sellers)),
                "conditions": ", ".join(f"{name}: {count}" for name, count in sorted(conditions.items())),
                "lowest_total": money(lowest, currency) if lowest is not None else "",
            }
        )
    return rows
