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
:root{
  --bg:#f6f8fc; --card:#ffffff; --ink:#0f172a; --body:#334155; --muted:#6b7a90;
  --line:#e6eaf2; --line-strong:#d5dce8;
  --accent:#2563eb; --accent-dark:#1d4ed8; --deal:#e11d48; --ok:#047857;
  --radius:16px; --radius-sm:10px;
  --shadow:0 1px 2px rgba(15,23,42,.04), 0 8px 24px -12px rgba(15,23,42,.18);
  --shadow-hover:0 2px 6px rgba(15,23,42,.06), 0 18px 40px -16px rgba(15,23,42,.28);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--bg);color:var(--body);
  font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI Variable Text","Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
a{color:var(--accent)}
h1,h2,h3,h4{color:var(--ink);margin:0}
h1{font-size:clamp(28px,4vw,42px);line-height:1.15;letter-spacing:-.02em;font-weight:800}
h2{font-size:22px;letter-spacing:-.01em;font-weight:750}
h3{font-size:16px;line-height:1.4;font-weight:700}

/* ---------- header ---------- */
.site-header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.88);backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{display:inline-flex;align-items:center;gap:10px;font-weight:800;color:var(--ink);text-decoration:none;font-size:18px;letter-spacing:-.02em}
.logo-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#0f172a,#334155);color:#7dd3fc;font-size:15px;font-weight:800}
.site-header nav{display:flex;gap:4px}
.site-header nav a{padding:8px 14px;border-radius:999px;color:var(--muted);text-decoration:none;font-size:14px;font-weight:600}
.site-header nav a:hover{background:#eef2f9;color:var(--ink)}

/* ---------- hero ---------- */
.hero{background:radial-gradient(1200px 480px at 15% -10%,#1e3a8a 0%,transparent 60%),linear-gradient(135deg,#0f172a 0%,#1e293b 55%,#0f172a 100%);color:#e2e8f0;padding:56px 0 60px}
.hero h1{color:#fff}
.hero .eyebrow{margin:0 0 14px;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#7dd3fc}
.hero .lede{margin:16px 0 0;max-width:62ch;font-size:17px;color:#c3cfdd}
.hero .stamp{margin:18px 0 0;font-size:13px;color:#8fa3ba}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:28px 0 0}
.stat{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:14px;padding:12px 20px;min-width:132px}
.stat b{display:block;font-size:26px;line-height:1.1;color:#fff;font-weight:800;font-variant-numeric:tabular-nums}
.stat span{font-size:12px;color:#9fb3c8;letter-spacing:.02em}

/* ---------- brand hero ---------- */
.brand-hero-inner{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}
.avatar{display:grid;place-items:center;border-radius:18px;font-weight:800;color:hsl(var(--hue) 62% 28%);background:hsl(var(--hue) 78% 92%);flex:none}
.avatar-lg{width:88px;height:88px;font-size:34px;border-radius:22px}
.hero-brand .lede{max-width:60ch}
.stats-sm .stat{min-width:110px;padding:10px 16px}
.hero-actions{margin:22px 0 0}

/* ---------- sections ---------- */
.section{margin:44px 0}
.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--line)}
.section-head .hint,.hint{color:var(--muted);font-size:13px}
.more{font-size:14px;font-weight:600;text-decoration:none}
.more:hover{text-decoration:underline}

/* ---------- brand grid ---------- */
.brand-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.brand-card{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px;text-decoration:none;transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.brand-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover);border-color:var(--line-strong)}
.brand-card .avatar{width:44px;height:44px;font-size:17px;border-radius:13px}
.brand-name{display:block;font-weight:700;color:var(--ink);font-size:15px}
.brand-meta{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}

/* ---------- deal grid ---------- */
.deal-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.deal-card{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;text-decoration:none;transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.deal-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-hover);border-color:var(--line-strong)}
.deal-thumb{height:168px;display:grid;place-items:center;background:#fff;border-bottom:1px solid var(--line);padding:14px}
.deal-thumb img{max-width:100%;max-height:100%;object-fit:contain}
.deal-thumb .fallback{width:100%;height:100%;border-radius:12px;display:grid;place-items:center;font-size:30px;font-weight:800;color:hsl(var(--hue) 55% 34%);background:hsl(var(--hue) 74% 95%)}
.deal-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;flex:1}
.deal-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.deal-card h3{color:var(--ink)}
.deal-title{margin:0;font-size:15px;font-weight:700;color:var(--ink);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.price-row{display:flex;align-items:baseline;gap:8px;margin-top:auto;padding-top:6px}
.price-now{font-size:20px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.price-now em{font-style:normal;font-size:12px;font-weight:700;color:var(--muted);margin-left:2px}
.price-was{font-size:13px;color:var(--muted);text-decoration:line-through;font-variant-numeric:tabular-nums}

/* ---------- chips & badges ---------- */
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;background:hsl(var(--hue) 74% 94%);color:hsl(var(--hue) 58% 30%);white-space:nowrap}
.chip-plain{background:#eef2f9;color:#475569}
.badge{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:800;background:#ffe4e9;color:var(--deal);white-space:nowrap}
.badge-lg{font-size:14px;padding:6px 14px}
.pill{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;background:#eef2f9;color:#475569;white-space:nowrap}
.pill-ok{background:#e7f6ef;color:var(--ok)}
.pill-warn{background:#fef3c7;color:#92400e}

/* ---------- compact product list ---------- */
.price-list{list-style:none;margin:0;padding:0;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.price-list li{display:flex;align-items:center;gap:12px;padding:13px 18px;border-bottom:1px solid var(--line)}
.price-list li:last-child{border-bottom:0}
.price-list .pl-main{flex:1;min-width:0}
.price-list .pl-title{display:block;color:var(--ink);font-weight:600;font-size:14.5px;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.price-list .pl-title:hover{text-decoration:underline}
.price-list .pl-sub{font-size:12.5px;color:var(--muted)}
.price-list .pl-price{font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;white-space:nowrap}

/* ---------- promo chips ---------- */
.chip-row{display:flex;flex-wrap:wrap;gap:10px}
.chip-link{display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:13.5px;font-weight:600;transition:border-color .15s,box-shadow .15s}
.chip-link:hover{border-color:var(--accent);box-shadow:var(--shadow)}
.chip-link::after{content:"↗";color:var(--muted);font-size:12px}

/* ---------- buttons ---------- */
.btn{display:inline-block;background:var(--accent);color:#fff;padding:11px 20px;border-radius:999px;text-decoration:none;font-weight:700;font-size:14.5px;transition:background .15s,transform .1s}
.btn:hover{background:var(--accent-dark)}
.btn:active{transform:translateY(1px)}
.btn-lg{padding:14px 26px;font-size:15.5px}
.cta-row{margin:22px 0 0}

/* ---------- deal page ---------- */
.deal-page{padding:30px 0 10px}
.deal-layout{display:grid;grid-template-columns:minmax(0,420px) minmax(0,1fr);gap:40px;align-items:start;margin-top:22px}
.deal-media{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:24px;display:grid;place-items:center;min-height:280px}
.deal-media img{max-width:100%;max-height:360px;object-fit:contain}
.deal-media .fallback{width:100%;min-height:240px;border-radius:12px;display:grid;place-items:center;font-size:72px;font-weight:800;color:hsl(var(--hue) 55% 34%);background:hsl(var(--hue) 74% 95%)}
.deal-info h1{margin:14px 0 0}
.price-block{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:18px;padding:16px 20px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);width:fit-content}
.price-block .price-now{font-size:30px}
table.facts{width:100%;border-collapse:collapse;margin:26px 0 0;font-size:14.5px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
table.facts th,table.facts td{text-align:left;padding:11px 16px;border-bottom:1px solid var(--line)}
table.facts tr:last-child th,table.facts tr:last-child td{border-bottom:0}
table.facts th{width:150px;color:var(--muted);font-weight:600;background:#fbfcfe}

/* ---------- compare table ---------- */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.table-card{overflow:hidden}
table.compare{width:100%;border-collapse:collapse;font-size:14px}
table.compare th,table.compare td{padding:13px 18px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
table.compare thead th{background:#fbfcfe;color:var(--muted);font-size:12px;letter-spacing:.06em;text-transform:uppercase;font-weight:700}
table.compare tbody tr:last-child td{border-bottom:0}
table.compare tbody tr:hover{background:#fbfcfe}
table.compare td.num{font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink)}
.tname{font-weight:700;color:var(--ink);text-decoration:none}
.tname:hover{text-decoration:underline}

/* ---------- faq ---------- */
.faq{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:8px 26px 20px}
.faq h3{font-size:16px;margin:18px 0 6px}
.faq p{margin:0 0 14px;color:var(--body)}

/* ---------- note & breadcrumb ---------- */
.note{margin:26px 0 0;color:var(--muted);font-size:13.5px;line-height:1.7;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:var(--radius-sm);padding:14px 18px}
nav.breadcrumb{font-size:13px;color:var(--muted);padding:0 0 4px}
nav.breadcrumb a{color:var(--muted);text-decoration:none}
nav.breadcrumb a:hover{color:var(--accent);text-decoration:underline}
.hero nav.breadcrumb a{color:#9fb3c8}
.hero nav.breadcrumb{color:#8fa3ba}

/* ---------- footer ---------- */
.site-footer{margin-top:56px;background:#0f172a;color:#94a3b8;padding:44px 0 26px}
.site-footer .logo{color:#fff}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1.4fr;gap:36px}
.site-footer h4{color:#fff;font-size:13px;letter-spacing:.08em;text-transform:uppercase;margin:0 0 12px}
.site-footer a{display:block;color:#94a3b8;text-decoration:none;font-size:14px;margin-bottom:8px}
.site-footer a:hover{color:#fff}
.footer-note{font-size:13.5px;line-height:1.7;margin:12px 0 0;max-width:52ch}
.footer-bottom{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:32px;padding-top:18px;border-top:1px solid rgba(255,255,255,.1);font-size:12.5px}

@media (max-width:900px){
  .deal-layout{grid-template-columns:1fr;gap:24px}
  .footer-grid{grid-template-columns:1fr 1fr}
}
@media (max-width:620px){
  .wrap{padding:0 16px}
  .hero{padding:40px 0 44px}
  .footer-grid{grid-template-columns:1fr;gap:24px}
  .section{margin:34px 0}
  .stat{flex:1 1 120px}
}
"""

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

# Inline SVG favicon (data URI) so the site needs no extra asset request.
FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='8' fill='%230f172a'/%3E"
    "%3Cpath d='M19 4 L9 18.5 h5.6 L13 28 24 13 h-6.2 z' fill='%2338bdf8'/%3E%3C/svg%3E"
)


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


def hue_for(text: str) -> int:
    """Stable colour per brand, derived from the slug. No randomness, no config."""
    return sum(ord(c) for c in (text or "?")) % 360


def initials(text: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", text or "") if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def deal_card(item: dict, currency: str) -> str:
    hue = hue_for(item.get("brand_slug", ""))
    thumb = (
        f'<img src="{esc(item.get("image"))}" alt="" loading="lazy">'
        if item.get("image")
        else f'<span class="fallback" style="--hue:{hue}">{esc(initials(item.get("brand_name", "?")))}</span>'
    )
    badge = (
        f'<span class="badge">-{item["discount_pct"]}% off</span>'
        if item.get("discount_pct")
        else ""
    )
    was = (
        f'<span class="price-was">{money(item["compare_at"], currency)}</span>'
        if item.get("compare_at")
        else ""
    )
    return (
        f'<a class="deal-card" href="/deal/{esc(item["id"])}/">'
        f'<div class="deal-thumb">{thumb}</div>'
        '<div class="deal-body">'
        '<div class="deal-top">'
        f'<span class="chip" style="--hue:{hue}">{esc(item.get("brand_name"))}</span>{badge}'
        "</div>"
        f'<p class="deal-title">{esc(item.get("title"))}</p>'
        '<div class="price-row">'
        f'<span class="price-now">{money(item.get("price"), currency)}<em>{esc(currency)}</em></span>{was}'
        "</div>"
        "</div></a>"
    )


def product_row(item: dict, currency: str) -> str:
    hue = hue_for(item.get("brand_slug", ""))
    return (
        "<li>"
        f'<span class="chip" style="--hue:{hue}">{esc(item.get("brand_name"))}</span>'
        '<span class="pl-main">'
        f'<a class="pl-title" href="{esc(item.get("url"))}" rel="nofollow noopener" target="_blank">{esc(item.get("title"))}</a>'
        f'<span class="pl-sub">{esc(availability_text(item.get("availability")))}</span>'
        "</span>"
        f'<span class="pl-price">{money(item.get("price"), currency)} {esc(currency)}</span>'
        "</li>"
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
        '<a class="brand-card" href="/brand/{slug}/">'
        '<span class="avatar" style="--hue:{hue}">{initial}</span>'
        "<span>"
        '<span class="brand-name">{name}</span>'
        '<span class="brand-meta">{deals} discounts &middot; {promo} promo pages</span>'
        "</span></a>".format(
            slug=esc(b["slug"]),
            name=esc(b["name"]),
            hue=hue_for(b["slug"]),
            initial=esc(initials(b["name"])),
            deals=b.get("deal_count", 0),
            promo=len(b.get("promo", [])),
        )
        for b in brands
    )
    deal_list = (
        '<div class="deal-grid">' + "".join(deal_card(d, currency) for d in deals[:40]) + "</div>"
        if deals
        else '<p class="note">No item in this run was listed below its own reference price. '
        "Nothing is shown here rather than inventing a discount. Official promo pages are linked on each brand page.</p>"
    )
    product_list = (
        '<ul class="price-list">' + "".join(product_row(p, currency) for p in products[:40]) + "</ul>"
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
            "FAVICON": FAVICON,
            "BRAND": esc(brand_name),
            "INITIAL": esc(initials(brand_name)),
            "NICHE": esc(dmeta.get("niche", "")),
            "HERO_TITLE": esc(
                dmeta.get("tagline", "") or f"{dmeta.get('niche', '')} tracked from official sources"
            ),
            "TAGLINE": esc(
                "Every price and every promo entry below was read from the brand's own "
                "public feed or sitemap. Discounts appear only when a brand lists an item "
                "below its own reference price — nothing here is estimated."
            ),
            "BRAND_COUNT": len(brands),
            "DEAL_COUNT": len(deals),
            "PRODUCT_COUNT": len(products),
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
            '<div class="chip-row">'
            + "".join(
                f'<a class="chip-link" href="{esc(p["url"])}" rel="nofollow noopener" target="_blank">{esc(p["label"])}</a>'
                for p in b.get("promo", [])
            )
            + "</div>"
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
                "FAVICON": FAVICON,
                "BREADCRUMB": breadcrumb(base, [(b["name"], None)]),
                "BRAND": esc(brand_name),
                "INITIAL": esc(initials(brand_name)),
                "BRAND_NAME": esc(b["name"]),
                "BRAND_INITIAL": esc(initials(b["name"])),
                "BRAND_LEDE": esc(
                    f"Official promo pages and tracked prices for {b['name']}, read from "
                    f"{b['name']}'s own public sources. Every link goes back to their site."
                ),
                "HUE": hue_for(b["slug"]),
                "OFFICIAL": esc(b["official"]),
                "DEAL_COUNT": len(b_deals),
                "PROMO_COUNT": len(b.get("promo", [])),
                "PRODUCT_COUNT": len(b_products),
                "UPDATED": esc(updated),
                "PROMO_LIST": promo_list,
                "DEAL_LIST": (
                    '<div class="deal-grid">' + "".join(deal_card(d, currency) for d in b_deals) + "</div>"
                    if b_deals
                    else '<p class="note">No discounted item was found for this brand in the last run.</p>'
                ),
                "PRODUCT_LIST": (
                    '<ul class="price-list">' + "".join(product_row(p, currency) for p in b_products) + "</ul>"
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
            f'<span class="price-was">{money(d["compare_at"], currency)}</span>'
            if d.get("compare_at")
            else ""
        )
        discount_block = (
            f'<span class="badge badge-lg">-{d["discount_pct"]}% off</span>'
            if d.get("discount_pct")
            else ""
        )
        hue = hue_for(d.get("brand_slug", ""))
        if d.get("image"):
            img_html = f'<img src="{esc(d["image"])}" alt="">'
        else:
            img_html = (
                f'<span class="fallback" style="--hue:{hue}">'
                f'{esc(initials(d.get("brand_name", "?")))}</span>'
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
                "FAVICON": FAVICON,
                "BREADCRUMB": breadcrumb(
                    base, [(d["brand_name"], f"/brand/{d['brand_slug']}/"), (d["title"], None)]
                ),
                "BRAND": esc(brand_name),
                "INITIAL": esc(initials(brand_name)),
                "HUE": hue,
                "BRAND_SLUG": esc(d.get("brand_slug", "")),
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
    def source_pill(brand_obj) -> str:
        src = brand_obj.get("source", "none")
        if src == "products_json":
            return '<span class="pill pill-ok">products feed</span>'
        if src == "sitemap_products":
            return '<span class="pill pill-ok">product sitemap</span>'
        return '<span class="pill">no public feed</span>'

    rows = "".join(
        "<tr>"
        f'<td><a class="tname" href="/brand/{esc(b["slug"])}/">{esc(b["name"])}</a></td>'
        f"<td>{source_pill(b)}</td>"
        f'<td class="num">{b.get("deal_count", 0)}</td>'
        f'<td class="num">{b.get("product_count", 0)}</td>'
        f'<td class="num">{len(b.get("promo", []))}</td>'
        f'<td><a href="{esc(b["official"])}" rel="nofollow noopener" target="_blank">visit</a></td>'
        "</tr>"
        for b in brands
    )
    compare_table = (
        '<table class="compare"><thead><tr>'
        "<th>Brand</th><th>Public price source</th><th>Discounts</th>"
        "<th>Prices tracked</th><th>Promo pages</th><th>Official site</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
    )
    price_source_count = sum(1 for b in brands if b.get("source", "none") != "none")
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
            "FAVICON": FAVICON,
            "BREADCRUMB": breadcrumb(base, [("Brands", None)]),
            "BRAND": esc(brand_name),
            "INITIAL": esc(initials(brand_name)),
            "NICHE": esc(dmeta.get("niche", "")),
            "BRAND_COUNT": len(brands),
            "PRICE_SOURCE_COUNT": price_source_count,
            "DEAL_COUNT": len(deals),
            "UPDATED": esc(updated),
            "COMPARE_TABLE": compare_table,
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
