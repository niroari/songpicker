# Song Picker — Project Notes

Live: https://niroari.github.io/songpicker/
Repo: https://github.com/niroari/songpicker

---

## What it does

A browser-based random song picker that pulls from two guitar tab sites:
- **tab4u.com** — Hebrew songs
- **ultimateguitar.com** — English songs

Run `fetch_favorites.py` to scrape your saved tabs and regenerate `index.html`.
Open `index.html` locally or visit the GitHub Pages URL.

---

## Files

| File | Purpose |
|---|---|
| `fetch_favorites.py` | Scraper + HTML generator |
| `index.html` | Generated output — the actual app (committed) |
| `ug_favorites.html` | Manually saved UG page (gitignored, local only) |
| `tab4u_mysongs.html` | Manually saved tab4u AJAX response (gitignored, local only) |

---

## How scraping works

### Tab4u
- Endpoint: `GET https://www.tab4u.com/getMySongs.php?lan=0&otherUId=0&aID=0`
- Requires session cookies (read from Chrome via `rookiepy`)
- Response is delimited HTML using `` `TOPALB` `` and `` `TOPEND` `` as section markers
- Song URLs extracted via regex: `/tabs/songs/{id}_{Artist}_-_{Title}.html`
- **Manual fallback**: if session is expired, save the URL above from Chrome as `tab4u_mysongs.html` and re-run

### Ultimate Guitar
- Blocked by Cloudflare (403) when automated
- **Manual fallback**: log in to Chrome, go to `https://tabs.ultimate-guitar.com/user/mytabs`, save as `ug_favorites.html` and re-run
- Parser first tries `__NEXT_DATA__` JSON blob (Next.js SSR), then falls back to extracting `<a href>` links from the rendered DOM
- URL pattern: `/tab/{artist-slug}/{title-type-id}`

### Cookie extraction
- Uses `rookiepy` (handles Chrome 127+ App-Bound Encryption)
- Falls back to `browser_cookie3` if rookiepy unavailable
- Cookie values with non-latin1 characters are URL-encoded before use in HTTP headers

---

## HTML app layout

Three-column full-height layout:

```
[ Add Song panel ] | [ Random picker ] | [ Song list ]
     (left)              (middle)           (right)
```

- **Left**: paste a tab4u or UG link to add a song manually; added songs persist in `localStorage`
- **Middle**: random pick button, song card with title/artist/source, open tab button
- **Right**: scrollable song list with filter input and sort dropdown (Title / Artist / Source / Random)

### Keyboard shortcuts
- `Space` — pick a random song
- `Enter` — open current song's tab

---

## Updating songs

```bash
python3 fetch_favorites.py          # fetch both sites
python3 fetch_favorites.py --tab4u-only
python3 fetch_favorites.py --ug-only
python3 fetch_favorites.py --debug  # saves raw responses for inspection
```

Then commit and push `index.html`:
```bash
git add index.html && git commit -m "Update song list" && git push
```

---

## Dependencies

```bash
pip install requests beautifulsoup4 rookiepy
```

`browser_cookie3` is an optional fallback for cookie extraction.

---

## Known limitations

- Tab4u session cookies expire — re-save `tab4u_mysongs.html` when `getMySongs.php` returns the login prompt
- UG is permanently Cloudflare-blocked for automated requests — always needs the manual HTML save
- Manually added songs (via the left panel) are stored in `localStorage` and are browser/device specific — they are not included in the committed `index.html`
