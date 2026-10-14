#!/usr/bin/env python3
"""Scheduled, idempotent sync for Nostos. Uses only Python's standard library."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_json(name, fallback):
    path = DATA / name
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(name, value):
    path = DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def request(url, data=None, headers=None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    if headers:
        request_headers.update(headers)
    body = data
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()


def stable_key(item):
    for field in ("sourceId", "id", "url", "link"):
        value = item.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    title = item.get("title", "").strip().casefold()
    year = item.get("year", "")
    return f"title:{title}:{year}"


def merge_preserving_personal_fields(existing, incoming, key_fields=None):
    """Merge upstream facts without overwriting a user's tier, note, or local choices."""
    old_by_key = {stable_key(item): item for item in existing if isinstance(item, dict)}
    # Alias by canonical URL/id helps when the feed's title or year formatting changes.
    result = []
    seen = set()
    for fresh in incoming:
        old = old_by_key.get(stable_key(fresh), {})
        merged = dict(old)
        merged.update({k: v for k, v in fresh.items() if v not in (None, "")})
        for field in ("tier", "note", "review", "personalNote", "palette", "color", "ink", "shape"):
            if old.get(field) not in (None, ""):
                merged[field] = old[field]
        key = stable_key(merged)
        if key not in seen:
            result.append(merged)
            seen.add(key)
    # Keep previously imported history that isn't in a limited upstream feed.
    for old in existing:
        if not isinstance(old, dict):
            continue
        key = stable_key(old)
        if key not in seen:
            result.append(old)
            seen.add(key)
    return result


def sync_letterboxd():
    username = os.environ.get("LETTERBOXD_USERNAME", "").strip()
    if not username:
        print("Letterboxd skipped: set repository variable LETTERBOXD_USERNAME.")
        return
    username = username.lstrip("@").strip("/")
    encoded = urllib.parse.quote(username)
    feeds = [
        (f"https://letterboxd.com/{encoded}/rss/", "items", False),
        (f"https://letterboxd.com/{encoded}/watchlist/rss/", "watchlist", True),
    ]
    current = load_json("films.json", {"items": [], "watchlist": [], "tiers": []})
    current.setdefault("items", [])
    current.setdefault("watchlist", [])
    changed = False
    for feed_url, destination, is_watchlist in feeds:
        try:
            xml_bytes = request(feed_url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
            root = ET.fromstring(xml_bytes)
        except Exception as exc:
            print(f"Letterboxd feed unavailable ({feed_url}): {exc}", file=sys.stderr)
            continue
        channel = root.find("channel")
        if channel is None:
            print(f"Letterboxd feed had no RSS channel ({feed_url}); leaving that collection untouched.", file=sys.stderr)
            continue
        entries = []
        for node in channel.findall("item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            description = (node.findtext("description") or "").strip()
            pub_date = (node.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            year_match = re.search(r"\b(18|19|20)\d{2}\b", title)
            year = int(year_match.group(0)) if year_match else None
            slug_match = re.search(r"letterboxd\.com/film/([^/]+)", link)
            source_id = slug_match.group(1) if slug_match else link.rstrip("/").split("/")[-1]
            image_match = re.search(r"""<img[^>]+src=["']([^"']+)["']""", description, flags=re.IGNORECASE)
            poster_url = image_match.group(1) if image_match else None
            entries.append({
                "source": "letterboxd", "sourceId": source_id, "title": title,
                "year": year, "url": link, "loggedAt": pub_date, "posterUrl": poster_url,
                "feedDescription": re.sub(r"<[^>]+>", " ", description).strip(),
                "watchlist": is_watchlist,
                "kindLabel": "WATCHLIST" if is_watchlist else "LETTERBOXD"
            })
        if entries:
            current[destination] = merge_preserving_personal_fields(current[destination], entries)
            print(f"Letterboxd {destination}: merged {len(entries)} feed entries; total {len(current[destination])}.")
            changed = True
        else:
            print(f"Letterboxd {destination}: no feed entries returned; existing data preserved.")
    if changed:
        current["lastSyncedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_json("films.json", current)


def anilist_query(username, chunk):
    query = """query ($name: String, $chunk: Int, $perChunk: Int) {
      MediaListCollection(userName: $name, type: ANIME, chunk: $chunk, perChunk: $perChunk) {
        hasNextChunk
        lists {
          name
          entries {
            id status score progress repeat
            notes
            media {
              id type format episodes
              title { english romaji native }
              coverImage { large }
              startDate { year }
              siteUrl
            }
          }
        }
      }
    }"""
    payload = json.dumps({"query": query, "variables": {"name": username, "chunk": chunk, "perChunk": 500}}).encode("utf-8")
    raw = request("https://graphql.anilist.co", payload, {"Content-Type": "application/json", "Accept": "application/json"})
    response = json.loads(raw.decode("utf-8"))
    if response.get("errors"):
        raise RuntimeError("AniList API returned errors: " + json.dumps(response["errors"])[:500])
    return response.get("data", {}).get("MediaListCollection")


def sync_anilist():
    username = os.environ.get("ANILIST_USERNAME", "").strip()
    if not username:
        print("AniList skipped: set repository variable ANILIST_USERNAME.")
        return
    try:
        entries = []
        chunk = 1
        while True:
            collection = anilist_query(username, chunk)
            if collection is None:
                raise RuntimeError("AniList returned no collection. Check that the username is public and correct.")
            page_entries = []
            for group in collection.get("lists", []):
                for entry in group.get("entries", []):
                    media = entry.get("media") or {}
                    title_data = media.get("title") or {}
                    title = title_data.get("english") or title_data.get("romaji") or title_data.get("native") or "Untitled anime"
                    status = entry.get("status", "")
                    media_id = media.get("id")
                    page_entries.append({
                        "source": "anilist", "sourceId": media_id, "anilistEntryId": entry.get("id"),
                        "title": title, "nativeTitle": title_data.get("native"),
                        "year": (media.get("startDate") or {}).get("year"),
                        "url": media.get("siteUrl"), "coverImage": (media.get("coverImage") or {}).get("large"),
                        "status": status.replace("_", " ").title(), "statusCode": status,
                        "score": entry.get("score"), "progress": entry.get("progress"),
                        "episodes": media.get("episodes"), "format": media.get("format"),
                        "note": entry.get("notes") or "", "kindLabel": "ANILIST"
                    })
            entries.extend(page_entries)
            if not collection.get("hasNextChunk", False):
                break
            chunk += 1
            if chunk > 100:
                raise RuntimeError("Safety stop: AniList pagination exceeded 100 pages.")
            time.sleep(0.3)
        if not entries:
            print("AniList returned an empty list; writing an empty synced collection.")
        current = load_json("anime.json", {"watched": [], "watchlist": []})
        old_all = (current.get("watched") or []) + (current.get("watchlist") or [])
        merged = merge_preserving_personal_fields(old_all, entries)
        watched_statuses = {"COMPLETED", "CURRENT", "REPEATING", "PAUSED", "DROPPED"}
        watched = [item for item in merged if item.get("statusCode") in watched_statuses or (item.get("source") != "anilist" and not item.get("watchlist"))]
        watchlist = [item for item in merged if item.get("statusCode") == "PLANNING" or item.get("watchlist") is True]
        current["watched"] = watched
        current["watchlist"] = watchlist
        current["lastSyncedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_json("anime.json", current)
        print(f"AniList: synced {len(entries)} entries ({len(watched)} non-planning, {len(watchlist)} planning).")
    except Exception as exc:
        print(f"AniList sync failed: {exc}", file=sys.stderr)


def main():
    sync_letterboxd()
    sync_anilist()


if __name__ == "__main__":
    main()
    
