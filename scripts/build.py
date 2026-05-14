#!/usr/bin/env python3
"""
Fetch Claude Code changelog, parse releases, and build a single-file
index.html under ./dist/ for GitHub Pages.

Run locally: python3 scripts/build.py
Run in CI:   same command — no extra deps beyond Python 3.9+.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHANGELOG_URL = "https://code.claude.com/docs/en/changelog"
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
DIST = ROOT / "dist"
TRANSLATIONS = ROOT / "translations.json"  # cache: {version: {"en": "...", "zh": "..."}}
TRANSLATE_API = "https://api.mymemory.translated.net/get"
TRANSLATE_EMAIL = "changelog-viz@example.com"  # raises free quota to 50K words/day

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "changelog-viz-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})"
)
# Block id pattern: id="2-1-140" — dot-separated version with dashes
BLOCK_ID_RE = re.compile(r'id="(\d+-\d+-\d+)"')


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    for src, dst in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
                     ("&hellip;", "..."), ("&mdash;", "—"), ("&ndash;", "–")]:
        s = s.replace(src, dst)
    s = re.sub(r"&#x?[0-9a-fA-F]+;", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_releases(html: str):
    """
    The changelog page is a Next.js render. Each release sits in a container
    div with id="X-Y-Z" (dashes). Inside, three named regions:
      data-component-part="update-label"        -> version string
      data-component-part="update-description"  -> date string
      data-component-part="update-content"      -> bullet list
    We find each id-anchored block and extract those three regions.
    """
    # Find all release block start positions, in document order.
    starts = []
    for m in BLOCK_ID_RE.finditer(html):
        starts.append((m.start(), m.group(1)))
    # Restrict to ids that look like version anchors with at least 2 dots,
    # and that have a "update-label" inside their following window
    blocks = []
    for i, (pos, vid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        chunk = html[pos:end]
        if 'data-component-part="update-label"' not in chunk:
            continue
        blocks.append((vid, chunk))

    out = []
    for vid, chunk in blocks:
        # version
        m = re.search(r'data-component-part="update-label"[^>]*>([^<]+)<', chunk)
        version = _strip_tags(m.group(1)) if m else vid.replace("-", ".")

        # date
        m = re.search(r'data-component-part="update-description"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        date_iso = None
        if m:
            md = DATE_RE.search(_strip_tags(m.group(1)))
            if md:
                date_iso = _iso(md)

        # bullets
        m = re.search(r'data-component-part="update-content"(.*?)(?=data-component-part=|$)', chunk, re.DOTALL)
        bullets = []
        if m:
            for li in re.finditer(r"<li[^>]*>(.*?)</li>", m.group(1), re.DOTALL):
                text = _strip_tags(li.group(1))
                if text:
                    bullets.append(text)

        if not date_iso or not bullets:
            continue

        out.append({
            "v": version,
            "date": date_iso,
            "count": len(bullets),
            "h": bullets[0][:140],
        })

    # newest first
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def _iso(m):
    month = MONTHS[m.group(1)]
    day = int(m.group(2))
    year = int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def translate_one(text: str) -> str | None:
    """Translate one short English string to Simplified Chinese via MyMemory.
    Returns None on failure (caller should fall back to English)."""
    if not text:
        return None
    qs = urllib.parse.urlencode({
        "q": text,
        "langpair": "en|zh-CN",
        "de": TRANSLATE_EMAIL,
    })
    url = f"{TRANSLATE_API}?{qs}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "changelog-viz/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
        rd = payload.get("responseData") or {}
        zh = (rd.get("translatedText") or "").strip()
        status = payload.get("responseStatus")
        # MyMemory sometimes returns 200 with garbage. Sanity checks:
        if not zh or status not in (200, "200"):
            return None
        if zh.lower().startswith("please") or "invalid" in zh.lower():
            return None
        return zh
    except Exception as e:
        print(f"  translate failed for {text[:60]!r}: {e}", file=sys.stderr)
        return None


def load_translations() -> dict:
    if TRANSLATIONS.exists():
        try:
            return json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_translations(cache: dict) -> None:
    # stable, human-diffable
    TRANSLATIONS.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def annotate_with_zh(releases: list, cache: dict) -> int:
    """Fill release['zh'] from cache, translating any missing entries.
    Returns number of NEW translations actually performed."""
    new_count = 0
    failures = 0
    FAIL_LIMIT = 5  # stop calling the API after this many consecutive failures
    for r in releases:
        v = r["v"]
        en = r["h"]
        slot = cache.get(v)
        if slot and slot.get("en") == en and slot.get("zh"):
            r["zh"] = slot["zh"]
            continue
        if failures >= FAIL_LIMIT:
            # API looks unhealthy — leave the rest untranslated, fall back to en
            r["zh"] = en
            continue
        zh = translate_one(en)
        if zh:
            cache[v] = {"en": en, "zh": zh}
            r["zh"] = zh
            new_count += 1
            failures = 0
            # be a polite client
            time.sleep(0.25)
        else:
            failures += 1
            r["zh"] = en  # fallback
    return new_count


def build():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching {CHANGELOG_URL}")
    html = fetch(CHANGELOG_URL)
    releases = parse_releases(html)
    print(f"Parsed {len(releases)} releases. Latest: {releases[0]['v'] if releases else 'none'}")

    if not releases:
        print("ERROR: parser returned no releases — aborting build", file=sys.stderr)
        sys.exit(1)

    cache = load_translations()
    print(f"Translation cache: {len(cache)} entries (file exists: {TRANSLATIONS.exists()})")
    new_zh = annotate_with_zh(releases, cache)
    print(f"Translated {new_zh} new headlines this run.")
    if new_zh:
        save_translations(cache)

    template = TEMPLATE.read_text(encoding="utf-8")
    data_js = "window.CHANGELOG = " + json.dumps(releases, ensure_ascii=False) + ";"
    page = template.replace('<script src="data.js"></script>',
                            f"<script>{data_js}</script>")
    # Inject a "last updated" stamp into the footer
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = page.replace("v.viz / 2026.05",
                        f"updated {stamp}")

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(page, encoding="utf-8")
    (DIST / "data.json").write_text(
        json.dumps({"updated": stamp, "releases": releases},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    # .nojekyll so GH Pages serves underscore-prefixed paths if any
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Wrote {DIST/'index.html'} ({(DIST/'index.html').stat().st_size} bytes)")


if __name__ == "__main__":
    build()
