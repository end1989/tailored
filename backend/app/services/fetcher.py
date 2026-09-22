from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

import httpx
import trafilatura

from ..schemas import FetchResult

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Less page text than this is almost never a posting: it is a JavaScript shell
# ("You need to enable JavaScript to run this app."), a cookie notice, or an
# error page. The MCP workflow guide gives agents the same figure for the same
# judgement.
MIN_POSTING_CHARS = 400

_JSON_LD = re.compile(
    r"<script\b[^>]*\btype\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)


def fetch_posting(url: str, timeout: float = 20.0) -> FetchResult:
    """Fetch a job posting URL and extract readable text.

    Never raises: every failure mode collapses to
    FetchResult(status="needs_paste", reason=...), which the pipeline maps to
    the needs_paste flow (user pastes the posting text manually).
    """
    try:
        with httpx.Client(
            follow_redirects=True, headers=BROWSER_HEADERS, timeout=timeout
        ) as client:
            resp = client.get(url)
    except Exception as exc:  # noqa: BLE001 - any transport error -> paste flow
        return FetchResult(status="needs_paste", reason=str(exc))

    if resp.status_code != 200:
        return FetchResult(status="needs_paste", reason=f"HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type:
        return FetchResult(
            status="needs_paste",
            reason=f"unsupported content-type: {content_type or 'unknown'}",
        )

    extracted = (trafilatura.extract(resp.text, include_comments=False) or "").strip()
    if len(extracted) >= MIN_POSTING_CHARS:
        return FetchResult(status="fetched", text=extracted)

    # A page that renders its posting with JavaScript usually still carries it
    # as schema.org JobPosting data for search engines, in this same response.
    from_json_ld = _json_ld_posting_text(resp.text)
    if from_json_ld:
        return FetchResult(status="fetched", text=from_json_ld)

    if not extracted:
        return FetchResult(status="needs_paste", reason="no extractable text")
    return FetchResult(
        status="needs_paste",
        reason=(
            f"only {len(extracted)} characters of page text; the posting "
            "probably needs JavaScript to display"
        ),
    )


def _json_ld_posting_text(page: str) -> str:
    """Posting text from the first usable schema.org JobPosting, or "".

    Best effort, and it must not raise: a block that is malformed, nested past
    the recursion limit, or holds markup html.parser rejects is skipped, and a
    later block can still supply the posting.
    """
    for block in _JSON_LD.findall(page):
        try:
            for posting in _job_postings(json.loads(block, strict=False)):
                text = _posting_text(posting)
                if text:
                    return text
        except Exception:  # noqa: BLE001 - see docstring
            continue
    return ""


def _job_postings(node):
    """Every JobPosting object at the top level, in a list, or in an @graph."""
    if isinstance(node, list):
        for item in node:
            yield from _job_postings(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            yield node
        yield from _job_postings(node.get("@graph"))


def _posting_text(posting: dict) -> str:
    description = posting.get("description")
    if not isinstance(description, str):
        return ""
    if "<" not in description and "&lt;" in description:
        description = html.unescape(description)  # HTML escaped inside the JSON
    body = _html_to_text(description)
    if len(body) < MIN_POSTING_CHARS:  # a teaser is no more a posting than a shell
        return ""

    header = [_plain(posting.get("title"))]
    organization = posting.get("hiringOrganization")
    if isinstance(organization, dict):
        header.append(_plain(organization.get("name")))
    location = _location(posting.get("jobLocation"))
    if location:
        header.append(f"Location: {location}")
    return "\n".join([line for line in header if line] + ["", body])


def _location(job_location) -> str:
    places = job_location if isinstance(job_location, list) else [job_location]
    found = []
    for place in places:
        address = place.get("address") if isinstance(place, dict) else None
        if isinstance(address, dict):
            parts = [
                _plain(address.get(key))
                for key in ("addressLocality", "addressRegion", "addressCountry")
            ]
            text = ", ".join(part for part in parts if part)
        else:
            text = _plain(address)
        if text and text not in found:
            found.append(text)
    return "; ".join(found)


def _plain(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


class _TextOnly(HTMLParser):
    """Collects the text of an HTML fragment, a line per block element."""

    _BLOCKS = {
        "p", "div", "br", "ul", "ol", "li", "tr", "section", "dl", "dt", "dd",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }
    _CELLS = {"td", "th"}
    _HIDDEN = {"style", "script"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self._BLOCKS:
            self.parts.append("\n")
        elif tag in self._CELLS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)


def _html_to_text(fragment: str) -> str:
    parser = _TextOnly()
    parser.feed(fragment)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line and line != "-")
