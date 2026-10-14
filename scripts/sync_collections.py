#!/usr/bin/env python3
"""Scheduled, idempotent sync for Nostos. Uses only Python's standard library."""
import json
from html.parser import HTMLParser
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
USER_AGENT = "NostosCollectionSync/1.0 (+https://github.com/)"


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
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
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


class WatchlistHTMLParser(HTMLParser):
    """Extract film cards from Letterboxd HTML across common poster markup variants."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.films = {}
        self.stack = []
        self.next_page = False
        self.film_markers = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href", "") or ""
        slug_match = re.search(r"/film/([^/?#]+)/?", href)
        slug = attrs.get("data-film-slug") or (slug_match.group(1) if slug_match else None)
        if slug:
            self.film_markers += 1
            record = self.films.setdefault(slug, {
                "href": urllib.parse.urljoin("https://letterboxd.com", href) if slug_match else f"https://letterboxd.com/film/{slug}/",
                "slug": slug, "title": "", "poster": None
            })
            title = attrs.get("data-film-name") or attrs.get("title") or attrs.get("aria-label")
            if title and not record["title"]:
                record["title"] = title.strip()
            if slug_match:
                record["href"] = urllib.parse.urljoin("https://letterboxd.com", href)
            self.stack.append((tag, slug))
        else:
            self.stack.append((tag, None))

        if tag == "img":
            poster = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original") or attrs.get("data-lazy-src")
            alt = (attrs.get("alt") or "").strip()
            # The poster image is often nested under a film-poster element rather than its link.
            for _, active_slug in reversed(self.stack[:-1]):
                if active_slug:
                    record = self.films[active_slug]
                    if poster and not record.get("poster"):
                        record["poster"] = urllib.parse.urljoin("https://letterboxd.com", poster)
                    if alt and not record.get("title") and alt.lower() not in ("poster", "film poster"):
                        record["title"] = alt
                    break

        if re.search(r"/watchlist/page/\d+/?", href) and ("next" in attrs.get("class", "").lower() or attrs.get("rel") == "next"):
            self.next_page = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def entries(self):
        result = []
        for film in self.films.values():
            title = (film.get("title") or "").strip()
            if title:
                result.append({**film, "display_title": title})
        return result

def merge_current_collection(existing, incoming):
    """Refresh a live collection, retaining user-authored fields for films still present."""
    old_by_key = {stable_key(item): item for item in existing if isinstance(item, dict)}
    result, seen = [], set()
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
    return result


def fetch_letterboxd_watchlist(username):
    """Read the public HTML watchlist; fail closed so blocked/changed pages never erase data."""
    all_entries = []
    for page in range(1, 101):
        if page == 1:
            url = f"https://letterboxd.com/{urllib.parse.quote(username)}/watchlist/"
        else:
            url = f"https://letterboxd.com/{urllib.parse.quote(username)}/watchlist/page/{page}/"
        html = request(url, headers={"Accept": "text/html,application/xhtml+xml"}).decode("utf-8", errors="replace")
        parser = WatchlistHTMLParser()
        parser.feed(html)
        page_entries = []
        for film in parser.entries():
            title = re.sub(r"\s+", " ", film["display_title"]).strip()
            year_match = re.search(r"(?:\(|,\s*)(18|19|20)\d{2}\)?", title)
            year = int(year_match.group(0).strip(" (,)")[-4:]) if year_match else None
            # Prefer a clean film name from Letterboxd's data attributes; otherwise remove poster year suffix.
            clean_title = re.sub(r"\s*\((?:18|19|20)\d{2}\)\s*$", "", title).strip()
            clean_title = re.sub(r",\s*(?:18|19|20)\d{2}.*$", "", clean_title).strip()
            page_entries.append({
                "source": "letterboxd", "sourceId": film["slug"], "title": clean_title or title,
                "year": year, "url": film["href"], "posterUrl": film.get("poster"),
                "watchlist": True, "kindLabel": "WATCHLIST"
            })
        if not page_entries:
            if page == 1:
                page_title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
                page_title = re.sub(r"\s+", " ", page_title_match.group(1)).strip() if page_title_match else "(no HTML title)"
                markers = len(re.findall(r"data-film-slug=|href=[\"'](?:https?://letterboxd\.com)?/film/", html, flags=re.IGNORECASE))
                raise RuntimeError(f"public watchlist page yielded no titled films (HTML title: {page_title!r}; film markers: {markers}; parser markers: {parser.film_markers}); preserving existing watchlist")
            break
        all_entries.extend(page_entries)
        # Continue while a full poster page is present; an empty next page ends pagination safely.
        if len(page_entries) < 20:
            break
        time.sleep(0.25)
    if len(all_entries) >= 2000:
        raise RuntimeError("watchlist pagination safety limit reached; preserving existing watchlist")
    return all_entries


def sync_letterboxd():
    username = os.environ.get("LETTERBOXD_USERNAME", "").strip()
    if not username:
        print("Letterboxd skipped: set repository variable LETTERBOXD_USERNAME.")
        return
    username = username.lstrip("@").strip("/")
    encoded = urllib.parse.quote(username)
    current = load_json("films.json", {"items": [], "watchlist": [], "tiers": []})
    current.setdefault("items", [])
    current.setdefault("watchlist", [])
    changed = False

    # Diary RSS is the supported Letterboxd feed for logged activity.
    feed_url = f"https://letterboxd.com/{encoded}/rss/"
    try:
        xml_bytes = request(feed_url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        if channel is None:
            raise RuntimeError("RSS response had no channel")
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
            image_match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", description, flags=re.IGNORECASE)
            poster_url = image_match.group(1) if image_match else None
            entries.append({
                "source": "letterboxd", "sourceId": source_id, "title": title,
                "year": year, "url": link, "loggedAt": pub_date, "posterUrl": poster_url,
                "feedDescription": re.sub(r"<[^>]+>", " ", description).strip(),
                "watchlist": False, "kindLabel": "LETTERBOXD"
            })
        if entries:
            current["items"] = merge_preserving_personal_fields(current["items"], entries)
            print(f"Letterboxd diary RSS: merged {len(entries)} entries; total {len(current['items'])}.")
            changed = True
        else:
            print("Letterboxd diary RSS returned no entries; existing diary preserved.")
    except Exception as exc:
        print(f"Letterboxd diary RSS unavailable ({feed_url}): {exc}", file=sys.stderr)

    # There is no documented watchlist RSS feed, so read the public HTML page instead.
    try:
        watchlist_entries = fetch_letterboxd_watchlist(username)
        if not watchlist_entries:
            raise RuntimeError("no watchlist entries returned; preserving existing watchlist")
        current["watchlist"] = merge_current_collection(current["watchlist"], watchlist_entries)
        print(f"Letterboxd public watchlist: synced {len(watchlist_entries)} films; total {len(current['watchlist'])}.")
        changed = True
    except Exception as exc:
        print(f"Letterboxd watchlist unavailable; existing watchlist preserved: {exc}", file=sys.stderr)
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
