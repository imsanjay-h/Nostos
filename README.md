# Nostos Connect refresh

This package contains a page-scoped Connect redesign and six individual Nostos profile pages.

## Included
- `connect.html` — six featured full-width cinematic stripes, plus a seven-platform directory.
- `letterboxd.html`, `anilist.html`, `github.html`, `instagram.html`, `reddit.html`, `mail.html` — individual landing pages for the featured stripes.
- `assets/css/connect.css` — styles used by these pages only.

## Add to the Nostos repository
1. Copy `connect.html` to the repository root.
2. Copy the six profile HTML files to the repository root.
3. Copy `assets/css/connect.css` to `assets/css/connect.css` (create the folder if necessary).
4. Preview the site, then commit and push to GitHub Pages.

## Behaviour and design
- The six featured stripes link to their individual Nostos pages, which then link out to the corresponding platform profile.
- Mobile layout is a single vertical list, with consistent icon/text alignment. The seven additional profiles form a separate responsive directory.
- Mail has its own page and opens the user's email app for either the personal or professional address.
- Brand marks use Simple Icons CDN SVGs (`cdn.simpleicons.org`); photography uses Unsplash and typography uses Google Fonts. Internet access is required for these remote assets.
- Existing non-Connect pages and the site's global CSS are not included or modified by this package.
