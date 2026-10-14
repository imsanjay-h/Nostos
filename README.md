# Nostos — a living personal archive

A complete static website foundation for GitHub Pages. The visual direction is intentionally new: warm paper, cobalt blue, coral, acid-lime, editorial typography, and poster/book galleries instead of the previous dark cinematic theme.

## Included

- `index.html` — homepage blending films, anime, books, music, current reading, and a changing thought.
- `films.html` — five personal tiers, an unplaced/newly imported area, and a separate watchlist.
- `anime.html` — watched collection and watchlist.
- `books.html` — read, currently reading, and want-to-read shelves.
- `connect.html` — Letterboxd, AniList, Goodreads, GitHub, and email links.
- Poster/book overlays that open without navigating away from the gallery.
- Independent, continuous horizontal movement for sufficiently long poster rows; short rows stay still. Hovering a moving row pauses it. Reduced-motion preferences are respected.
- `scripts/sync_collections.py` — scheduled Letterboxd RSS + AniList API sync.
- `scripts/import_exports.py` — bulk CSV import for Letterboxd diary/watchlist and Goodreads exports.
- `.github/workflows/sync-collections.yml` — scheduled GitHub Actions workflow, approximately every six hours, plus manual runs.

## 1. Put the site on GitHub Pages

1. Download and unzip this project.
2. Upload the **contents** of the `nostos-site` folder to the root of your website repository. The root should contain `index.html`, `films.html`, `anime.html`, `books.html`, `connect.html`, `assets/`, `data/`, `scripts/`, and `.github/`.
3. In the repository, open **Settings → Pages**. Set deployment to **Deploy from a branch**, select your publishing branch (usually `main`) and folder `/ (root)`, then save. If Pages is already enabled for this repository, keep its existing publishing settings.
4. Wait for the deployment to finish. Open the website URL and do a hard refresh if an older cached version appears.

Keep the directory structure intact. The HTML pages load the CSS, JavaScript, and JSON files by relative paths.

## 2. Add your platform usernames for automatic sync

This workflow does not need your Letterboxd or AniList passwords, and you should **never put passwords or API tokens into these files**.

In your GitHub repository:

1. Open **Settings → Secrets and variables → Actions → Variables**.
2. Create repository variable `LETTERBOXD_USERNAME` with your Letterboxd username (not the full URL).
3. Create repository variable `ANILIST_USERNAME` with your AniList username.
4. Open **Actions** and enable workflows if GitHub asks.
5. Open **Sync Nostos collections** and choose **Run workflow** to test it.

The workflow also runs on a schedule, approximately every six hours. GitHub may delay scheduled runs, so it is not instant sync.

### Letterboxd details

The sync reads the public RSS feed at `https://letterboxd.com/YOUR_USERNAME/rss/` and also attempts the watchlist RSS endpoint. RSS feeds expose recent activity, not a guaranteed complete all-time diary, and watchlist feed availability can vary. The sync merges new entries into your existing data so entries outside the recent feed are not deleted. Use the bulk CSV import below once to seed your full history and watchlist; the scheduled job will keep trying the feeds afterward.

Letterboxd's feed can supply a title and source link, but it cannot decide which personal Nostos tier a film belongs in. New films appear in **JUST LOGGED / NOT YET PLACED** until you assign a `tier` value in `data/films.json`. Valid tier IDs are `immortals`, `works-of-art`, `stayed-with-me`, `a-good-time`, and `didnt-connect`. A personal note can be added with the `note` field. The sync is designed to preserve these local fields.

### AniList details

The sync reads your public AniList anime list through its GraphQL API. Planning entries appear in the watchlist; other statuses appear in the watched/visited collection with their status shown in the detail overlay. If your list is private or the username is incorrect, the workflow log will report an error. This initial version deliberately uses public list data and does not ask for an access token.

### Books / Goodreads

The current workflow imports books from a Goodreads CSV export. Goodreads syncing options can change and are not assumed to offer a stable official API for this personal site. Re-import an updated CSV when you want to refresh your books.

## 3. Bulk-import your existing collections

Run these scripts on a computer with Python 3, from the project folder. (The site itself runs without Python.)

### Letterboxd

Export your diary and watchlist from Letterboxd, then run:

```bash
python scripts/import_exports.py --letterboxd-diary path/to/diary.csv --letterboxd-watchlist path/to/watchlist.csv
```

### Goodreads

Export your Goodreads library CSV, then run:

```bash
python scripts/import_exports.py --goodreads path/to/goodreads_library_export.csv
```

You can combine all three arguments in one command. After importing, commit the changed JSON files to GitHub. AniList does not require an initial export when its public API sync is working.

If you're working from Android only, you can still edit the JSON files directly in GitHub, but running the CSV import script is easier from a computer or a trusted Python environment. Don't upload private exports to public repositories; the generated JSON becomes public if committed to a public GitHub Pages repo.

## 4. The data files

- `data/films.json` — `items`, `watchlist`, and the five tier definitions.
- `data/anime.json` — `watched` and `watchlist`.
- `data/books.json` — `read`, `currentlyReading`, and `wantToRead`.
- `data/profile.json` — homepage intro, current music, current reading fallback, current thought, and social links. Add your profile URLs/email there so the Connect page links point to your real accounts.

Collection data is intentionally empty at first so the site does not pretend that sample titles are your real favourites. Empty sections show designed placeholders until you import data. The layout is ready for the collections to grow.

### Adding a personal film tier / note

An item in `data/films.json` can look like this:

```json
{
  "source": "letterboxd",
  "sourceId": "your-letterboxd-film-slug",
  "title": "Film title",
  "year": 2024,
  "url": "https://letterboxd.com/film/your-film/",
  "tier": "stayed-with-me",
  "note": "A thought you want to keep."
}
```

This is a **schema example only**, not an entry included in your collection. You can omit `note` entirely. The sync script preserves `tier`, `note`, and presentation fields when matching an existing entry.

## Important limitations to know

- This is a static site: there is no private admin panel or server database. The JSON files in the repository are the collection's source of truth.
- The GitHub Actions sync writes updated JSON back to the repository. If the repository is public, those collection files are public too. Keep private notes out of public files.
- RSS/API sync can be delayed, rate-limited, or temporarily unavailable. Workflow logs are available in the GitHub Actions tab.
- The poster design uses a custom editorial graphic treatment by default, so it does not depend on an API key to render. When Letterboxd RSS or AniList provides a poster/cover image URL, the gallery uses it; otherwise it falls back to the custom graphic treatment.
- The CV/portfolio page is intentionally not included yet, as planned; it can be added when there are projects and achievements to showcase.
