from __future__ import annotations

from decimal import Decimal

from .http_client import DiscogsClient, DiscogsHttpError
from .models import Offer


def enrich_seller_ratings(client: DiscogsClient, offers: list[Offer]) -> tuple[list[Offer], list[str]]:
    sellers = sorted({offer.seller for offer in offers if offer.seller})
    seller_data: dict[str, tuple[Decimal | None, int | None]] = {}
    warnings: list[str] = []
    for seller in sellers:
        try:
            data = client.get_json(f"/users/{seller}")
        except DiscogsHttpError as exc:
            warnings.append(f"Could not fetch seller rating for {seller}: {exc}")
            continue
        rating = _decimal_or_none(data.get("seller_rating"))
        reviews = _int_or_none(data.get("seller_num_ratings"))
        seller_data[seller] = (rating, reviews)

    enriched: list[Offer] = []
    for offer in offers:
        rating, reviews = seller_data.get(offer.seller, (None, None))
        enriched.append(
            Offer(
                artist=offer.artist,
                album=offer.album,
                seller=offer.seller,
                ships_from=offer.ships_from,
                media_condition=offer.media_condition,
                item_price=offer.item_price,
                shipping_price=offer.shipping_price,
                currency=offer.currency,
                listing_url=offer.listing_url,
                release_id=offer.release_id,
                listing_id=offer.listing_id,
                seller_rating=offer.seller_rating if offer.seller_rating is not None else rating,
                seller_reviews=offer.seller_reviews if offer.seller_reviews is not None else reviews,
                source=offer.source,
            )
        )
    return enriched, warnings


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

