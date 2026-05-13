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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHANGELOG_URL = "https://code.claude.com/docs/en/changelog"
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
DIST = ROOT / "dist"

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


def build():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching {CHANGELOG_URL}")
    html = fetch(CHANGELOG_URL)
    releases = parse_releases(html)
    print(f"Parsed {len(releases)} releases. Latest: {releases[0]['v'] if releases else 'none'}")

    if not releases:
        print("ERROR: parser returned no releases — aborting build", file=sys.stderr)
        sys.exit(1)

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
