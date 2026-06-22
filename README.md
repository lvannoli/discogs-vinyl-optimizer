# Discogs Vinyl Optimizer

Discogs Vinyl Optimizer finds UK vinyl marketplace offers for a list of albums and builds ranked purchase options that minimize the estimated total cost of records plus shipping.

The app is designed for a London/UK buyer. It only considers vinyl listings that:

- ship from the United Kingdom;
- are in `Mint (M)`, `Near Mint (NM or M-)`, or `Very Good Plus (VG+)` media condition;
- match the requested artist and album title after normalization;
- expose price, shipping, seller rating, review count, and listing URL.

## What It Does

Given a list such as:

```text
Dave Brubeck - Time Out
Charles Mingus - Mingus Ah Um
The Beatles - Revolver
Nirvana - Nevermind
```

the optimizer:

1. Normalizes the input album list.
2. Resolves exact Discogs release/master candidates using read-only Discogs catalog requests.
3. Scrapes matching Discogs marketplace pages for UK vinyl offers.
4. Rejects marketplace rows whose real Discogs listing title does not match the requested artist and album.
5. Computes ranked purchase bundles while counting shipping once per seller.
6. Writes HTML, JSON, CSV, and audit outputs.

The main output is `purchase_options.html`, a human-readable report with seller ratings, review counts, item prices, shipping estimates, listing links, and percentage comparisons between purchase options.

## Safety

This project does not buy anything and does not modify your Discogs account.

It does not:

- add items to cart;
- create orders;
- update your profile;
- edit your collection or wantlist;
- call write/action API endpoints.

The default workflow uses only read operations: Discogs catalog GET requests plus public marketplace page scraping.

## Accuracy Model

The optimizer does not trust broad Discogs text search results directly.

For each requested album it first resolves exact Discogs release/master candidates, then keeps only marketplace listings whose real listing title matches the requested artist and album after normalizing:

- case;
- accented characters in artist or album names;
- punctuation;
- Discogs artist suffixes such as `(2)`;
- Discogs format suffixes such as `(LP, Album, RE)`.

`offers_scraped.csv` includes a `listing_title` column. The audit fails if an available `listing_title` does not match the requested artist and album.

## Shipping Model

Discogs calculates final shipping in the checkout flow, but this app does not enter the checkout flow.

The optimizer therefore estimates shipping as follows:

- for each selected seller, shipping is counted once;
- if multiple records are selected from the same seller, the seller shipping cost is the highest shipping value among those selected listings;
- per-album shipping shown in the report is an allocation for readability only.

This makes the benefit of buying several records from the same seller visible without inventing seller-specific shipping rules.

## Requirements

- Python 3.11 or newer.
- No required third-party Python packages.
- Optional Discogs user token in `DISCOGS_USER_TOKEN`.

The default scraping workflow can run without a token. A token can help catalog API rate limits, but it is not required for normal use.

## Quick Start

From the project directory:

```powershell
cd "C:\Users\LeonardoVannoli\OneDrive - Asite Solutions Ltd\Documents\discogs-vinyl-optimizer"
python .\discogs_shortcut.py
```

Paste one album per line:

```text
Artist - Album
Artist - Album
```

Submit an empty line to start the search.

## Non-Interactive Usage

Run from pasted text:

```powershell
python .\discogs_shortcut.py --input-text "The Beatles - Revolver`nNirvana - Nevermind" --out-dir .\outputs\my_run
```

Run from a file:

```powershell
python .\discogs_shortcut.py --input-file "C:\path\albums.xlsx" --out-dir .\outputs\my_run
```

Supported input files:

- `.csv`
- `.xlsx`
- `.docx`
- `.txt`

CSV and Excel files must contain at least:

```csv
artist,album
The Beatles,Revolver
Nirvana,Nevermind
```

You may also provide `release_id` to force a specific Discogs release:

```csv
artist,album,release_id
The Beatles,Revolver,1011994
```

## Codex Shortcut

This repository is also wired into a local Codex skill.

In Codex, you can run:

```text
$discogs look for this list
Artist - Album
Artist - Album
```

Codex will run `discogs_shortcut.py`, generate the reports, and return the output file paths.

## Output Files

Each run creates a folder under `outputs/` unless `--out-dir` is provided.

Typical files:

| File | Purpose |
| --- | --- |
| `albums.csv` | Normalized input album list. |
| `offers_scraped.csv` | All eligible scraped offers, including real Discogs `listing_title`. |
| `purchase_options.html` | Main human-readable purchase report. |
| `purchase_options.json` | Structured purchase options. |
| `audit_report.html` | Human-readable audit report. |
| `audit_report.json` | Structured audit result. |
| `discogs_results_email.eml` | Optional email draft with attachments. |

## Email Drafts

The easiest email workflow does not require SMTP configuration.

Create a local `.eml` draft with `purchase_options.json` and `offers_scraped.csv` attached:

```powershell
python .\discogs_shortcut.py --input-file "C:\path\albums.xlsx" --email-draft --email-to "recipient@example.com"
```

Open the generated `discogs_results_email.eml` in your mail client and send it manually.

SMTP sending also exists, but it is optional:

```powershell
python .\discogs_shortcut.py --input-file "C:\path\albums.xlsx" --email-results --email-to "recipient@example.com"
```

SMTP environment variables:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_FROM=sender@example.com
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your_smtp_password
SMTP_STARTTLS=true
```

If SMTP is missing, `--email-results` falls back to writing `discogs_results_email.eml`.

## Main Options

```text
--input-file PATH              CSV, TXT, XLSX, or DOCX input file.
--input-text TEXT              Pasted album list, one "Artist - Album" per line.
--out-dir PATH                 Output directory.
--top N                        Number of purchase options to write. Default: 10.
--pages-per-condition N        Marketplace pages to scrape per condition. Default: 1.
--per-album N                  Catalog candidates to inspect per album. Default: 25.
--max-release-candidates N     Exact release/master candidates used per album. Default: 3.
--max-offers-per-album N       Offer cap per album before optimization. Default: 12.
--beam-width N                 Optimization beam width. Default: 5000.
--email-draft                  Write an .eml email draft with attachments.
--email-results                Try SMTP email, fallback to .eml draft if SMTP is missing.
--email-to ADDRESS             Recipient for email or draft.
```

## Advanced CLI

The package also exposes lower-level commands through `run.py`:

```powershell
python .\run.py search --albums .\examples\albums.example.csv --out-dir .\outputs
python .\run.py optimize --albums .\examples\albums.mock.csv --offers .\examples\offers.mock.csv --out-dir .\outputs --top 3 --no-enrich-sellers
python .\run.py audit --albums .\outputs\my_run\albums.csv --offers .\outputs\my_run\offers_scraped.csv --options .\outputs\my_run\purchase_options.json --out-dir .\outputs\my_run
```

The `api-sellers` mode still exists for experiments with seller inventory endpoints, but it is not the recommended workflow. It is slower and requires a seller watchlist plus a Discogs user token.

Long `api-sellers` runs write `inventory_checkpoint.json` inside the output directory and print seller-by-seller progress. If a run is interrupted, rerun the same command with the same `--out-dir` to resume completed sellers from the checkpoint.

## Token Configuration

Optional:

```powershell
[Environment]::SetEnvironmentVariable("DISCOGS_USER_TOKEN", "your_token_here", "User")
```

The token is read locally. It is not printed and should not be committed.

`config.example.env` documents optional environment variables. Real `.env` files are ignored by `.gitignore`.

## Testing

Run the test suite:

```powershell
python -B -m unittest discover -s tests
```

The `-B` flag avoids writing extra Python cache files.

## Limitations

- Discogs may return HTTP 403 or Cloudflare challenges for some marketplace pages.
- Shipping is an estimate because this app does not enter checkout.
- Marketplace pages can change structure; tests cover the parser, but scraping may need maintenance if Discogs changes its HTML.
- The app returns listing links, not cart-add links. Adding to cart would be an account action and is intentionally out of scope.

## Repository Hygiene

Generated files are ignored:

- `outputs/`
- `__pycache__/`
- `.env`
- `tests/tmp*/`

For a clean GitHub push, keep source code, tests, examples, and documentation; do not commit generated run outputs or credentials.
