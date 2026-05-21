from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .models import AlbumRequest, Offer, PurchaseOption


class OptimisationError(ValueError):
    pass


def optimise_purchases(
    albums: list[AlbumRequest],
    offers: list[Offer],
    top_n: int = 5,
    max_offers_per_album: int = 50,
    beam_width: int = 5000,
) -> list[PurchaseOption]:
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    if max_offers_per_album < 1:
        raise ValueError("max_offers_per_album must be at least 1")
    if beam_width < top_n:
        raise ValueError("beam_width must be greater than or equal to top_n")

    album_order = {album.key: index for index, album in enumerate(albums)}
    wanted_keys = set(album_order)
    eligible = [offer for offer in offers if offer.album_key in wanted_keys]
    if not eligible:
        raise OptimisationError("No eligible offers match the requested albums.")

    currencies = {offer.currency for offer in eligible}
    if len(currencies) != 1:
        raise OptimisationError(f"Cannot optimise mixed currencies: {', '.join(sorted(currencies))}")
    currency = next(iter(currencies))

    grouped: dict[str, list[Offer]] = defaultdict(list)
    for offer in eligible:
        grouped[offer.album_key].append(offer)

    missing = [album.display for album in albums if album.key not in grouped]
    if missing:
        raise OptimisationError("No eligible UK VG+/NM/M offers for: " + "; ".join(missing))

    groups: list[tuple[str, list[Offer]]] = []
    for album in albums:
        album_offers = sorted(
            grouped[album.key],
            key=lambda offer: (offer.single_item_total, offer.item_price, offer.shipping_price, offer.seller),
        )[:max_offers_per_album]
        groups.append((album.key, album_offers))

    groups.sort(key=lambda item: (len(item[1]), album_order[item[0]]))
    states: list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]] = [
        (Decimal("0.00"), tuple(), {})
    ]
    for _, album_offers in groups:
        next_states: list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]] = []
        for running_total, selected, seller_shipping in states:
            ranked_offers = sorted(album_offers, key=lambda offer: _incremental_cost(offer, seller_shipping))
            for offer in ranked_offers:
                current_shipping = seller_shipping.get(offer.seller, Decimal("0.00"))
                new_shipping = max(current_shipping, offer.shipping_price)
                delta_shipping = new_shipping - current_shipping
                updated_shipping = dict(seller_shipping)
                updated_shipping[offer.seller] = new_shipping
                next_states.append(
                    (
                        running_total + offer.item_price + delta_shipping,
                        selected + (offer,),
                        updated_shipping,
                    )
                )
        states = _prune_states(next_states, beam_width)

    solutions: list[PurchaseOption] = []
    for rank, (total, selected, seller_shipping) in enumerate(_dedupe_final_states(states)[:top_n], start=1):
        ordered_offers = tuple(sorted(selected, key=lambda offer: album_order[offer.album_key]))
        item_total = sum((offer.item_price for offer in ordered_offers), Decimal("0.00"))
        shipping_total = sum(seller_shipping.values(), Decimal("0.00"))
        solutions.append(
            PurchaseOption(
                rank=rank,
                offers=ordered_offers,
                item_total=item_total,
                shipping_total=shipping_total,
                total=total,
                currency=currency,
                shipping_by_seller=seller_shipping,
            )
        )
    return solutions


def _incremental_cost(offer: Offer, seller_shipping: dict[str, Decimal]) -> Decimal:
    current_shipping = seller_shipping.get(offer.seller, Decimal("0.00"))
    return offer.item_price + max(Decimal("0.00"), offer.shipping_price - current_shipping)


def _min_remaining_item_costs(groups: list[tuple[str, list[Offer]]]) -> list[Decimal]:
    values = [Decimal("0.00")] * (len(groups) + 1)
    for index in range(len(groups) - 1, -1, -1):
        values[index] = values[index + 1] + min(offer.item_price for offer in groups[index][1])
    return values


def _prune_states(
    states: list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]],
    beam_width: int,
) -> list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]]:
    states.sort(key=lambda state: (state[0], len(state[2])))
    return states[:beam_width]


def _dedupe_final_states(
    states: list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]],
) -> list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[tuple[Decimal, tuple[Offer, ...], dict[str, Decimal]]] = []
    for state in sorted(states, key=lambda item: (item[0], len(item[2]))):
        _, selected, _ = state
        key = tuple(sorted(offer.listing_id or offer.listing_url for offer in selected))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(state)
    return deduped
