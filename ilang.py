"""
::ILANG
[TYPE:lib][FILE:ilang.py]
::ROLE 解析 .ilang/site.ilang，输出 dict 给 scraper.py 与 build.py
::BOUNDARY 只做解析，不做网络请求，不做渲染，不写入任何文件
::NEVER 在这里硬编码任何品牌清单，品牌只来自 site.ilang

Minimal I-Lang config reader.

Reads .ilang/site.ilang and returns a plain dict:

    {
      "meta":   {key: str, ...},
      "render": {key: str, ...},
      "brands": [ {key: str or list, ...}, ... ]
    }

Block syntax:
    ::META            opens a block
    key: value        one entry per line, '#' starts a comment
    ::END             closes the block

A repeated key inside a block becomes a list (used for `promo:`).
There is no other source of truth: scraper.py and build.py both call
load_site() and must not keep their own copy of the brand list.
"""

from __future__ import annotations

import os
import re

BLOCK_OPEN = re.compile(r"^::(META|RENDER|BRAND)\s*$")
BLOCK_CLOSE = re.compile(r"^::END\s*$")
ENTRY = re.compile(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$")

REQUIRED_BRAND_KEYS = ("slug", "name", "official", "source")


def _strip_comment(line: str) -> str:
    # '#' only starts a comment at the beginning of a (trimmed) line,
    # so URLs containing '#' stay intact.
    stripped = line.strip()
    if stripped.startswith("#"):
        return ""
    return line.rstrip("\n")


def load_site(path: str | None = None) -> dict:
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, ".ilang", "site.ilang")
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()

    meta: dict = {}
    render: dict = {}
    brands: list = []
    current: dict | None = None
    current_name: str | None = None

    for raw_line in raw.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        m = BLOCK_OPEN.match(line)
        if m:
            current_name = m.group(1)
            current = {}
            continue

        if BLOCK_CLOSE.match(line):
            if current_name == "BRAND" and current is not None:
                missing = [k for k in REQUIRED_BRAND_KEYS if not current.get(k)]
                if missing:
                    raise ValueError(
                        "brand block missing required key(s): %s -> %r"
                        % (", ".join(missing), current)
                    )
                for key in ("promo",):
                    if key not in current:
                        current[key] = []
                    elif isinstance(current[key], str):
                        current[key] = [current[key]] if current[key] else []
                current.setdefault("endpoint", "")
                current.setdefault("affiliate", "")
                brands.append(current)
            elif current_name == "META" and current is not None:
                meta = current
            elif current_name == "RENDER" and current is not None:
                render = current
            current = None
            current_name = None
            continue

        if current is None:
            continue

        m = ENTRY.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key in current:
            if isinstance(current[key], list):
                if value:
                    current[key].append(value)
            else:
                current[key] = [current[key], value] if value else [current[key]]
        else:
            current[key] = value

    if not brands:
        raise ValueError("no ::BRAND block parsed from %s" % path)

    return {"meta": meta, "render": render, "brands": brands}


def int_meta(cfg: dict, key: str, default: int) -> int:
    try:
        return int(cfg["meta"].get(key, default))
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    import json

    print(json.dumps(load_site(), indent=2, ensure_ascii=False))
