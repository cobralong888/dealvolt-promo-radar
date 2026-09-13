"""
::ILANG
[TYPE:worker][FILE:scraper.py]
::ROLE 按 .ilang/site.ilang 的配置读各品牌公开数据源，产出 data/offers.json
::BOUNDARY 只读公开 sitemap / products.json / 商品页，遵守 robots.txt，不登录不绕反爬
::NEVER 编造任何价格、原价、折扣或优惠码；字段抓不到就留空，宁可少一个字段
::NEVER 在代码里另存一份品牌清单，一切来自 site.ilang

Read public brand sources and write data/offers.json.

Deterministic by design: no model calls, no API keys, no paid runtime.
Standard library only, so GitHub Actions needs nothing but python.

Source kinds (declared per brand in .ilang/site.ilang):
  products_json     Shopify public feed, carries compare_at_price -> real discount
  sitemap_products  public product sitemap -> product pages -> JSON-LD Product/Offer
  none              no public price feed; only official site + promo links are listed
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ilang import int_meta, load_site

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

# Handles like "vn-85515" or "tr-123" are locale variants of the same store.
# The site targets en-US, so those are skipped rather than mislabeled.
LOCALE_PREFIX = re.compile(r"^[a-z]{2}-")
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)


# ---------------------------------------------------------------- http


def http_get(url, timeout=30, user_agent="", retries=2):
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent or "DealVoltPromoRadar/1.0",
                "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw.decode("utf-8", errors="replace")
        except Exception:
            if attempt == retries:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


class Robots:
    """Minimal robots.txt support: honour Disallow for '*' and for our own UA."""

    def __init__(self, body: str | None, our_ua: str):
        self.rules: list[tuple[str, str]] = []  # (agent, path)
        self.our_ua = (our_ua or "").split("/")[0].lower()
        if body:
            agent = None
            for line in body.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                low = line.lower()
                if low.startswith("user-agent:"):
                    agent = line.split(":", 1)[1].strip().lower()
                elif low.startswith("disallow:") and agent is not None:
                    path = line.split(":", 1)[1].strip()
                    self.rules.append((agent, path))

    def allowed(self, url: str) -> bool:
        path = urllib.parse.urlparse(url).path or "/"
        blocked = False
        for agent, rule in self.rules:
            if agent not in ("*", self.our_ua):
                continue
            if rule == "":
                continue
            if rule == "/" or path.startswith(rule):
                blocked = True
        return not blocked


_robots_cache: dict[str, Robots] = {}


def robots_for(url: str, timeout: int, ua: str) -> Robots:
    host = urllib.parse.urlparse(url).netloc
    if host not in _robots_cache:
        body = http_get(f"https://{host}/robots.txt", timeout=timeout, user_agent=ua, retries=1)
        _robots_cache[host] = Robots(body, ua)
    return _robots_cache[host]


# ---------------------------------------------------------------- helpers


def to_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def slugify(text: str, limit: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
    return text[:limit].strip("-") or "item"


def discount_pct(price, compare):
    """Real discount only. Returns None when we cannot prove one."""
    if price is None or compare is None:
        return None
    if compare <= 0 or price <= 0 or price >= compare:
        return None
    return int(round((compare - price) / compare * 100))


def walk_jsonld(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_jsonld(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_jsonld(item)


def extract_product_jsonld(html: str):
    """First schema.org Product in any ld+json block, with its Offer."""
    for block in LD_JSON_RE.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in walk_jsonld(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            offer = node.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            if isinstance(offer, dict) and "Offer" not in (
                offer.get("@type") if isinstance(offer.get("@type"), str) else ""
            ) and offer.get("@type") not in (None, "Offer", ["Offer"]):
                offer = {}
            return {
                "name": node.get("name"),
                "url": node.get("url") or node.get("@id"),
                "image": (node.get("image") or [None])[0]
                if isinstance(node.get("image"), list)
                else node.get("image"),
                "price": to_float(offer.get("price") or offer.get("lowPrice")),
                "currency": offer.get("priceCurrency") or offer.get("currency"),
                "availability": offer.get("availability"),
            }
    return None


# ---------------------------------------------------------------- sources


def source_products_json(brand, cfg, ctx):
    """Shopify public feed. compare_at_price > price is the only discount we claim."""
    deals, products = [], []
    body = http_get(brand["endpoint"], timeout=ctx["timeout"], user_agent=ctx["ua"])
    if not body:
        return deals, products, "endpoint_unreachable"
    try:
        payload = json.loads(body)
    except Exception:
        return deals, products, "endpoint_not_json"

    currency = cfg["meta"].get("currency", "USD")
    for product in payload.get("products", []):
        handle = product.get("handle") or ""
        if LOCALE_PREFIX.match(handle):
            continue  # locale variant, not the en-US catalogue
        title = (product.get("title") or "").strip()
        if not title:
            continue
        host = urllib.parse.urlparse(brand["official"]).netloc
        url = f"https://{host}/products/{handle}" if handle else brand["official"]
        image = None
        images = product.get("images") or []
        if images and isinstance(images[0], dict):
            image = images[0].get("src")
        for variant in product.get("variants") or []:
            price = to_float(variant.get("price"))
            compare = to_float(variant.get("compare_at_price"))
            if price is None:
                continue
            item = {
                "id": slugify(f"{brand['slug']}-{handle}-{variant.get('id', '')}"),
                "brand_slug": brand["slug"],
                "brand_name": brand["name"],
                "title": title if not variant.get("title") else f"{title} - {variant['title']}",
                "url": url,
                "image": image,
                "price": price,
                "currency": currency,
                "availability": "InStock" if variant.get("available") else "OutOfStock",
                "source_url": brand["endpoint"],
                "source_kind": "products_json",
            }
            pct = discount_pct(price, compare)
            if pct is not None and pct >= ctx["min_discount_pct"]:
                item["compare_at"] = compare
                item["discount_pct"] = pct
                deals.append(item)
            else:
                products.append(item)
            break  # one variant per product keeps the feed small and readable
    return deals, products, "ok"


def source_sitemap_products(brand, cfg, ctx):
    """Public product sitemap -> product pages -> JSON-LD Offer (price only)."""
    products = []
    body = http_get(brand["endpoint"], timeout=ctx["timeout"], user_agent=ctx["ua"])
    if not body:
        return [], products, "endpoint_unreachable"
    urls = [u.strip() for u in LOC_RE.findall(body)]
    if not urls:
        return [], products, "sitemap_empty"
    robots = robots_for(brand["official"], ctx["timeout"], ctx["ua"])

    checked = 0
    for url in urls:
        if len(products) >= ctx["max_products_per_brand"]:
            break
        if checked >= ctx["max_pages_to_fetch"]:
            break
        if not robots.allowed(url):
            continue
        checked += 1
        html = http_get(url, timeout=ctx["timeout"], user_agent=ctx["ua"], retries=1)
        if not html:
            continue
        node = extract_product_jsonld(html)
        if not node or node.get("price") is None or not node.get("name"):
            continue
        products.append(
            {
                "id": slugify(f"{brand['slug']}-{node['name']}"),
                "brand_slug": brand["slug"],
                "brand_name": brand["name"],
                "title": node["name"],
                "url": node.get("url") or url,
                "image": node.get("image"),
                "price": node["price"],
                "currency": node.get("currency") or cfg["meta"].get("currency", "USD"),
                "availability": node.get("availability"),
                "source_url": url,
                "source_kind": "sitemap_products",
            }
        )
        time.sleep(0.4)
    status = "ok" if products else "no_price_found"
    return [], products, status


def promo_label(url: str) -> str:
    tail = urllib.parse.urlparse(url).path.strip("/").split("/")[-1] or "official promo"
    return tail.replace("-", " ").title()


# ---------------------------------------------------------------- main


def main() -> int:
    cfg = load_site()
    meta = cfg["meta"]
    ctx = {
        "timeout": int_meta(cfg, "request_timeout", 30),
        "min_discount_pct": int_meta(cfg, "min_discount_pct", 1),
        "max_deals_per_brand": int_meta(cfg, "max_deals_per_brand", 12),
        "max_products_per_brand": int_meta(cfg, "max_products_per_brand", 12),
        "max_pages_to_fetch": int_meta(cfg, "max_pages_to_fetch", 10),
        "ua": meta.get("user_agent", "DealVoltPromoRadar/1.0"),
    }

    brands_out, deals, products = [], [], []
    for brand in cfg["brands"]:
        kind = (brand.get("source") or "none").strip()
        b_deals, b_products, status = [], [], "no_source"
        if kind == "products_json" and brand.get("endpoint"):
            b_deals, b_products, status = source_products_json(brand, cfg, ctx)
        elif kind == "sitemap_products" and brand.get("endpoint"):
            b_deals, b_products, status = source_sitemap_products(brand, cfg, ctx)

        b_deals = sorted(b_deals, key=lambda d: d.get("discount_pct", 0), reverse=True)
        b_deals = b_deals[: ctx["max_deals_per_brand"]]
        b_products = b_products[: ctx["max_products_per_brand"]]

        brands_out.append(
            {
                "slug": brand["slug"],
                "name": brand["name"],
                "official": brand["official"],
                "affiliate": brand.get("affiliate") or "",
                "source": kind,
                "source_status": status,
                "promo": [{"url": u, "label": promo_label(u)} for u in brand.get("promo", [])],
                "deal_count": len(b_deals),
                "product_count": len(b_products),
            }
        )
        deals.extend(b_deals)
        products.extend(b_products)
        print(
            f"[{brand['slug']:9s}] source={kind:16s} status={status:20s} "
            f"deals={len(b_deals)} products={len(b_products)}"
        )

    deals.sort(key=lambda d: (d.get("discount_pct", 0), d.get("price") or 0), reverse=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "meta": {
            "brand": meta.get("brand", "DealVolt"),
            "tagline": meta.get("tagline", ""),
            "niche": meta.get("niche", ""),
            "niche_zh": meta.get("niche_zh", ""),
            "locale": meta.get("locale", "en-US"),
            "language": meta.get("language", "en"),
            "currency": meta.get("currency", "USD"),
            "base_url": meta.get("base_url", ""),
        },
        "brands": brands_out,
        "deals": deals,
        "products": products,
    }
    out_path = os.path.join(DATA_DIR, "offers.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\nwrote {out_path}: {len(brands_out)} brands, {len(deals)} deals, {len(products)} products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
