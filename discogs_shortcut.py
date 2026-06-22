from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discogs_vinyl_optimizer.input_parser import (
    albums_from_chat_text,
    albums_from_file,
    known_album_correction,
    write_albums_csv,
)
from discogs_vinyl_optimizer.catalog import search_release_suggestions, search_releases
from discogs_vinyl_optimizer.http_client import DiscogsClient, DiscogsHttpError
from discogs_vinyl_optimizer.inventory_api import InventorySearchProgress, search_seller_inventory_offers
from discogs_vinyl_optimizer.io import write_offers_csv
from discogs_vinyl_optimizer.marketplace_scraper import ScrapeResult, scrape_marketplace_offers
from discogs_vinyl_optimizer.matching import (
    normalise_artist_match_text,
    normalise_match_text,
    split_artist_album_display,
    strip_discogs_format_suffix,
    title_matches_artist_album,
)
from discogs_vinyl_optimizer.models import AlbumRequest
from discogs_vinyl_optimizer.optimizer import OptimisationError, optimise_purchases
from discogs_vinyl_optimizer.reports import write_options_html, write_options_json
from discogs_vinyl_optimizer.audit import audit_purchase_outputs, write_audit_html, write_audit_json
from discogs_vinyl_optimizer.seller_watchlist import read_seller_watchlist
from discogs_vinyl_optimizer.spelling import SpellingSuggestion, suggest_album_correction
from discogs_vinyl_optimizer.emailer import (
    DEFAULT_RESULTS_EMAIL,
    EmailError,
    send_results_email,
    write_results_email_draft,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Interactive Discogs vinyl shortcut.")
    parser.add_argument("--input-file", help="CSV, TXT, XLSX, or DOCX input file.")
    parser.add_argument("--input-text", help="Pasted list text, using 'Artist - Album' per line.")
    parser.add_argument("--out-dir", help="Output directory. Defaults to outputs/shortcut_<timestamp>.")
    parser.add_argument("--mode", choices=("scrape", "api-sellers"), default="scrape")
    parser.add_argument("--seller-watchlist", default=str(ROOT / "data" / "seller_watchlist.csv"))
    parser.add_argument("--seller-limit", type=int, default=100)
    parser.add_argument("--min-seller-rating", default="99.00")
    parser.add_argument("--min-seller-reviews", type=int, default=500)
    parser.add_argument("--per-query", type=int, default=10)
    parser.add_argument("--max-pages-per-query", type=int, default=1)
    parser.add_argument("--token-env", default="DISCOGS_USER_TOKEN")
    parser.add_argument("--api-delay-seconds", type=float, default=1.5)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--pages-per-condition", type=int, default=1)
    parser.add_argument("--per-album", type=int, default=25)
    parser.add_argument("--max-release-candidates", type=int, default=3)
    parser.add_argument("--max-offers-per-album", type=int, default=12)
    parser.add_argument("--beam-width", type=int, default=5000)
    parser.add_argument("--user-agent", default="Mozilla/5.0 DiscogsVinylOptimizer/0.1")
    parser.add_argument("--email-results", action="store_true", help="Email purchase_options.json and offers CSV after a successful run.")
    parser.add_argument("--email-draft", action="store_true", help="Write an .eml email draft with purchase_options.json and offers CSV attached.")
    parser.add_argument("--email-to", help=f"Email recipient. Defaults to DISCOGS_EMAIL_TO or {DEFAULT_RESULTS_EMAIL} when --email-results is used.")
    args = parser.parse_args()

    try:
        albums = _load_albums(args.input_file, args.input_text)
        albums = _confirm_spelling_corrections(albums, args)
        out_dir = Path(args.out_dir) if args.out_dir else ROOT / "outputs" / f"shortcut_{datetime.now():%Y%m%d_%H%M%S}"
        out_dir.mkdir(parents=True, exist_ok=True)

        albums_path = out_dir / "albums.csv"
        offers_path = out_dir / ("offers_api.csv" if args.mode == "api-sellers" else "offers_scraped.csv")
        html_path = out_dir / "purchase_options.html"
        json_path = out_dir / "purchase_options.json"
        audit_html_path = out_dir / "audit_report.html"
        audit_json_path = out_dir / "audit_report.json"

        write_albums_csv(albums, albums_path)
        print(f"Wrote {albums_path}")
        if args.mode == "api-sellers":
            print("Querying Discogs seller inventories through authenticated GET API calls.")
            token = os.environ.get(args.token_env)
            if not token:
                raise ValueError(f"{args.token_env} is required for api-sellers mode.")
            sellers = read_seller_watchlist(
                args.seller_watchlist,
                min_rating=_decimal(args.min_seller_rating),
                min_reviews=args.min_seller_reviews,
                limit=args.seller_limit,
            )
            if not sellers:
                raise ValueError("No sellers matched the watchlist thresholds.")
            checkpoint_path = out_dir / "inventory_checkpoint.json"
            print(f"Inventory checkpoint: {checkpoint_path}")
            scrape_result = search_seller_inventory_offers(
                client=DiscogsClient(
                    token=token,
                    user_agent=args.user_agent,
                    min_delay_seconds=args.api_delay_seconds,
                ),
                albums=albums,
                sellers=sellers,
                per_query=args.per_query,
                max_pages_per_query=args.max_pages_per_query,
                catalog_per_album=args.per_album,
                checkpoint_path=checkpoint_path,
                progress_callback=_print_inventory_progress,
            )
            print(f"Queried {len(sellers)} seller(s) from {args.seller_watchlist}.")
        else:
            print("Resolving exact Discogs release candidates with read-only GET catalog search.")
            candidates, candidate_warnings = _exact_release_candidates(albums, args)
            print(f"Found {len(candidates)} exact release candidate(s).")
            print("Scraping exact Discogs release marketplace pages. This can take a few minutes for long lists.")
            scrape_result = scrape_marketplace_offers(
                candidates=candidates,
                pages_per_condition=args.pages_per_condition,
                user_agent=args.user_agent,
            )
            scrape_result = ScrapeResult(
                offers=scrape_result.offers,
                warnings=candidate_warnings + scrape_result.warnings,
            )
        write_offers_csv(scrape_result.offers, offers_path)
        print(f"Wrote {offers_path}")
        print(f"Found {len(scrape_result.offers)} eligible offer(s).")
        for warning in scrape_result.warnings:
            print(f"Warning: {warning}")

        output_warnings = scrape_result.warnings + _missing_offer_warnings(albums, scrape_result.offers)
        options = optimise_purchases(
            albums=albums,
            offers=scrape_result.offers,
            top_n=args.top,
            max_offers_per_album=args.max_offers_per_album,
            beam_width=args.beam_width,
            allow_missing=True,
        )
        write_options_html(options, html_path, warnings=output_warnings)
        write_options_json(options, json_path)
        audit = audit_purchase_outputs(albums_path, offers_path, json_path)
        write_audit_html(audit, audit_html_path)
        write_audit_json(audit, audit_json_path)
        print(f"Wrote {html_path}")
        print(f"Wrote {json_path}")
        print(f"Wrote {audit_html_path}")
        print(f"Wrote {audit_json_path}")
        print("Audit result: " + ("PASS" if audit.passed else "FAIL"))
        print(f"Best option: {options[0].currency} {options[0].total}")
        if (args.email_results or args.email_draft or args.email_to) and audit.passed:
            recipient = args.email_to or os.environ.get("DISCOGS_EMAIL_TO") or DEFAULT_RESULTS_EMAIL
            attachments = [json_path, offers_path]
            if args.email_results:
                try:
                    send_results_email(
                        recipient=recipient,
                        attachments=attachments,
                        run_dir=out_dir,
                    )
                    print(f"Emailed {json_path.name} and {offers_path.name} to {recipient}.")
                except EmailError as exc:
                    draft_path = write_results_email_draft(
                        recipient=recipient,
                        attachments=attachments,
                        run_dir=out_dir,
                    )
                    print(f"SMTP email was not sent: {exc}")
                    print(f"Wrote email draft instead: {draft_path}")
            else:
                draft_path = write_results_email_draft(
                    recipient=recipient,
                    attachments=attachments,
                    run_dir=out_dir,
                )
                print(f"Wrote email draft: {draft_path}")
        elif args.email_results or args.email_draft or args.email_to:
            print("Email not sent because the audit failed.")
        return 0 if audit.passed else 1
    except (FileNotFoundError, ValueError, OptimisationError, EmailError) as exc:
        print(f"Error: {exc}")
        return 1


def _load_albums(input_file: str | None, input_text: str | None):
    if input_file:
        return albums_from_file(input_file, apply_corrections=False)
    if input_text:
        return albums_from_chat_text(input_text, apply_corrections=False)

    first = input("Paste an album list or enter a CSV/XLSX/DOCX/TXT file path: ").strip().strip('"')
    possible_path = Path(first)
    if possible_path.exists():
        return albums_from_file(possible_path, apply_corrections=False)

    lines = [first]
    print("Continue pasting album lines. Submit an empty line to start.")
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line)
    return albums_from_chat_text("\n".join(lines), apply_corrections=False)


def _decimal(value: str):
    from decimal import Decimal

    return Decimal(value)


def _print_inventory_progress(progress: InventorySearchProgress) -> None:
    action = "Skipped" if progress.skipped else "Completed"
    seller_delta = "" if progress.skipped else f", +{progress.seller_offers} offer(s)"
    print(
        f"{action} seller {progress.current_seller}/{progress.total_sellers}: "
        f"{progress.seller}{seller_delta}, {progress.total_offers} total offer(s), "
        f"{progress.warnings} warning(s), elapsed {_format_duration(progress.elapsed_seconds)}",
        flush=True,
    )


def _format_duration(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes}m{seconds:02d}s"


def _confirm_spelling_corrections(albums, args):
    client = DiscogsClient(
        token=os.environ.get(args.token_env),
        user_agent=args.user_agent,
        min_delay_seconds=args.api_delay_seconds,
    )
    corrected_albums = []
    for album in albums:
        known = known_album_correction(album)
        if known is not None:
            print(f"Using corrected spelling: {known.display}")
            corrected_albums.append(known)
            continue
        if album.release_id is not None:
            corrected_albums.append(album)
            continue
        try:
            found = search_releases(client, album, per_album=args.per_album)
        except DiscogsHttpError as exc:
            print(f"Warning: Spelling check skipped for {album.display}: {exc}")
            corrected_albums.append(album)
            continue
        exact = [
            candidate
            for candidate in found
            if title_matches_artist_album(candidate.title, album.artist, album.album)
        ]
        if exact:
            corrected_albums.append(_candidate_album_correction(album, exact) or album)
            continue
        article_correction = _find_artist_article_correction(client, album, args)
        if article_correction is not None:
            print(f"Using corrected artist article: {article_correction.display}")
            corrected_albums.append(article_correction)
            continue
        suggestion = _find_spelling_suggestion(client, album, args)
        if suggestion is None:
            corrected_albums.append(album)
            continue
        print(f"Using corrected spelling: {suggestion.corrected.display}")
        corrected_albums.append(suggestion.corrected)
    return corrected_albums


def _find_artist_article_correction(client: DiscogsClient, album, args) -> AlbumRequest | None:
    for variant in _artist_article_variants(album):
        try:
            found = search_releases(client, variant, per_album=args.per_album)
        except DiscogsHttpError as exc:
            print(f"Warning: Artist article check skipped for {variant.display}: {exc}")
            continue
        exact = [
            candidate
            for candidate in found
            if title_matches_artist_album(candidate.title, variant.artist, variant.album)
        ]
        correction = _candidate_album_correction(album, exact)
        if correction is not None:
            return correction
    return None


def _artist_article_variants(album: AlbumRequest) -> list[AlbumRequest]:
    artist = album.artist.strip()
    if artist.casefold().startswith("the "):
        return [AlbumRequest(artist=artist[4:].strip(), album=album.album, release_id=album.release_id)]
    return [AlbumRequest(artist=f"The {artist}", album=album.album, release_id=album.release_id)]


def _candidate_album_correction(album: AlbumRequest, candidates) -> AlbumRequest | None:
    for candidate in candidates:
        artist, title = split_artist_album_display(candidate.title)
        title = strip_discogs_format_suffix(title)
        if not artist or not title:
            continue
        if normalise_artist_match_text(artist) != normalise_artist_match_text(album.artist):
            continue
        if normalise_match_text(title) != normalise_match_text(album.album):
            continue
        corrected = AlbumRequest(
            artist=_strip_discogs_artist_suffix(artist),
            album=title,
            release_id=album.release_id,
        )
        if corrected != album:
            return corrected
    return None


def _strip_discogs_artist_suffix(value: str) -> str:
    import re

    without_numeric_suffix = re.sub(r"\s*\([0-9]+\)\s*$", "", value)
    return without_numeric_suffix.replace("*", "").strip()


def _find_spelling_suggestion(client: DiscogsClient, album, args) -> SpellingSuggestion | None:
    try:
        suggestions = search_release_suggestions(client, album, per_album=max(args.per_album, 10))
    except DiscogsHttpError as exc:
        print(f"Warning: Spelling suggestions skipped for {album.display}: {exc}")
        return None
    suggestion = suggest_album_correction(album, suggestions)
    if suggestion is not None:
        return suggestion
    album_title_only = AlbumRequest(artist="", album=album.album, release_id=album.release_id)
    try:
        suggestions = search_release_suggestions(client, album_title_only, per_album=max(args.per_album, 50))
    except DiscogsHttpError as exc:
        print(f"Warning: Album-title spelling suggestions skipped for {album.display}: {exc}")
        return None
    return suggest_album_correction(album, suggestions)


def _confirm_or_keep_spelling(suggestion: SpellingSuggestion):
    prompt = (
        f'Suggested corrected spelling for "{suggestion.original.display}": '
        f'"{suggestion.corrected.display}". Apply this correction? [y/N]: '
    )
    try:
        answer = input(prompt)
    except EOFError:
        print(f"No response received; keeping original spelling for {suggestion.original.display}.")
        return suggestion.original
    if answer.strip().casefold() in {"y", "yes"}:
        print(f"Using corrected spelling: {suggestion.corrected.display}")
        return suggestion.corrected
    print(f"Keeping original spelling: {suggestion.original.display}")
    return suggestion.original


def _exact_release_candidates(albums, args):
    client = DiscogsClient(
        token=os.environ.get(args.token_env),
        user_agent=args.user_agent,
        min_delay_seconds=args.api_delay_seconds,
    )
    candidates = []
    warnings = []
    for album in albums:
        try:
            found = search_releases(client, album, per_album=args.per_album)
        except DiscogsHttpError as exc:
            warnings.append(f"No exact release candidates checked for {album.display}: {exc}")
            continue
        exact = [
            candidate
            for candidate in found
            if title_matches_artist_album(candidate.title, album.artist, album.album)
        ]
        if not exact:
            warnings.append(f"No exact Discogs release candidate found for {album.display}.")
            continue
        candidates.extend(_dedupe_marketplace_candidates(exact)[: args.max_release_candidates])
    return candidates, warnings


def _missing_offer_warnings(albums, offers):
    covered = {offer.album_key for offer in offers}
    missing = [album.display for album in albums if album.key not in covered]
    if not missing:
        return []
    return ["No eligible UK VG+/NM/M offers found for: " + "; ".join(missing)]


def _dedupe_marketplace_candidates(candidates):
    deduped = []
    seen = set()
    for candidate in candidates:
        key = ("master", candidate.master_id) if candidate.master_id else ("release", candidate.release_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())
