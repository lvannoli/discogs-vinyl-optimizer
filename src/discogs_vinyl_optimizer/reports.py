from __future__ import annotations

import html
import json
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Iterable

from .models import Offer, PurchaseOption


CENT = Decimal("0.01")


def html_escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value: Decimal, currency: str) -> str:
    symbol = "£" if currency == "GBP" else f"{currency} "
    return f"{symbol}{value:.2f}"


def percent(value: Decimal) -> str:
    return f"{value:.2f}%"


def write_options_json(options: Iterable[PurchaseOption], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _options_payload(options)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _options_payload(options: Iterable[PurchaseOption]) -> list[dict[str, object]]:
    options = list(options)
    best_total = options[0].total if options else Decimal("0.00")
    payload = []
    for option in options:
        offer_rows = _seller_grouped_offer_rows(option)
        extra_amount = option.total - best_total
        extra_percent = _percent_above_best(option.total, best_total)
        payload.append(
            {
                "rank": option.rank,
                "currency": option.currency,
                "item_total": str(option.item_total),
                "shipping_total_estimate": str(option.shipping_total),
                "total_estimate": str(option.total),
                "extra_vs_cheapest": str(extra_amount),
                "extra_vs_cheapest_percent": str(extra_percent),
                "shipping_model": "one shipping charge per seller, using the highest selected listing shipping value for that seller",
                "album_cost_model": "seller shipping is split evenly across selected items from the same seller for per-album reporting only",
                "shipping_by_seller": {
                    seller: str(amount)
                    for seller, amount in sorted(option.shipping_by_seller.items())
                },
                "offers": [
                    {
                        "artist": offer.artist,
                        "album": offer.album,
                        "release_id": offer.release_id,
                        "seller": offer.seller,
                        "seller_rating": str(offer.seller_rating) if offer.seller_rating is not None else None,
                        "seller_reviews": offer.seller_reviews,
                        "ships_from": offer.ships_from,
                        "media_condition": offer.media_condition,
                        "item_price": str(offer.item_price),
                        "shipping_price": str(offer.shipping_price),
                        "allocated_shipping": str(allocated),
                        "album_total_estimate": str(offer.item_price + allocated),
                        "listing_url": offer.listing_url,
                    }
                    for offer, allocated in offer_rows
                ],
            }
        )
    return payload


def write_options_html(options: Iterable[PurchaseOption], path: str | Path, warnings: list[str] | None = None) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_options_html(options, warnings=warnings), encoding="utf-8")


def _options_html(options: Iterable[PurchaseOption], warnings: list[str] | None = None) -> str:
    options = list(options)
    best_total = options[0].total if options else Decimal("0.00")
    body = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head><meta charset=\"utf-8\"><title>Discogs Vinyl Optimisation</title>",
        "<style>",
        "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45;color:#222}",
        "h1{margin-bottom:4px}h2{margin-top:28px;border-top:2px solid #222;padding-top:16px}",
        "table{border-collapse:collapse;width:100%;margin:12px 0 20px}th,td{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}th{background:#f3f3f3}",
        ".total{font-size:1.15rem;font-weight:700}.warning{background:#fff4d6;border:1px solid #e0bd54;padding:10px;margin:8px 0}.seller-group td{background:#edf2f7;font-weight:700}",
        "</style></head><body>",
        "<h1>Discogs Vinyl Optimisation</h1>",
        "<p>Costs are estimates using one shipping charge per seller, taken as the highest selected listing shipping value for that seller.</p>",
        "<p>Per-album cost splits that seller shipping evenly across selected items from the same seller. This split is for reporting only; the option total is the controlling value.</p>",
    ]
    for warning in warnings or []:
        report_warning = _report_warning(warning)
        if report_warning:
            body.append(f"<div class=\"warning\">{html_escape(report_warning)}</div>")
    if not options:
        body.append("<p>No purchase options were generated.</p>")
    for option in options:
        extra_amount = option.total - best_total
        extra_percent = _percent_above_best(option.total, best_total)
        difference_label = "cheapest option" if option.rank == 1 else (
            f"{money(extra_amount, option.currency)} more than cheapest ({percent(extra_percent)})"
        )
        body.append(f"<h2>Option {option.rank}: {money(option.total, option.currency)}</h2>")
        body.append(
            f"<p class=\"total\">Items: {money(option.item_total, option.currency)} | "
            f"Shipping estimate: {money(option.shipping_total, option.currency)} | "
            f"Total estimate: {money(option.total, option.currency)} | "
            f"Difference: {html_escape(difference_label)}</p>"
        )
        shipping_parts = [
            f"{html_escape(seller)}: {money(amount, option.currency)}"
            for seller, amount in sorted(option.shipping_by_seller.items())
        ]
        body.append(f"<p>Shipping by seller: {'; '.join(shipping_parts)}</p>")
        body.append("<table><thead><tr>")
        for header in [
            "Album",
            "Seller",
            "Rating",
            "Condition",
            "Item",
            "Listing shipping",
            "Allocated shipping",
            "Album total",
            "Listing",
        ]:
            body.append(f"<th>{header}</th>")
        body.append("</tr></thead><tbody>")
        current_seller = None
        for offer, allocated in _seller_grouped_offer_rows(option):
            if offer.seller != current_seller:
                current_seller = offer.seller
                seller_shipping = option.shipping_by_seller.get(offer.seller, Decimal("0.00"))
                body.append(
                    "<tr class=\"seller-group\"><td colspan=\"9\">"
                    f"Seller: {html_escape(offer.seller)} | "
                    f"Shipping estimate: {money(seller_shipping, option.currency)}"
                    "</td></tr>"
                )
            rating = "not available"
            if offer.seller_rating is not None:
                reviews = f" ({offer.seller_reviews} reviews)" if offer.seller_reviews is not None else ""
                rating = f"{offer.seller_rating}%{reviews}"
            body.append("<tr>")
            body.append(f"<td>{html_escape(offer.album_display)}</td>")
            body.append(f"<td>{html_escape(offer.seller)}</td>")
            body.append(f"<td>{html_escape(rating)}</td>")
            body.append(f"<td>{html_escape(offer.media_condition)}</td>")
            body.append(f"<td>{money(offer.item_price, option.currency)}</td>")
            body.append(f"<td>{money(offer.shipping_price, option.currency)}</td>")
            body.append(f"<td>{money(allocated, option.currency)}</td>")
            body.append(f"<td>{money(offer.item_price + allocated, option.currency)}</td>")
            body.append(
                f"<td><a href=\"{html_escape(offer.listing_url)}\">Open Discogs listing</a></td>"
            )
            body.append("</tr>")
        body.append("</tbody></table>")
    body.extend(["</body></html>"])
    return "\n".join(body)


def allocate_shipping_by_offer(option: PurchaseOption) -> list[Decimal]:
    seller_indexes: dict[str, list[int]] = defaultdict(list)
    for index, offer in enumerate(option.offers):
        seller_indexes[offer.seller].append(index)

    allocations = [Decimal("0.00")] * len(option.offers)
    for seller, indexes in seller_indexes.items():
        seller_shipping = option.shipping_by_seller.get(seller, Decimal("0.00"))
        base = (seller_shipping / len(indexes)).quantize(CENT, rounding=ROUND_DOWN)
        remainder_cents = int(((seller_shipping - (base * len(indexes))) * 100).to_integral_value())
        for offset, index in enumerate(indexes):
            allocations[index] = base + (CENT if offset < remainder_cents else Decimal("0.00"))
    return allocations


def _seller_grouped_offer_rows(option: PurchaseOption) -> list[tuple[Offer, Decimal]]:
    allocated_shipping = allocate_shipping_by_offer(option)
    rows = [
        (offer, allocated_shipping[index])
        for index, offer in enumerate(option.offers)
    ]
    return sorted(
        rows,
        key=lambda row: (
            row[0].seller.casefold(),
            row[0].album.casefold(),
            row[0].artist.casefold(),
            row[0].item_price,
            row[0].listing_url,
        ),
    )


def _percent_above_best(total: Decimal, best_total: Decimal) -> Decimal:
    if best_total == Decimal("0.00"):
        return Decimal("0.00")
    return ((total - best_total) / best_total * Decimal("100")).quantize(CENT)


def _report_warning(warning: str) -> str | None:
    if warning.startswith("Discogs marketplace page returned HTTP 403:"):
        return None
    if warning.startswith("Skipped one optional Discogs marketplace page during scraping"):
        return None
    return warning
