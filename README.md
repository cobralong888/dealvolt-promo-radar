# DealVolt — home appliance & consumer electronics brand deal radar

DealVolt tracks official prices and promo entries for home appliance and consumer
electronics brands. Everything on the site is read from the brands' own public
sources: their `products.json` feed, their public product sitemap, or a page on
their own website.

**Live site:** https://dealvolt-promo-radar.pages.dev

## What this actually is

- A static site. No server, no database, no runtime API keys, no model calls.
- An automated job re-reads the public sources on a schedule and commits fresh data.
- A discount is shown **only** when a brand's own feed lists a reference price above
  the current price. Nothing is estimated, and nothing is typed in by hand.
- If a brand publishes no public price feed, the site says so instead of guessing.

## Brands tracked

Momcozy, Anker, Ninja, eufy, UGREEN, Roborock, Anycubic, xTool, RingConn, Cozyla.

`wybot.com` was in the seed list but is **not** tracked: the domain currently serves a
parking page ("Contact us for any business inquiries"), not a store. It is excluded
rather than listed with invented data.

## How it works

```
scraper.py  ->  data/offers.json  ->  build.py  ->  site/  ->  Cloudflare Pages
```

- `scraper.py` reads `.ilang/site.ilang`, fetches each brand's public source, and writes
  `data/offers.json`. Standard library only.
- `build.py` reads the same config plus `data/offers.json` and renders `site/` with
  JSON-LD (`Product`, `Offer`, `AggregateOffer`, `ItemList`, `BreadcrumbList`, `FAQPage`),
  one canonical per page, and a generated `sitemap.xml` / `robots.txt`.
- `.github/workflows/update.yml` runs the scraper every 6 hours and commits new data.
- Cloudflare Pages builds with `python build.py`, output directory `site/`.

## Configuration lives in one place

`.ilang/site.ilang` is the single source of truth for brand list, niche, data sources,
rendering strings and limits. `scraper.py` and `build.py` both read it. To add a brand,
add a `::BRAND` block — no code change needed.

## Run it locally

```bash
python scraper.py
python build.py
# site/ is now ready; open site/index.html
```

Python 3.10+ and nothing else.

## Monetization

No affiliate links are present yet. Each brand has an empty `affiliate:` field in
`.ilang/site.ilang`; when a program is approved (CJ, ShareAsale, Impact, or a brand's
own program) it gets filled in there and nowhere else. No invented commission data.

## For AI agents

`AGENTS.md` states what may and may not be changed in this repository.

Site rules are described with the I-Lang protocol, see `.ilang/site.ilang`. Protocol notes: ilang.ai
