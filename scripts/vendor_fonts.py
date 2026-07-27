"""Vendor latin-subset woff2 fonts from Google Fonts into backend/templates/fonts/.

Run once during implementation; the output is committed. There is no build step
at runtime, and the app never touches the network to render.

    ./.venv/Scripts/python.exe scripts/vendor_fonts.py

Google's css2 endpoint returns @font-face blocks already split per unicode
subset. We keep only the block commented /* latin */. Variable families serve
one identical file for every requested weight, so we dedupe by content hash and
collapse the covered weights into a single CSS weight range.

The script also regenerates `LICENSES.md`. OFL 1.1 condition 2 lets us
redistribute these binaries "provided that each copy contains the above
copyright notice and this license", so that file has to carry both, fetched
from each family's own upstream licence rather than written by hand.
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

# (css2 family query, filename stem, human family name, upstream project URL,
#  upstream licence file URL)
SPECS = [
    (
        "Inter:ital,wght@0,400..700;1,400..700",
        "Inter",
        "Inter",
        "https://github.com/rsms/inter",
        "https://raw.githubusercontent.com/rsms/inter/master/LICENSE.txt",
    ),
    (
        "IBM+Plex+Sans:ital,wght@0,400;0,600;1,400",
        "IBMPlexSans",
        "IBM Plex Sans",
        "https://github.com/IBM/plex",
        "https://raw.githubusercontent.com/IBM/plex/master/LICENSE.txt",
    ),
    (
        "IBM+Plex+Mono:wght@400;500",
        "IBMPlexMono",
        "IBM Plex Mono",
        "https://github.com/IBM/plex",
        "https://raw.githubusercontent.com/IBM/plex/master/LICENSE.txt",
    ),
    (
        "Public+Sans:ital,wght@0,400..700;1,400",
        "PublicSans",
        "Public Sans",
        "https://github.com/uswds/public-sans",
        "https://raw.githubusercontent.com/uswds/public-sans/develop/LICENSE.md",
    ),
    (
        "Source+Serif+4:ital,opsz,wght@0,8..60,400..600;1,8..60,400",
        "SourceSerif4",
        "Source Serif 4",
        "https://github.com/adobe-fonts/source-serif",
        "https://raw.githubusercontent.com/adobe-fonts/source-serif/release/LICENSE.md",
    ),
    (
        "EB+Garamond:ital,wght@0,400..600;1,400",
        "EBGaramond",
        "EB Garamond",
        "https://github.com/octaviopardo/EBGaramond12",
        "https://raw.githubusercontent.com/octaviopardo/EBGaramond12/master/OFL.txt",
    ),
    (
        "Source+Sans+3:ital,wght@0,400..600;1,400",
        "SourceSans3",
        "Source Sans 3",
        "https://github.com/adobe-fonts/source-sans",
        "https://raw.githubusercontent.com/adobe-fonts/source-sans/release/LICENSE.md",
    ),
]

# The family whose upstream file supplies the one verbatim copy of the licence
# body. All seven carry the same text (see `_canonical`), so reproducing it
# per family would be seven identical pages.
OFL_TEXT_SOURCE = "Source Serif 4"

OFL_HEADING = "SIL OPEN FONT LICENSE Version 1.1"
OFL_RULE = "-" * 59

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


def _split_licence(text: str, url: str) -> tuple[list[str], str]:
    """(copyright lines, verbatim OFL body) from one upstream licence file.

    The copyright lines are everything above the licence body that starts with
    "Copyright" - two of them for EB Garamond, one for the rest. They are read
    from upstream and never composed here: a copyright notice we made up would
    be worse than none.
    """
    normalized = text.replace("\r\n", "\n")
    marker = f"{OFL_RULE}\n{OFL_HEADING}"
    head, found, tail = normalized.partition(marker)
    if not found:
        raise SystemExit(f"{url} does not contain the OFL 1.1 text")
    # Public Sans fences its copy of the licence in a markdown code block.
    body = (marker + tail).split("\n```")[0].strip() + "\n"
    notices = [
        line.strip() for line in head.splitlines() if line.strip().startswith("Copyright")
    ]
    if not notices:
        raise SystemExit(f"{url} carries no copyright line above the OFL text")
    return notices, body


def _canonical(body: str) -> str:
    """Whitespace- and ampersand-insensitive form of a licence body.

    Used only to prove the seven upstream copies say the same thing before we
    ship one of them for all of them. They differ in two cosmetic ways and no
    others: stray trailing spaces, and whether the third heading reads
    "PERMISSION & CONDITIONS" (SIL's own wording, and the majority here) or
    "PERMISSION AND CONDITIONS" (Inter's).
    """
    return " ".join(body.replace("&", "and").split()).lower()


def _fetch_licences() -> dict[str, tuple[list[str], str]]:
    """Family name -> (copyright lines, OFL body), one HTTP GET per distinct URL."""
    by_url: dict[str, str] = {}
    licences: dict[str, tuple[list[str], str]] = {}
    for _query, _stem, family_name, _project_url, licence_url in SPECS:
        if licence_url not in by_url:
            resp = httpx.get(licence_url, headers={"User-Agent": UA}, timeout=30.0)
            resp.raise_for_status()
            by_url[licence_url] = resp.content.decode("utf-8")
        licences[family_name] = _split_licence(by_url[licence_url], licence_url)

    reference = _canonical(licences[OFL_TEXT_SOURCE][1])
    for family_name, (_notices, body) in licences.items():
        if _canonical(body) != reference:
            raise SystemExit(
                f"{family_name}'s upstream licence body differs from "
                f"{OFL_TEXT_SOURCE}'s by more than whitespace. Reproduce it "
                "separately rather than shipping one text for both."
            )
    return licences


def _licence_file(
    provenance: list[tuple[str, str]],
    licences: dict[str, tuple[list[str], str]],
) -> str:
    licence_urls = {family: url for _q, _s, family, _p, url in SPECS}
    lines = [
        "# Vendored font licences",
        "",
        "Every font in this directory is licensed under the SIL Open Font "
        "License 1.1, which permits embedding and redistribution. Condition 2 "
        "requires each copy to travel with the copyright notice and the licence "
        "itself, so both are reproduced below rather than linked.",
        "",
        "These are latin-subset `.woff2` files fetched from the Google Fonts "
        "`css2` endpoint by `scripts/vendor_fonts.py` and committed as binaries. "
        "There is no build step: the app base64-inlines them at render time so "
        "every exported HTML document is standalone. That script also generates "
        "this file; do not edit it by hand.",
        "",
        "| Family | Upstream project |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {url} |" for name, url in provenance)
    lines += ["", "## Copyright notices", ""]
    for name, _url in provenance:
        notices, _body = licences[name]
        lines.append(f"### {name}")
        lines.append("")
        lines.extend(notices)
        lines.append("")
        lines.append(f"Notice taken from {licence_urls[name]}")
        lines.append("")
    lines += [
        "## SIL Open Font License, Version 1.1",
        "",
        "Every family above ships under this licence, and their upstream files "
        "carry the same text, so it appears once here rather than seven times. "
        f"Reproduced verbatim from {licence_urls[OFL_TEXT_SOURCE]}",
        "",
        "```",
        licences[OFL_TEXT_SOURCE][1].rstrip("\n"),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    # Before any binary is overwritten: a licence we cannot fetch means we may
    # not redistribute the fonts it covers.
    licences = _fetch_licences()
    per_family: dict[str, list[dict]] = {}
    provenance: list[tuple[str, str]] = []
    total = 0

    for query, stem, family_name, project_url, _licence_url in SPECS:
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

    (FONTS_DIR / "LICENSES.md").write_text(
        _licence_file(provenance, licences), encoding="utf-8"
    )

    print(json.dumps(per_family, indent=2))
    print(f"\nTOTAL: {total / 1024:.1f} KB in {FONTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
