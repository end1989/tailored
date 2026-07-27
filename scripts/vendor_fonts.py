"""Vendor latin-subset woff2 fonts from Google Fonts into backend/templates/fonts/.

Run once during implementation; the output is committed. There is no build step
at runtime, and the app never touches the network to render.

    ./.venv/Scripts/python.exe scripts/vendor_fonts.py

Google's css2 endpoint returns @font-face blocks already split per unicode
subset. We keep only the block commented /* latin */. Variable families serve
one identical file for every requested weight, so we dedupe by content hash and
collapse the covered weights into a single CSS weight range.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FONTS_DIR = Path(__file__).resolve().parents[1] / "backend" / "templates" / "fonts"

# (css2 family query, filename stem, human family name, upstream project URL)
SPECS = [
    (
        "Inter:ital,wght@0,400..700;1,400..700",
        "Inter",
        "Inter",
        "https://github.com/rsms/inter",
    ),
    (
        "IBM+Plex+Sans:ital,wght@0,400;0,600;1,400",
        "IBMPlexSans",
        "IBM Plex Sans",
        "https://github.com/IBM/plex",
    ),
    (
        "IBM+Plex+Mono:wght@400;500",
        "IBMPlexMono",
        "IBM Plex Mono",
        "https://github.com/IBM/plex",
    ),
    (
        "Public+Sans:ital,wght@0,400..700;1,400",
        "PublicSans",
        "Public Sans",
        "https://github.com/uswds/public-sans",
    ),
    (
        "Source+Serif+4:ital,opsz,wght@0,8..60,400..600;1,8..60,400",
        "SourceSerif4",
        "Source Serif 4",
        "https://github.com/adobe-fonts/source-serif",
    ),
    (
        "EB+Garamond:ital,wght@0,400..600;1,400",
        "EBGaramond",
        "EB Garamond",
        "https://github.com/octaviopardo/EBGaramond12",
    ),
    (
        "Source+Sans+3:ital,wght@0,400..600;1,400",
        "SourceSans3",
        "Source Sans 3",
        "https://github.com/adobe-fonts/source-sans",
    ),
]

BLOCK = re.compile(
    r"/\*\s*(?P<subset>[a-z0-9\-]+)\s*\*/\s*@font-face\s*\{(?P<body>[^}]*)\}",
    re.IGNORECASE,
)


def _latin_faces(query: str) -> list[dict]:
    """Fetch one family's css2 and return the latin-subset faces with their bytes."""
    url = f"https://fonts.googleapis.com/css2?family={query}&display=swap"
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30.0)
    resp.raise_for_status()
    faces = []
    for match in BLOCK.finditer(resp.text):
        if match.group("subset").lower() != "latin":
            continue
        body = match.group("body")
        src = re.search(r"url\((https://[^)]+\.woff2)\)", body)
        family = re.search(r"font-family:\s*'([^']+)'", body)
        style = re.search(r"font-style:\s*([a-z]+)", body)
        weight = re.search(r"font-weight:\s*([0-9]+(?:\s+[0-9]+)?)", body)
        if src is None or family is None:
            raise SystemExit(f"unparsable @font-face for {query}:\n{body}")
        data = httpx.get(src.group(1), headers={"User-Agent": UA}, timeout=30.0)
        data.raise_for_status()
        faces.append(
            {
                "family": family.group(1),
                "style": style.group(1) if style else "normal",
                "weight": (weight.group(1) if weight else "400").strip(),
                "bytes": data.content,
            }
        )
    if not faces:
        raise SystemExit(f"no latin subset returned for {query}")
    return faces


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    per_family: dict[str, list[dict]] = {}
    provenance: list[tuple[str, str]] = []
    total = 0

    for query, stem, family_name, project_url in SPECS:
        provenance.append((family_name, project_url))
        groups: dict[str, dict] = {}
        css_family = ""
        for face in _latin_faces(query):
            css_family = face["family"]
            digest = hashlib.sha256(face["bytes"]).hexdigest()
            slot = groups.setdefault(
                f"{face['style']}:{digest}",
                {"style": face["style"], "bytes": face["bytes"], "weights": []},
            )
            slot["weights"].extend(int(p) for p in face["weight"].split())

        # Count files per style so a static family (several distinct files for
        # one style) gets weight-qualified names and a variable one does not.
        per_style: dict[str, int] = defaultdict(int)
        for slot in groups.values():
            per_style[slot["style"]] += 1

        entries = []
        for slot in groups.values():
            lo, hi = min(slot["weights"]), max(slot["weights"])
            if per_style[slot["style"]] > 1:
                filename = f"{stem}-{lo}-{slot['style']}.woff2"
            else:
                filename = f"{stem}-{slot['style']}.woff2"
            (FONTS_DIR / filename).write_bytes(slot["bytes"])
            total += len(slot["bytes"])
            entries.append(
                {
                    "family": css_family,
                    "file": filename,
                    "weight": f"{lo} {hi}" if lo != hi else str(lo),
                    "style": slot["style"],
                }
            )
        entries.sort(key=lambda e: (e["style"], e["weight"]))
        per_family[family_name] = entries

    lines = [
        "# Vendored font licences",
        "",
        "Every font in this directory is licensed under the "
        "[SIL Open Font License 1.1](https://openfontlicense.org/), which permits "
        "embedding and redistribution.",
        "",
        "These are latin-subset `.woff2` files fetched from the Google Fonts "
        "`css2` endpoint by `scripts/vendor_fonts.py` and committed as binaries. "
        "There is no build step: the app base64-inlines them at render time so "
        "every exported HTML document is standalone.",
        "",
        "| Family | Upstream project |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {url} |" for name, url in provenance)
    lines.append("")
    (FONTS_DIR / "LICENSES.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(per_family, indent=2))
    print(f"\nTOTAL: {total / 1024:.1f} KB in {FONTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
