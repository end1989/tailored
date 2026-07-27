"""The vendored woff2 binaries are committed artifacts. This test guards them.

`scripts/vendor_fonts.py` fetches these files over the network and writes
whatever comes back. `resp.raise_for_status()` only catches an HTTP error
status: a captive portal or corporate proxy that answers 200 with an HTML body
makes the script overwrite all fourteen fonts with markup, and nothing else in
the suite would notice. Until a template actually references a family, no other
test opens these files at all - and even once a manifest declares one, the
registry test only asserts `path.is_file()`, which a zero-byte or HTML-content
file satisfies. The visible symptom would be every exported PDF silently
rendering in a fallback face.

Three families (Source Serif 4, EB Garamond, Source Sans 3) are vendored ahead
of the templates that use them, so they have no other coverage whatsoever until
those templates exist.

How far the check goes: neither `brotli` nor `fonttools` is installed, and the
no-build-step constraint says they must not be, so the glyph tables cannot be
decompressed here. What can be verified without them is the woff2 header, which
is uncompressed and self-describing - signature, table count, and a total-length
field that must equal the size of the file on disk. That is enough to separate a
real font from an error page, a truncated download, or an empty file. Whether
the glyphs extract as text is covered by tests/test_pdf_extraction.py, once a
template uses the family.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from backend.app.services.render import FONTS_DIR

# Display name -> the files vendored for it. This is the roster: a font that is
# not listed here should not be in the directory, and a font listed here that is
# missing from disk is a deletion no other test would catch.
EXPECTED_FAMILIES: dict[str, tuple[str, ...]] = {
    "Inter": ("Inter-italic.woff2", "Inter-normal.woff2"),
    "IBM Plex Sans": ("IBMPlexSans-italic.woff2", "IBMPlexSans-normal.woff2"),
    "IBM Plex Mono": (
        "IBMPlexMono-400-normal.woff2",
        "IBMPlexMono-500-normal.woff2",
    ),
    "Public Sans": ("PublicSans-italic.woff2", "PublicSans-normal.woff2"),
    "Source Serif 4": ("SourceSerif4-italic.woff2", "SourceSerif4-normal.woff2"),
    "EB Garamond": ("EBGaramond-italic.woff2", "EBGaramond-normal.woff2"),
    "Source Sans 3": ("SourceSans3-italic.woff2", "SourceSans3-normal.woff2"),
}

EXPECTED_FONT_FILES = frozenset(
    name for files in EXPECTED_FAMILIES.values() for name in files
)

# Total budget for the directory, from the plan: small enough that base64
# inlining does not bloat every export, large enough for seven latin subsets.
MIN_TOTAL_BYTES = 300 * 1024
MAX_TOTAL_BYTES = 600 * 1024

# No real latin subset is this small. An HTML error page or a truncated download
# is. The header checks below catch those too; this is the cheap first signal.
MIN_FILE_BYTES = 4096

WOFF2_SIGNATURE = b"wOF2"


def _on_disk() -> set[str]:
    return {p.name for p in FONTS_DIR.glob("*.woff2")}


def _every_font_name() -> list[str]:
    """Roster union disk, so a missing file fails as a test rather than vanishing.

    Parametrising over the glob alone would turn a wiped directory into zero
    collected tests, which reads as success.
    """
    return sorted(EXPECTED_FONT_FILES | _on_disk())


def test_the_vendored_font_roster_is_exactly_what_is_on_disk():
    assert _on_disk() == set(EXPECTED_FONT_FILES)


@pytest.mark.parametrize("filename", _every_font_name())
def test_vendored_font_is_a_structurally_valid_woff2(filename):
    path = FONTS_DIR / filename
    assert path.is_file(), (
        f"{filename} is missing from {FONTS_DIR}. It is a committed binary; "
        "re-run scripts/vendor_fonts.py or restore it from git."
    )
    raw = path.read_bytes()
    assert len(raw) >= MIN_FILE_BYTES, (
        f"{filename} is only {len(raw)} bytes. A real latin subset is not this "
        "small - this is an error page, a truncated download, or an empty file."
    )
    assert raw[:4] == WOFF2_SIGNATURE, (
        f"{filename} does not start with {WOFF2_SIGNATURE!r} but with "
        f"{raw[:4]!r}. vendor_fonts.py wrote a non-font response body - most "
        "likely an HTML page from a proxy that answered 200 - into a .woff2 "
        "file. Every export using this family would silently fall back."
    )
    declared_length, num_tables = struct.unpack(">I H", raw[8:14])
    assert declared_length == len(raw), (
        f"{filename}: the woff2 header declares {declared_length} bytes but the "
        f"file is {len(raw)}. The download was truncated or the file was "
        "corrupted in transit."
    )
    assert num_tables > 0, f"{filename}: the woff2 header declares no sfnt tables"


def test_no_two_vendored_fonts_are_byte_identical():
    """Distinct files with identical bytes mean the fetch collapsed.

    A proxy serving one canned response for every request, or a script bug that
    reuses the previous family's payload, produces a directory of valid-looking
    woff2 files that are all the same face.
    """
    by_digest: dict[str, list[str]] = {}
    for name in sorted(_on_disk()):
        digest = hashlib.sha256((FONTS_DIR / name).read_bytes()).hexdigest()
        by_digest.setdefault(digest, []).append(name)
    duplicates = {d: names for d, names in by_digest.items() if len(names) > 1}
    assert not duplicates, f"identical font payloads under different names: {duplicates}"


def test_the_vendored_fonts_stay_within_their_size_budget():
    total = sum((FONTS_DIR / name).stat().st_size for name in _on_disk())
    assert MIN_TOTAL_BYTES <= total <= MAX_TOTAL_BYTES, (
        f"{total / 1024:.1f} KB of fonts; the budget is "
        f"{MIN_TOTAL_BYTES / 1024:.0f}-{MAX_TOTAL_BYTES / 1024:.0f} KB. Fonts are "
        "base64-inlined into every export, so this is per-document weight."
    )


def test_every_vendored_family_is_covered_by_the_licence_file():
    """Only SIL Open Font License families may be vendored (spec constraint).

    LICENSES.md is the provenance record shipped alongside the binaries. A font
    added to the directory without an entry here is a redistribution the repo
    cannot account for.
    """
    licences = (FONTS_DIR / "LICENSES.md").read_text(encoding="utf-8")
    assert "Open Font License" in licences
    for family in EXPECTED_FAMILIES:
        assert family in licences, (
            f"{family} is vendored but absent from LICENSES.md"
        )


def test_every_vendored_file_belongs_to_a_licensed_family():
    """The roster is keyed by family, so an unlisted file has no provenance."""
    for name in sorted(_on_disk()):
        assert name in EXPECTED_FONT_FILES, (
            f"{name} is in the fonts directory but not in EXPECTED_FAMILIES. Add "
            "it there and to LICENSES.md, or delete it - an unaccounted font "
            "binary is a licensing risk."
        )
