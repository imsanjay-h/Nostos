#!/usr/bin/env python3
"""Sync the authenticated user's Hardcover library into Nostos data/books.json."""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ENDPOINT = "https://api.hardcover.app/v1/graphql"
QUERY = r'''query NostosMyLibrary {
  me {
    id
    username
    user_books {
      id
      rating
      status_id
      book {
        id
        title
        slug
        image { url }
        contributions { author { name } }
      }
    }
  }
}'''


def fetch_library(token):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"query": QUERY}).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Nostos-Hardcover-Sync/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Hardcover API returned HTTP {exc.code}: {detail}") from exc
    if payload.get("errors"):
        raise RuntimeError("Hardcover GraphQL error: " + json.dumps(payload["errors"])[:700])
    me = (payload.get("data") or {}).get("me")
    if isinstance(me, list):
        me = me[0] if me else None
    if not me:
        raise RuntimeError("Hardcover returned no authenticated user. Check the token.")
    if "user_books" not in me:
        raise RuntimeError("Hardcover response did not include user_books; keeping existing books.json unchanged.")
    return me, me.get("user_books") or []


def clean_entry(entry):
    book = entry.get("book") or {}
    title = (book.get("title") or "").strip()
    if not title:
        return None
    # Hardcover exposes the library status as status_id on user_books.
    # IDs: 1=Want to Read, 2=Currently Reading, 3=Read, 4=Paused, 5=DNF, 6=Ignored.
    status_ids = {
        1: "wantToRead", 2: "currentlyReading", 3: "read",
        4: "didNotFinish", 5: "didNotFinish", 6: "ignored",
    }
    try:
        status_id = int(entry.get("status_id"))
    except (TypeError, ValueError):
        status_id = 1
    shelf = status_ids.get(status_id, "wantToRead")
    if shelf == "ignored":
        return None
    authors = []
    for contribution in book.get("contributions") or []:
        author = contribution.get("author") or {}
        if author.get("name") and author["name"] not in authors:
            authors.append(author["name"])
    image = book.get("image")
    if isinstance(image, dict):
        image = image.get("url")
    try:
        rating = float(entry["rating"]) if entry.get("rating") not in (None, "") else None
    except (TypeError, ValueError):
        rating = None
    return {
        "source": "hardcover", "sourceId": book.get("id"), "userBookId": entry.get("id"),
        "title": title, "author": ", ".join(authors), "coverUrl": image or "",
        "url": ("https://hardcover.app/books/" + str(book.get("slug"))) if book.get("slug") else "",
        "status": shelf, "statusId": status_id, "rating": rating,
    }


def main():
    token = os.environ.get("HARDCOVER_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HARDCOVER_API_TOKEN secret is missing; existing books.json was not changed.")
    me, raw_books = fetch_library(token)
    if not raw_books:
        raise RuntimeError("Hardcover returned an empty library. To avoid accidentally clearing the page, existing books.json was preserved.")
    mapped = [item for entry in raw_books if (item := clean_entry(entry))]
    if not mapped:
        raise RuntimeError("No usable book entries were returned; existing books.json was preserved.")
    result = {
        "source": "hardcover", "username": me.get("username", ""),
        "lastSyncedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "read": [b for b in mapped if b["status"] == "read"],
        "currentlyReading": [b for b in mapped if b["status"] == "currentlyReading"],
        "wantToRead": [b for b in mapped if b["status"] == "wantToRead"],
        "didNotFinish": [b for b in mapped if b["status"] == "didNotFinish"],
    }
    os.makedirs("data", exist_ok=True)
    path = "data/books.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Hardcover: synced {len(mapped)} books for @{result['username']} — {len(result['read'])} read, {len(result['currentlyReading'])} currently reading, {len(result['wantToRead'])} want to read, {len(result['didNotFinish'])} paused/DNF.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Hardcover sync failed: {exc}", file=sys.stderr)
        sys.exit(1)
