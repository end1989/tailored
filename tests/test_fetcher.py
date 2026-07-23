from __future__ import annotations

import httpx
import pytest
import respx

from backend.app.services.fetcher import fetch_posting

JOB_URL = "https://jobs.example.com/senior-backend"

JOB_HTML = """<!doctype html>
<html>
<head><title>Senior Backend Engineer - Acme Robotics</title></head>
<body>
<header><nav>Home | Careers | About</nav></header>
<main>
<article>
<h1>Senior Backend Engineer</h1>
<p>Acme Robotics builds the fleet telemetry platform that keeps thousands of
warehouse robots moving. We are hiring a Senior Backend Engineer to own our
ingestion pipeline end to end, from device firmware payloads to the analytics
API our customers rely on every day.</p>
<p>You will design and operate Python services with FastAPI, model data in
PostgreSQL, and deploy to AWS with infrastructure as code. You will mentor two
junior engineers and help shape our engineering culture as the team doubles
over the next year.</p>
<p>Requirements: five or more years of professional Python experience, deep
knowledge of FastAPI or Django, strong SQL and PostgreSQL skills, and
production experience operating services on AWS.</p>
<p>Nice to have: Kubernetes, Terraform, Kafka, and prior robotics or IoT
experience. We offer a hybrid schedule out of Portland, Oregon.</p>
</article>
</main>
<footer>Copyright Acme Robotics</footer>
</body>
</html>"""


@respx.mock
def test_200_html_returns_fetched_with_extracted_text():
    respx.get(JOB_URL).mock(
        return_value=httpx.Response(
            200, text=JOB_HTML, headers={"content-type": "text/html; charset=utf-8"}
        )
    )
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "fleet telemetry platform" in result.text
    assert result.reason == ""


@respx.mock
def test_403_returns_needs_paste_with_http_reason():
    respx.get(JOB_URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert result.reason == "HTTP 403"
    assert result.text == ""


@respx.mock
def test_connect_error_returns_needs_paste():
    respx.get(JOB_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert "connection refused" in result.reason


@respx.mock
def test_200_empty_body_returns_needs_paste_no_extractable_text():
    respx.get(JOB_URL).mock(
        return_value=httpx.Response(
            200, text="", headers={"content-type": "text/html"}
        )
    )
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert result.reason == "no extractable text"


@respx.mock
def test_200_non_html_content_type_returns_needs_paste():
    respx.get(JOB_URL).mock(
        return_value=httpx.Response(
            200, text='{"jobs": []}', headers={"content-type": "application/json"}
        )
    )
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert result.reason.startswith("unsupported content-type:")
