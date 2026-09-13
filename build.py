"""
::ILANG
[TYPE:worker][FILE:build.py]
::ROLE 读 data/offers.json 与 .ilang/site.ilang，渲染静态站到 site/
::BOUNDARY 只渲染已有的真实数据；抓不到的字段不出现在页面上，也不出现在 JSON-LD 里
::NEVER 编造 price、priceValidUntil、优惠码或任何数字
::NEVER 在代码里另存一份品牌清单，一切来自 site.ilang

Render the static site from data/offers.json.

Standard library only. Reads .ilang/site.ilang for brand, wording and limits,
so changing the site rules never means editing this file.

Structured data that is actually emitted:
  index      WebSite + ItemList(brands) + ItemList(deals) + FAQPage
  brand page Product(with AggregateOffer when 2+ real prices) + ItemList + BreadcrumbList
  deal page  Product + Offer(price, priceCurrency, availability, url) + BreadcrumbList
  compare    ItemList(brands)
priceValidUntil is emitted only when a source actually provides it.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone

from ilang import load_site

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(HERE, "templates")
DATA_FILE = os.path.join(HERE, "data", "offers.json")

STYLE = """
:root{--bg:#ffffff;--fg:#14181f;--muted:#5b6472;--line:#e3e7ed;--accent:#0b5fff;--accent-fg:#ffffff;--soft:#f6f8fb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:0 20px}
header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--line)}
.brandmark{font-weight:700;font-size:20px;color:var(--fg);text-decoration:none}
header nav a{margin-left:18px;color:var(--muted);text-decoration:none}
header nav a:hover{color:var(--accent)}
.hero{padding:34px 0 18px}
h1{font-size:30px;line-height:1.25;margin:0 0 10px}
h2{font-size:21px;margin:34px 0 14px}
.meta{color:var(--muted);font-size:14px;margin:0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.card{border:1px solid var(--line);border-radius:10px;padding:14px;background:var(--soft)}
.card a{color:var(--accent);text-decoration:none;font-weight:600}
.card p{margin:6px 0 0;color:var(--muted);font-size:14px}
ul.deals{list-style:none;padding:0;margin:0}
ul.deals li{border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px;display:flex;gap:14px;align-items:flex-start}
ul.deals img{width:84px;height:84px;object-fit:contain;border-radius:8px;background:#fff;border:1px solid var(--line)}
.badge{display:inline-block;background:#e8f0ff;color:#0b3fa8;border-radius:6px;padding:2px 8px;font-size:13px;font-weight:700}
.price{font-size:22px;font-weight:700;margin:8px 0}
.price .was{color:var(--muted);font-size:15px;font-weight:400;text-decoration:line-through;margin-left:8px}
.btn{display:inline-block;background:var(--accent);color:var(--accent-fg);padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:600}
table.compare{width:100%;border-collapse:collapse;font-size:14px}
table.compare th,table.compare td{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}
table.compare th{background:var(--soft)}
dl.facts{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;margin:22px 0}
dl.facts dt{color:var(--muted)}
dl.facts dd{margin:0}
.note{color:var(--muted);font-size:14px;border-left:3px solid var(--line);padding-left:12px}
footer{border-top:1px solid var(--line);margin-top:44px;padding:22px 20px 40px;color:var(--muted);font-size:14px}
.copyright{margin-top:12px}
nav.breadcrumb{font-size:13px;color:var(--muted);padding:14px 0 0}
nav.breadcrumb a{color:var(--muted)}
img.heroimg{max-width:260px;width:100%;height:auto;border-radius:10px;border:1px solid var(--line);background:#fff}
"""

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def money(value, currency: str) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def read_template(name: str) -> str:
    with open(os.path.join(TPL_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def render(template: str, values: dict) -> str:
    def sub(match):
        key = match.group(1)
        return str(values.get(key, ""))

    return PLACEHOLDER.sub(sub, template)


def promo_label(url: str) -> str:
    tail = urllib.parse.urlparse(url).path.strip("/").split("/")[-1] or "official promo"
    return tail.replace("-", " ").title()


def breadcrumb(base: str, items: list) -> str:
    crumbs = ['<nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a>']
    for label, url in items:
        if url:
            crumbs.append(f' &rsaquo; <a href="{esc(url)}">{esc(label)}</a>')
        else:
            crumbs.append(f" &rsaquo; <span>{esc(label)}</span>")
    crumbs.append("</nav>")
    return "".join(crumbs)


def jsonld_block(data) -> str:
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


def availability_text(value) -> str:
    if not value:
        return "Not stated by source"
    return str(value).replace("https://schema.org/", "").replace("http://schema.org/", "")


def fmt_updated(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def month_year(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%B %Y")
    except Exception:
        return ""


# ------------------------------------------------------------------ renderers


def deal_card(item: dict, currency: str) -> str:
    img = f'<img src="{esc(item.get("image"))}" alt="">' if item.get("image") else ""
    compare = ""
    if item.get("compare_at"):
        compare = f'<span class="was">{money(item["compare_at"], currency)}</span>'
    badge = f'<span class="badge">-{item["discount_pct"]}%</span>' if item.get("discount_pct") else ""
    return (
        "<li>"
        f'<a href="/deal/{esc(item["id"])}/">{img}</a>' if img else "<li>"
    ) + (
        "<div>"
        f'<div>{badge} <a href="/deal/{esc(item["id"])}/">{esc(item["title"])}</a></div>'
        f'<div class="price">{money(item.get("price"), currency)} {esc(currency)} {compare}</div>'
        f'<div class="meta">{esc(item.get("brand_name"))} &middot; '
        f'<a href="{esc(item.get("url"))}" rel="nofollow noopener" target="_blank">official product page</a></div>'
        "</div></li>"
    )


def product_row(item: dict, currency: str) -> str:
    return (
        "<li><div>"
        f'<div><a href="{esc(item.get("url"))}" rel="nofollow noopener" target="_blank">{esc(item["title"])}</a></div>'
        f'<div class="meta">{esc(item.get("brand_name"))} &middot; {money(item.get("price"), currency)} {esc(currency)}'
        f' &middot; {esc(availability_text(item.get("availability")))}</div>'
        "</div></li>"
    )


def main() -> int:
    cfg = load_site()
    meta = cfg["meta"]
    render_cfg = cfg["render"]
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    dmeta = data.get("meta", {})
    brand_name = meta.get("brand", "DealVolt")
    currency = dmeta.get("currency", meta.get("currency", "USD"))
    base = (meta.get("base_url") or "").rstrip("/")
    generated = data.get("generated_at", "")
    updated = fmt_updated(generated)
    month = month_year(generated)
    year = datetime.now(timezone.utc).year

    deals = data.get("deals", [])
    products = data.get("products", [])

    # Brand identity (name, official URL, promo pages, source kind) is taken from
    # .ilang/site.ilang, not from offers.json. offers.json only supplies counts and
    # run status, so editing the config changes the site on the next build.
    data_brands = {b["slug"]: b for b in data.get("brands", [])}
    brands = []
    for cb in cfg["brands"]:
        db = data_brands.get(cb["slug"], {})
        merged = dict(cb)
        merged["promo"] = [
            {"url": u, "label": promo_label(u)} for u in (cb.get("promo") or [])
        ]
        merged["deal_count"] = db.get("deal_count", 0)
        merged["product_count"] = db.get("product_count", 0)
        merged["source_status"] = db.get("source_status", "no_data")
        brands.append(merged)

    out_dir = os.path.join(HERE, meta.get("build_output", "site/") or "site/")

    def tpl(key, **values):
        text = render_cfg.get(key, "")
        for k, v in values.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    # ------------------------------------------------ index
    brand_grid = "".join(
        '<div class="card"><a href="/brand/{slug}/">{name}</a>'
        "<p>{promo} official promo page(s)<br>{deals} discounted &middot; {prods} tracked prices</p></div>".format(
            slug=esc(b["slug"]),
            name=esc(b["name"]),
            promo=len(b.get("promo", [])),
            deals=b.get("deal_count", 0),
            prods=b.get("product_count", 0),
        )
        for b in brands
    )
    deal_list = (
        '<ul class="deals">' + "".join(deal_card(d, currency) for d in deals[:40]) + "</ul>"
        if deals
        else '<p class="note">No item in this run was listed below its own reference price. '
        "Nothing is shown here rather than inventing a discount. Official promo pages are linked on each brand page.</p>"
    )
    product_list = (
        '<ul class="deals">' + "".join(product_row(p, currency) for p in products[:40]) + "</ul>"
        if products
        else '<p class="note">No public price feed returned data in this run.</p>'
    )

    faq_items = []
    for i in range(1, 5):
        q = render_cfg.get(f"faq_{i}_q")
        a = render_cfg.get(f"faq_{i}_a")
        if q and a:
            faq_items.append({"q": q, "a": a})
    faq_html = "".join(
        f"<h3>{esc(i['q'])}</h3><p>{esc(i['a'])}</p>" for i in faq_items
    )

    index_ld = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": brand_name,
            "url": base + "/" if base else "",
            "description": dmeta.get("tagline", ""),
            "inLanguage": dmeta.get("locale", "en-US"),
        },
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "url": f"{base}/brand/{b['slug']}/" if base else f"/brand/{b['slug']}/",
                    "name": b["name"],
                }
                for i, b in enumerate(brands)
            ],
        },
    ]
    if deals:
        index_ld.append(
            {
                "@context": "https://schema.org",
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "url": f"{base}/deal/{d['id']}/" if base else f"/deal/{d['id']}/",
                        "name": d["title"],
                    }
                    for i, d in enumerate(deals[:40])
                ],
            }
        )
    if faq_items:
        index_ld.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": i["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": i["a"]},
                    }
                    for i in faq_items
                ],
            }
        )

    index_html = render(
        read_template("index.html"),
        {
            "LANG": dmeta.get("language", "en"),
            "TITLE": esc(
                tpl("home_title", brand=brand_name, niche=dmeta.get("niche", ""), month=month)
            ),
            "DESC": esc(
                tpl(
                    "home_desc",
                    brand=brand_name,
                    niche=dmeta.get("niche", ""),
                    brand_count=len(brands),
                    date=updated,
                )
            ),
            "CANONICAL": esc((base + "/") if base else "/"),
            "STYLE": STYLE,
            "JSONLD": "\n".join(jsonld_block(x) for x in index_ld),
            "BRAND": esc(brand_name),
            "TAGLINE": esc(dmeta.get("tagline", "")),
            "BRAND_COUNT": len(brands),
            "DEAL_COUNT": len(deals),
            "UPDATED": esc(updated),
            "BRAND_GRID": brand_grid,
            "DEAL_LIST": deal_list,
            "PRODUCT_LIST": product_list,
            "FAQ": faq_html,
            "YEAR": year,
        },
    )
    write(os.path.join(out_dir, "index.html"), index_html)

    # ------------------------------------------------ brand pages
    for b in brands:
        b_deals = [d for d in deals if d["brand_slug"] == b["slug"]]
        b_products = [p for p in products if p["brand_slug"] == b["slug"]]

        promo_list = (
            "<ul>"
            + "".join(
                f'<li><a href="{esc(p["url"])}" rel="nofollow noopener" target="_blank">{esc(p["label"])}</a></li>'
                for p in b.get("promo", [])
            )
            + "</ul>"
            if b.get("promo")
            else '<p class="note">No official promo page was found in this brand\'s public sitemap during the last run.</p>'
        )

        page_url = f"{base}/brand/{b['slug']}/" if base else f"/brand/{b['slug']}/"
        ld = [
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": (base + "/") if base else "/"},
                    {"@type": "ListItem", "position": 2, "name": b["name"], "item": page_url},
                ],
            }
        ]
        priced = [d["price"] for d in b_deals if d.get("price") is not None]
        if len(priced) >= 2:
            ld.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": f"{b['name']} deals",
                    "brand": {"@type": "Brand", "name": b["name"]},
                    "url": b["official"],
                    "offers": {
                        "@type": "AggregateOffer",
                        "priceCurrency": currency,
                        "lowPrice": min(priced),
                        "highPrice": max(priced),
                        "offerCount": len(priced),
                    },
                }
            )
        elif len(priced) == 1:
            ld.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": f"{b['name']} deals",
                    "brand": {"@type": "Brand", "name": b["name"]},
                    "url": b["official"],
                    "offers": {
                        "@type": "Offer",
                        "priceCurrency": currency,
                        "price": priced[0],
                        "url": b_deals[0]["url"],
                    },
                }
            )
        else:
            ld.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Service",
                    "name": f"{b['name']} official promo entries",
                    "provider": {"@type": "Organization", "name": b["name"], "url": b["official"]},
                    "url": page_url,
                }
            )
        if b_deals:
            ld.append(
                {
                    "@context": "https://schema.org",
                    "@type": "ItemList",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": i + 1,
                            "url": f"{base}/deal/{d['id']}/" if base else f"/deal/{d['id']}/",
                            "name": d["title"],
                        }
                        for i, d in enumerate(b_deals)
                    ],
                }
            )

        note = {
            "products_json": "Prices are read from this brand's public products feed. A discount is shown only when the feed lists a reference price above the current price.",
            "sitemap_products": "Prices are read from this brand's public product pages. A discount is shown only when the page states one.",
            "none": "This brand publishes no public price feed this site can read, so only its official site is listed. No price on this page is estimated.",
        }.get(b.get("source", "none"), "")
        if b.get("source_status") not in ("ok", ""):
            note += f" Last run status: {b.get('source_status')}."

        html_out = render(
            read_template("provider.html"),
            {
                "LANG": dmeta.get("language", "en"),
                "TITLE": esc(
                    tpl("brand_title", name=b["name"], month=month, brand=brand_name)
                ),
                "DESC": esc(
                    tpl(
                        "brand_desc",
                        name=b["name"],
                        deal_count=len(b_deals),
                        date=updated,
                    )
                ),
                "CANONICAL": esc(page_url),
                "STYLE": STYLE,
                "JSONLD": "\n".join(jsonld_block(x) for x in ld),
                "BREADCRUMB": breadcrumb(base, [(b["name"], None)]),
                "BRAND": esc(brand_name),
                "BRAND_NAME": esc(b["name"]),
                "OFFICIAL": esc(b["official"]),
                "DEAL_COUNT": len(b_deals),
                "UPDATED": esc(updated),
                "PROMO_LIST": promo_list,
                "DEAL_LIST": (
                    '<ul class="deals">' + "".join(deal_card(d, currency) for d in b_deals) + "</ul>"
                    if b_deals
                    else '<p class="note">No discounted item was found for this brand in the last run.</p>'
                ),
                "PRODUCT_LIST": (
                    '<ul class="deals">' + "".join(product_row(p, currency) for p in b_products) + "</ul>"
                    if b_products
                    else '<p class="note">No tracked price for this brand in the last run.</p>'
                ),
                "NOTE": esc(note),
                "YEAR": year,
            },
        )
        write(os.path.join(out_dir, "brand", b["slug"], "index.html"), html_out)

    # ------------------------------------------------ deal pages
    for d in deals:
        page_url = f"{base}/deal/{d['id']}/" if base else f"/deal/{d['id']}/"
        offer = {
            "@type": "Offer",
            "price": d.get("price"),
            "priceCurrency": d.get("currency", currency),
            "availability": d.get("availability"),
            "url": d.get("url"),
        }
        # priceValidUntil is emitted only when a source actually provides it.
        if d.get("price_valid_until"):
            offer["priceValidUntil"] = d["price_valid_until"]
        ld = [
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": (base + "/") if base else "/"},
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": d["brand_name"],
                        "item": f"{base}/brand/{d['brand_slug']}/" if base else f"/brand/{d['brand_slug']}/",
                    },
                    {"@type": "ListItem", "position": 3, "name": d["title"], "item": page_url},
                ],
            },
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": d["title"],
                "brand": {"@type": "Brand", "name": d["brand_name"]},
                "url": page_url,
                "offers": offer,
            },
        ]
        if d.get("image"):
            ld[1]["image"] = d["image"]

        compare_block = (
            f'<span class="was">{money(d["compare_at"], currency)}</span>'
            if d.get("compare_at")
            else ""
        )
        discount_block = (
            f'<span class="badge">-{d["discount_pct"]}%</span>' if d.get("discount_pct") else ""
        )
        img_html = (
            f'<img class="heroimg" src="{esc(d["image"])}" alt="">' if d.get("image") else ""
        )
        image_meta = (
            f'<meta property="og:image" content="{esc(d["image"])}">' if d.get("image") else ""
        )

        html_out = render(
            read_template("deal.html"),
            {
                "LANG": dmeta.get("language", "en"),
                "TITLE": esc(
                    tpl(
                        "deal_title",
                        name=d["brand_name"],
                        discount=d.get("discount_pct", 0),
                        product=d["title"],
                        brand=brand_name,
                    )
                ),
                "DESC": esc(
                    tpl(
                        "deal_desc",
                        product=d["title"],
                        price=money(d.get("price"), currency),
                        compare=money(d.get("compare_at"), currency) if d.get("compare_at") else "n/a",
                        currency=currency,
                        name=d["brand_name"],
                        date=updated,
                    )
                ),
                "CANONICAL": esc(page_url),
                "STYLE": STYLE,
                "JSONLD": "\n".join(jsonld_block(x) for x in ld),
                "BREADCRUMB": breadcrumb(
                    base, [(d["brand_name"], f"/brand/{d['brand_slug']}/"), (d["title"], None)]
                ),
                "BRAND": esc(brand_name),
                "BRAND_NAME": esc(d["brand_name"]),
                "PRODUCT": esc(d["title"]),
                "PRICE": money(d.get("price"), currency),
                "CURRENCY": esc(d.get("currency", currency)),
                "COMPARE_BLOCK": compare_block,
                "DISCOUNT_BLOCK": discount_block,
                "URL": esc(d.get("url")),
                "IMAGE_HTML": img_html,
                "IMAGE_META": image_meta,
                "AVAILABILITY": esc(availability_text(d.get("availability"))),
                "SOURCE_URL": esc(d.get("source_url")),
                "SOURCE_KIND": esc(d.get("source_kind")),
                "UPDATED": esc(updated),
                "NOTE": esc(
                    "Every figure on this page was read from the brand's own public source at the time shown. "
                    "Confirm the price on the official page before buying."
                ),
                "YEAR": year,
            },
        )
        write(os.path.join(out_dir, "deal", d["id"], "index.html"), html_out)

    # ------------------------------------------------ compare
    rows = "".join(
        "<tr>"
        f'<td><a href="/brand/{esc(b["slug"])}/">{esc(b["name"])}</a></td>'
        f"<td>{esc(b.get('source', 'none'))}</td>"
        f"<td>{b.get('deal_count', 0)}</td>"
        f"<td>{b.get('product_count', 0)}</td>"
        f"<td>{len(b.get('promo', []))}</td>"
        f'<td><a href="{esc(b["official"])}" rel="nofollow noopener" target="_blank">official site</a></td>'
        "</tr>"
        for b in brands
    )
    compare_ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": f"{base}/brand/{b['slug']}/" if base else f"/brand/{b['slug']}/",
                "name": b["name"],
            }
            for i, b in enumerate(brands)
        ],
    }
    compare_url = f"{base}/compare/" if base else "/compare/"
    compare_html = render(
        read_template("compare.html"),
        {
            "LANG": dmeta.get("language", "en"),
            "TITLE": esc(tpl("compare_title", brand_count=len(brands), month=month, brand=brand_name)),
            "DESC": esc(tpl("compare_desc", brand_count=len(brands), date=updated)),
            "CANONICAL": esc(compare_url),
            "STYLE": STYLE,
            "JSONLD": jsonld_block(compare_ld),
            "BREADCRUMB": breadcrumb(base, [("Brands", None)]),
            "BRAND": esc(brand_name),
            "BRAND_COUNT": len(brands),
            "UPDATED": esc(updated),
            "COMPARE_ROWS": rows,
            "NOTE": esc(
                "Counts come from the last run only. They are not a ranking and no score is invented."
            ),
            "YEAR": year,
        },
    )
    write(os.path.join(out_dir, "compare", "index.html"), compare_html)

    # ------------------------------------------------ sitemap + robots
    urls = [("/", "1.0"), ("/compare/", "0.6")]
    for b in brands:
        urls.append((f"/brand/{b['slug']}/", "0.8"))
    for d in deals:
        urls.append((f"/deal/{d['id']}/", "0.7"))
    lastmod = generated or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    loc = base if base else ""
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, prio in urls:
        sitemap.append(
            f"  <url><loc>{html.escape(loc + path)}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>daily</changefreq><priority>{prio}</priority></url>"
        )
    sitemap.append("</urlset>")
    write(os.path.join(out_dir, "sitemap.xml"), "\n".join(sitemap) + "\n")

    robots = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "",
            f"Sitemap: {loc}/sitemap.xml" if loc else "Sitemap: /sitemap.xml",
            "",
        ]
    )
    write(os.path.join(out_dir, "robots.txt"), robots)

    print(
        f"built into {out_dir}: index, {len(brands)} brand pages, "
        f"{len(deals)} deal pages, compare, sitemap.xml ({len(urls)} urls), robots.txt"
    )
    return 0


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    raise SystemExit(main())
