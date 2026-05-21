from __future__ import annotations

import csv
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: python scripts/merge_offers.py output.csv input1.csv input2.csv ...")
        return 2
    output_path = Path(argv[0])
    input_paths = [Path(arg) for arg in argv[1:]]
    rows = []
    fieldnames = None
    seen = set()
    for path in input_paths:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if fieldnames is None:
                fieldnames = reader.fieldnames
            for row in reader:
                key = row.get("listing_url") or "|".join(row.get(name, "") for name in fieldnames or [])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {output_path}")
    print(f"Merged {len(rows)} unique offer(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

