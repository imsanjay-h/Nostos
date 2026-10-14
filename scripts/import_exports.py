#!/usr/bin/env python3
"""Import common Letterboxd and Goodreads CSV exports into Nostos JSON data files.

Examples:
  python scripts/import_exports.py --letterboxd-diary diary.csv --letterboxd-watchlist watchlist.csv
  python scripts/import_exports.py --goodreads goodreads_library_export.csv
  python scripts/import_exports.py --letterboxd-diary diary.csv --letterboxd-watchlist watchlist.csv --goodreads goodreads_library_export.csv

Existing personal tier assignments and notes are preserved where IDs/URLs match.
"""
import argparse
import csv
import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(name, fallback):
    path = DATA / name
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return fallback


def save(name, value):
    with (DATA / name).open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def key(item):
    for field in ("sourceId", "id", "url", "link"):
        if item.get(field) not in (None, ""):
            return f"{field}:{item[field]}"
    return f"title:{item.get('title','').casefold()}:{item.get('year','')}"


def merge(old, incoming):
    by_key = {key(item): item for item in old if isinstance(item, dict)}
    result, seen = [], set()
    for fresh in incoming:
        previous = by_key.get(key(fresh), {})
        merged = dict(previous)
        merged.update({k: v for k, v in fresh.items() if v not in (None, "")})
        for field in ("tier", "note", "review", "personalNote", "palette", "color", "ink", "shape"):
            if previous.get(field) not in (None, ""):
                merged[field] = previous[field]
        k = key(merged)
        if k not in seen:
            result.append(merged); seen.add(k)
    for item in old:
        k = key(item)
        if k not in seen:
            result.append(item); seen.add(k)
    return result


def import_letterboxd(diary_path, watchlist_path):
    current = load("films.json", {"items": [], "watchlist": [], "tiers": []})
    diary = []
    if diary_path:
        for row in rows(diary_path):
            title = (row.get("Name") or row.get("Title") or "").strip()
            if not title: continue
            uri = (row.get("Letterboxd URI") or row.get("URI") or row.get("URL") or "").strip()
            year = row.get("Year", "").strip()
            rating = (row.get("Rating") or "").strip()
            diary.append({"source":"letterboxd", "sourceId":uri.rstrip("/").split("/")[-1] if uri else f"{title}-{year}",
                          "title":title, "year":int(year) if year.isdigit() else None, "url":uri,
                          "loggedAt":(row.get("Watched Date") or row.get("Date") or "").strip(),
                          "rating":rating, "tags":(row.get("Tags") or "").strip(), "kindLabel":"LETTERBOXD"})
    watch = []
    if watchlist_path:
        for row in rows(watchlist_path):
            title = (row.get("Name") or row.get("Title") or "").strip()
            if not title: continue
            uri = (row.get("Letterboxd URI") or row.get("URI") or row.get("URL") or "").strip()
            year = row.get("Year", "").strip()
            watch.append({"source":"letterboxd", "sourceId":uri.rstrip("/").split("/")[-1] if uri else f"{title}-{year}",
                          "title":title, "year":int(year) if year.isdigit() else None, "url":uri,
                          "watchlist":True, "kindLabel":"WATCHLIST"})
    current["items"] = merge(current.get("items", []), diary)
    current["watchlist"] = merge(current.get("watchlist", []), watch)
    current["lastImportedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save("films.json", current)
    print(f"Imported/merged {len(diary)} Letterboxd diary rows and {len(watch)} watchlist rows.")


def import_goodreads(path):
    data = load("books.json", {"read": [], "currentlyReading": [], "wantToRead": []})
    read_items, current_items, wanted_items = [], [], []
    for row in rows(path):
        title = (row.get("Title") or "").strip()
        if not title: continue
        author = (row.get("Author") or "").strip()
        shelf = (row.get("Exclusive Shelf") or row.get("Bookshelves") or "").strip().lower()
        isbn = re.sub(r"[^0-9Xx]", "", row.get("ISBN13") or row.get("ISBN") or "")
        item = {"source":"goodreads", "sourceId":isbn or f"{title.casefold()}-{author.casefold()}", "title":title,
                "author":author, "year":(row.get("Original Publication Year") or row.get("Year Published") or "").strip(),
                "url":(row.get("Book Id") or "").strip(), "rating":(row.get("My Rating") or "").strip(),
                "note":(row.get("My Review") or "").strip(), "kindLabel":"GOODREADS"}
        if shelf in {"currently-reading", "currently_reading", "currently reading"}:
            current_items.append(item)
        elif shelf in {"to-read", "to_read", "want-to-read", "want_to_read", "to read"}:
            wanted_items.append(item)
        else:
            read_items.append(item)
    data["read"] = merge(data.get("read", []), read_items)
    data["currentlyReading"] = merge(data.get("currentlyReading", []), current_items)
    data["wantToRead"] = merge(data.get("wantToRead", []), wanted_items)
    data["lastImportedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save("books.json", data)
    print(f"Imported/merged {len(read_items)} read, {len(current_items)} currently-reading, and {len(wanted_items)} to-read Goodreads rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--letterboxd-diary", help="Letterboxd diary.csv export")
    parser.add_argument("--letterboxd-watchlist", help="Letterboxd watchlist.csv export")
    parser.add_argument("--goodreads", help="Goodreads library CSV export")
    args = parser.parse_args()
    if not any((args.letterboxd_diary, args.letterboxd_watchlist, args.goodreads)):
        parser.error("Supply at least one export file argument.")
    if args.letterboxd_diary or args.letterboxd_watchlist:
        import_letterboxd(args.letterboxd_diary, args.letterboxd_watchlist)
    if args.goodreads:
        import_goodreads(args.goodreads)

if __name__ == "__main__":
    main()
