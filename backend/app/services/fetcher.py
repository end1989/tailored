from __future__ import annotations

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

    extracted = trafilatura.extract(resp.text, include_comments=False)
    if not extracted:
        return FetchResult(status="needs_paste", reason="no extractable text")

    return FetchResult(status="fetched", text=extracted)
