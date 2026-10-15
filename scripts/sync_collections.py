#!/usr/bin/env python3
"""Scheduled, idempotent sync for Nostos. Uses only Python's standard library."""
import json
import difflib
import html as html_lib
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


def merge_current_watchlist(existing, incoming):
    """Refresh the watchlist to match Letterboxd while retaining personal fields on matching films."""
    old_by_key = {stable_key(item): item for item in existing if isinstance(item, dict)}
    result = []
    seen = set()
    personal_fields = ("tier", "note", "review", "personalNote", "palette", "color", "ink", "shape")
    for fresh in incoming:
        old = old_by_key.get(stable_key(fresh), {})
        merged = dict(old)
        merged.update({k: v for k, v in fresh.items() if v not in (None, "")})
        for field in personal_fields:
            if old.get(field) not in (None, ""):
                merged[field] = old[field]
        key = stable_key(merged)
        if key not in seen:
            result.append(merged)
            seen.add(key)
    return result


class WatchlistHTMLParser(HTMLParser):
    """Extract film links from Letterboxd HTML without depending on one CSS class."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.films = {}
        self.current_anchor = None

    @staticmethod
    def attrs_dict(attrs):
        return {key: value for key, value in attrs if key}

    def handle_starttag(self, tag, attrs):
        a = self.attrs_dict(attrs)
        # Letterboxd watchlist cards can expose film identity on a wrapper via
        # data-item-* attributes rather than on the <a href="..."> itself.
        href = a.get("href", "")
        item_link = a.get("data-item-link", "")
        path = href or item_link
        match = re.search(r"/film/([^/?#]+)/?", path)
        slug = (a.get("data-film-slug") or a.get("data-item-slug") or
                (match.group(1) if match else ""))
        if not slug:
            return

        slug = slug.strip("/")
        raw_title = (a.get("data-film-name") or a.get("data-film-title") or
                     a.get("data-item-name") or a.get("aria-label") or
                     a.get("title") or "").strip()
        # Letterboxd's data-item-name commonly includes the release year, e.g.
        # "Por Thozil (2023)". Keep the title clean and retain the year.
        title = re.sub(r"\s*\(((?:18|19|20)\d{2})\)\s*$", "", raw_title).strip()
        year_text = (a.get("data-film-release-year") or a.get("data-film-year") or
                     a.get("data-item-name") or raw_title)
        year_match = re.search(r"\b(18|19|20)\d{2}\b", year_text)
        year = int(year_match.group(0)) if year_match else None
        poster = (a.get("data-poster-url") or a.get("data-image-url") or
                  a.get("data-image") or a.get("data-src") or a.get("src"))
        # Do not save Letterboxd's known empty-poster placeholder as the film art.
        if poster and ("empty-poster" in poster or not poster.startswith(("https://", "http://"))):
            poster = None

        existing = self.films.get(slug, {})
        if title or not existing.get("title"):
            existing["title"] = title or slug.replace("-", " ").title()
        if year:
            existing["year"] = year
        if poster and not existing.get("posterUrl"):
            existing["posterUrl"] = poster
        self.films[slug] = existing
        if tag == "a":
            self.current_anchor = slug

    def handle_endtag(self, tag):
        if tag == "a":
            self.current_anchor = None


def scrape_public_watchlist(username):
    """Read public watchlist pages, stopping safely when pagination ends."""
    all_films = {}
    page = 1
    while page <= 100:
        if page == 1:
            url = f"https://letterboxd.com/{urllib.parse.quote(username)}/watchlist/"
        else:
            url = f"https://letterboxd.com/{urllib.parse.quote(username)}/watchlist/page/{page}/"
        try:
            raw = request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://letterboxd.com/{urllib.parse.quote(username)}/",
            })
        except Exception as exc:
            if page == 1:
                raise RuntimeError(f"could not fetch public watchlist page 1: {exc}") from exc
            print(f"Letterboxd watchlist: pagination stopped at page {page} ({exc}).")
            break
        html = raw.decode("utf-8", errors="replace")
        lowered = html.lower()
        if any(marker in lowered for marker in ("cf-chl-", "just a moment...", "verify you are human", "access denied")):
            if page == 1:
                raise RuntimeError("Letterboxd returned an anti-bot/challenge page to GitHub Actions")
            break
        parser = WatchlistHTMLParser()
        parser.feed(html)
        if not parser.films:
            # A blank later page means pagination has ended; a blank first page
            # is diagnostic and must not erase the existing collection.
            if page == 1:
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                page_title = html_lib.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else "(no title)"
                # Diagnostics are deliberately compact: reveal the HTML structure that
                # GitHub Actions received without dumping the entire page into logs.
                probes = {
                    "literal /film/": r"/film/",
                    "encoded film path": r"(?:%2F|&#0*47;|&sol;)film(?:%2F|&#0*47;|&sol;)",
                    "data-film attributes": r"data-film-[\w-]+",
                    "film-poster marker": r"film-poster",
                    "poster-container marker": r"poster-container",
                    "film slug marker": r"filmSlug|film_slug|film-slug",
                    "JSON-LD script": r"application/ld\+json",
                    "embedded state marker": r"__NEXT_DATA__|__INITIAL_STATE__|__APOLLO_STATE__",
                }
                counts = []
                for label, pattern in probes.items():
                    counts.append(f"{label}={len(re.findall(pattern, html, re.I))}")
                print("Letterboxd watchlist diagnostics: " + "; ".join(counts))
                for marker in ("data-film", "film-poster", "poster-container", "/film/", "watchlist"):
                    match = re.search(re.escape(marker), html, re.I)
                    if match:
                        start = max(0, match.start() - 120)
                        end = min(len(html), match.end() + 220)
                        snippet = re.sub(r"\s+", " ", html[start:end]).strip()
                        print(f"Letterboxd HTML sample [{marker}]: {snippet[:340]}")
                raise RuntimeError(f"no recognised film entries; HTTP page title: {page_title[:120]}; response size: {len(raw)} bytes")
            break
        before = len(all_films)
        all_films.update(parser.films)
        # The first page with no new film links is a safe end condition.
        if len(all_films) == before:
            break
        page += 1
        time.sleep(0.25)
    if page > 100:
        raise RuntimeError("watchlist pagination safety stop after 100 pages")
    return [
        {"source": "letterboxd", "sourceId": slug, "title": film.get("title") or slug.replace("-", " ").title(),
         "year": film.get("year"), "url": f"https://letterboxd.com/film/{slug}/",
         "posterUrl": film.get("posterUrl"), "watchlist": True, "kindLabel": "WATCHLIST"}
        for slug, film in all_films.items()
    ]


def sync_letterboxd():
    username = os.environ.get("LETTERBOXD_USERNAME", "").strip()
    if not username:
        print("Letterboxd skipped: set repository variable LETTERBOXD_USERNAME.")
        return
    username = username.lstrip("@").strip("/")
    current = load_json("films.json", {"items": [], "watchlist": [], "tiers": []})
    current.setdefault("items", [])
    current.setdefault("watchlist", [])
    changed = False

    # Diary remains on its working RSS feed. Do not use the watchlist RSS URL:
    # Letterboxd does not reliably serve it to GitHub Actions.
    feed_url = f"https://letterboxd.com/{urllib.parse.quote(username)}/rss/"
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
            entries.append({"source": "letterboxd", "sourceId": source_id, "title": title,
                            "year": year, "url": link, "loggedAt": pub_date, "posterUrl": poster_url,
                            "feedDescription": re.sub(r"<[^>]+>", " ", description).strip(),
                            "watchlist": False, "kindLabel": "LETTERBOXD"})
        if entries:
            current["items"] = merge_preserving_personal_fields(current["items"], entries)
            print(f"Letterboxd items: merged {len(entries)} feed entries; total {len(current['items'])}.")
            changed = True
        else:
            print("Letterboxd items: no feed entries returned; existing data preserved.")
    except Exception as exc:
        print(f"Letterboxd diary feed unavailable: {exc}; existing diary data preserved.", file=sys.stderr)

    try:
        watchlist = scrape_public_watchlist(username)
        if watchlist:
            current["watchlist"] = merge_current_watchlist(current["watchlist"], watchlist)
            print(f"Letterboxd watchlist: synced {len(watchlist)} page entries; total {len(current['watchlist'])}.")
            changed = True
        else:
            print("Letterboxd watchlist returned no films; existing watchlist preserved.")
    except Exception as exc:
        print(f"Letterboxd watchlist sync unavailable: {exc}; keeping existing data unchanged.", file=sys.stderr)

    if changed:
        current["lastSyncedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_json("films.json", current)


def tmdb_search_movie(title, year, api_key):
    """Find a likely TMDB movie match by title and, when available, release year."""
    # Letterboxd RSS titles can contain year/rating decorations; remove them before searching.
    clean_title = re.sub(r"\s*,?\s*(?:18|19|20)\d{2}\s*(?:[-–—].*)?$", "", str(title or "")).strip()
    clean_title = re.sub(r"\s*[★☆]+.*$", "", clean_title).strip()
    if not clean_title:
        return None
    params = {"api_key": api_key, "query": clean_title, "include_adult": "false"}
    if year:
        params["year"] = str(year)
    url = "https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode(params)
    raw = request(url, headers={"Accept": "application/json"})
    payload = json.loads(raw.decode("utf-8"))
    results = payload.get("results") or []
    if not results and year:
        # Some databases disagree on release year; retry by title alone.
        params.pop("year", None)
        url = "https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode(params)
        raw = request(url, headers={"Accept": "application/json"})
        results = (json.loads(raw.decode("utf-8")).get("results") or [])
    if not results:
        return None

    def normalized(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    target = normalized(clean_title)
    # Prefer exact title + matching year, then closest title among matching-year results.
    same_year = [item for item in results if year and str(item.get("release_date", ""))[:4] == str(year)]
    candidates = same_year or results
    def score(item):
        names = [item.get("title", ""), item.get("original_title", "")]
        similarity = max((difflib.SequenceMatcher(None, target, normalized(name)).ratio() for name in names), default=0)
        return (1 if any(normalized(name) == target for name in names) else 0, similarity, float(item.get("popularity") or 0))
    best = max(candidates, key=score)
    if score(best)[1] < 0.55:
        return None
    poster_path = best.get("poster_path")
    return {
        "tmdbId": best.get("id"),
        "tmdbPosterPath": poster_path,
        "tmdbPosterUrl": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        "tmdbTitle": best.get("title"),
        "tmdbReleaseDate": best.get("release_date") or None,
    }


def enrich_tmdb_posters():
    """Enrich film data with TMDB metadata, without overwriting personal fields."""
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if not api_key:
        print("TMDB skipped: add TMDB_API_KEY as a GitHub Actions repository secret.")
        return
    current = load_json("films.json", {"items": [], "watchlist": [], "tiers": []})
    groups = [("items", current.get("items") or []), ("watchlist", current.get("watchlist") or [])]
    # Match duplicate items by stable identity, then apply the same result to both lists.
    cache = {}
    matched = 0
    failed = 0
    for list_name, entries in groups:
        for item in entries:
            if not isinstance(item, dict):
                continue
            key = stable_key(item)
            if item.get("tmdbId") and item.get("tmdbPosterPath"):
                cache[key] = {field: item.get(field) for field in ("tmdbId", "tmdbPosterPath", "tmdbPosterUrl", "tmdbTitle", "tmdbReleaseDate") if item.get(field) not in (None, "")}
                continue
            if key in cache:
                item.update(cache[key])
                continue
            try:
                match = tmdb_search_movie(item.get("title"), item.get("year"), api_key)
                if match:
                    item.update({field: value for field, value in match.items() if value not in (None, "")})
                    cache[key] = match
                    matched += 1
                    if matched % 25 == 0:
                        print(f"TMDB: matched {matched} films so far.")
                else:
                    failed += 1
                    cache[key] = {}
            except Exception as exc:
                failed += 1
                # Don't log the request URL; it contains the API key.
                print(f"TMDB lookup failed for {item.get('title', 'untitled')!r}: {type(exc).__name__}: {exc}", file=sys.stderr)
            time.sleep(0.15)
    save_json("films.json", current)
    print(f"TMDB posters: matched {matched} new film records; {failed} unmatched/failed lookups; collection saved.")

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
    enrich_tmdb_posters()
    sync_anilist()


if __name__ == "__main__":
    main()
