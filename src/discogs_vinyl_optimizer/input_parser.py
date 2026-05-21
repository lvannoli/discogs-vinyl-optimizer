from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .models import AlbumRequest


SUPPORTED_INPUT_EXTENSIONS = {".csv", ".txt", ".xlsx", ".docx"}

KNOWN_ALBUM_CORRECTIONS = {
    ("dave brubeck", "time out"): ("The Dave Brubeck Quartet", "Time Out"),
    ("genesis", "nursery crime"): ("Genesis", "Nursery Cryme"),
    ("the beatles", "sgt. peppers"): ("The Beatles", "Sgt. Pepper's Lonely Hearts Club Band"),
    ("keith jarrett", "the koln concert"): ("Keith Jarrett", "The Köln Concert"),
}


def albums_from_chat_text(text: str) -> list[AlbumRequest]:
    text = text.strip()
    if not text:
        raise ValueError("No album list provided.")
    if _looks_like_csv(text):
        return _albums_from_csv_lines(text.splitlines(), source="chat CSV")

    albums: list[AlbumRequest] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", line)
        if not match:
            raise ValueError(f"Line {line_number}: expected 'Artist - Album'. Got: {line}")
        albums.append(AlbumRequest(artist=match.group(1).strip(), album=match.group(2).strip()))
    if not albums:
        raise ValueError("No album rows found in pasted text.")
    return apply_known_corrections(albums)


def albums_from_file(path: str | Path) -> list[AlbumRequest]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    suffix = input_path.suffix.casefold()
    if suffix == ".csv":
        return apply_known_corrections(
            _albums_from_csv_lines(input_path.read_text(encoding="utf-8-sig").splitlines(), source=str(input_path))
        )
    if suffix == ".txt":
        return apply_known_corrections(albums_from_chat_text(input_path.read_text(encoding="utf-8-sig")))
    if suffix == ".xlsx":
        return apply_known_corrections(_albums_from_xlsx(input_path))
    if suffix == ".docx":
        return apply_known_corrections(albums_from_chat_text(_text_from_docx(input_path)))
    allowed = ", ".join(sorted(SUPPORTED_INPUT_EXTENSIONS))
    raise ValueError(f"Unsupported input file type '{suffix}'. Supported: {allowed}")


def write_albums_csv(albums: list[AlbumRequest], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["artist", "album", "release_id"])
        writer.writeheader()
        for album in albums:
            writer.writerow(
                {
                    "artist": album.artist,
                    "album": album.album,
                    "release_id": album.release_id or "",
                }
            )


def apply_known_corrections(albums: list[AlbumRequest]) -> list[AlbumRequest]:
    corrected: list[AlbumRequest] = []
    for album in albums:
        key = (_normalise_text(album.artist), _normalise_text(album.album))
        if key in KNOWN_ALBUM_CORRECTIONS:
            artist, title = KNOWN_ALBUM_CORRECTIONS[key]
            corrected.append(AlbumRequest(artist=artist, album=title, release_id=album.release_id))
        else:
            corrected.append(album)
    return corrected


def _looks_like_csv(text: str) -> bool:
    first_line = text.splitlines()[0]
    return "," in first_line and {"artist", "album"}.issubset(
        {header.strip().casefold() for header in first_line.split(",")}
    )


def _albums_from_csv_lines(lines: list[str], source: str) -> list[AlbumRequest]:
    reader = csv.DictReader(lines)
    headers = {_normalise_header(header) for header in (reader.fieldnames or [])}
    missing = {"artist", "album"} - headers
    if missing:
        raise ValueError(f"{source} is missing required column(s): {', '.join(sorted(missing))}")

    albums: list[AlbumRequest] = []
    for row_number, row in enumerate(reader, start=2):
        normalised = {_normalise_header(key): value for key, value in row.items() if key is not None}
        artist = (normalised.get("artist") or "").strip()
        album = (normalised.get("album") or "").strip()
        if not artist or not album:
            raise ValueError(f"{source} row {row_number}: artist and album are required.")
        release_id = _optional_int(normalised.get("release_id"), source, row_number)
        albums.append(AlbumRequest(artist=artist, album=album, release_id=release_id))
    if not albums:
        raise ValueError(f"No album rows found in {source}.")
    return albums


def _albums_from_xlsx(path: Path) -> list[AlbumRequest]:
    with zipfile.ZipFile(path) as archive:
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in archive.namelist():
            raise ValueError(f"{path} does not contain xl/worksheets/sheet1.xml")
        shared_strings = _xlsx_shared_strings(archive)
        rows = _xlsx_rows(archive.read(sheet_name), shared_strings)

    if not rows:
        raise ValueError(f"No rows found in {path}")
    headers = [_normalise_header(value) for value in rows[0]]
    if "artist" not in headers or "album" not in headers:
        raise ValueError(f"{path} is missing required column(s): artist, album")
    artist_index = headers.index("artist")
    album_index = headers.index("album")
    release_index = headers.index("release_id") if "release_id" in headers else None

    albums: list[AlbumRequest] = []
    for row_number, row in enumerate(rows[1:], start=2):
        artist = _cell(row, artist_index)
        album = _cell(row, album_index)
        if not artist and not album:
            continue
        if not artist or not album:
            raise ValueError(f"{path} row {row_number}: artist and album are required.")
        release_id = _optional_int(_cell(row, release_index), str(path), row_number) if release_index is not None else None
        albums.append(AlbumRequest(artist=artist, album=album, release_id=release_id))
    if not albums:
        raise ValueError(f"No album rows found in {path}.")
    return albums


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(".//{*}si"):
        values.append("".join(text.text or "" for text in item.findall(".//{*}t")))
    return values


def _xlsx_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row in root.findall(".//{*}row"):
        values: dict[int, str] = {}
        for cell in row.findall("{*}c"):
            ref = cell.attrib.get("r", "")
            column_index = _column_index(ref)
            values[column_index] = _xlsx_cell_value(cell, shared_strings)
        if values:
            rows.append([values.get(index, "") for index in range(max(values) + 1)])
    return rows


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return " ".join(text.text or "" for text in cell.findall(".//{*}t")).strip()
    value = cell.find("{*}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        index = int(value.text)
        return shared_strings[index] if index < len(shared_strings) else ""
    return value.text.strip()


def _text_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ValueError(f"{path} does not contain word/document.xml")
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    lines: list[str] = []
    for paragraph in root.findall(".//{*}p"):
        text = "".join(node.text or "" for node in paragraph.findall(".//{*}t")).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _column_index(reference: str) -> int:
    letters = re.match(r"^[A-Z]+", reference.upper())
    if not letters:
        return 0
    index = 0
    for char in letters.group(0):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _normalise_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _optional_int(value: str | None, source: str, row_number: int) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{source} row {row_number}: release_id must be an integer.") from exc
