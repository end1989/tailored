from __future__ import annotations

import httpx
import pytest
import respx

from backend.app.services.fetcher import MIN_POSTING_CHARS, fetch_posting

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


# A single-page-app shell, modelled on a jobs.ashbyhq.com posting: the visible
# body is only a <noscript> notice, and the posting itself is rendered by
# JavaScript. The same page usually carries the posting as schema.org
# JobPosting JSON-LD for search engines.
SPA_SHELL = """<!doctype html>
<html>
<head>
<title>Client Partner, Emerging @ Ibotta</title>
{ld}
</head>
<body>
<noscript>You need to enable JavaScript to run this app.</noscript>
<div id="root"></div>
<script>window.__appData = {{}};</script>
</body>
</html>"""

JOB_POSTING_LD = """<script type="application/ld+json">{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Client Partner, Emerging",
  "description": "<p>Ibotta is seeking a <strong>Client Partner</strong> to join our Revenue team.</p><ul><li>Own a book of emerging brand partners and grow their annual spend.</li><li>Run quarterly business reviews with brand marketing leaders.</li></ul><p>Requirements: five or more years in client-facing sales or partnerships, comfort with Salesforce, and a record of growing accounts.</p><p>We offer a remote-friendly schedule, with an office in Denver, Colorado, for those who want one, and a benefits package that covers medical, dental, and vision.</p>",
  "hiringOrganization": {"@type": "Organization", "name": "Ibotta", "sameAs": "https://ibotta.com/"},
  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Denver", "addressRegion": "Colorado", "addressCountry": "United States"}},
  "employmentType": "FULL_TIME"
}</script>"""


def _html_response(html: str) -> httpx.Response:
    return httpx.Response(
        200, text=html, headers={"content-type": "text/html; charset=utf-8"}
    )


@respx.mock
def test_javascript_shell_without_posting_data_returns_needs_paste():
    # Regression: this shell used to count as a fetched posting, so an empty
    # "posting" was parsed, researched, and tailored against.
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld="")))
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert result.text == ""
    assert "JavaScript" in result.reason


@respx.mock
def test_javascript_shell_with_job_posting_json_ld_is_fetched_from_it():
    respx.get(JOB_URL).mock(
        return_value=_html_response(SPA_SHELL.format(ld=JOB_POSTING_LD))
    )
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert result.reason == ""
    lines = result.text.splitlines()
    assert lines[:3] == [
        "Client Partner, Emerging",
        "Ibotta",
        "Location: Denver, Colorado, United States",
    ]
    # The description arrives as HTML inside a JSON string. The markup goes,
    # but its structure stays: one line per block, list items marked, and no
    # words glued together across a tag boundary.
    assert "- Own a book of emerging brand partners and grow their annual spend." in lines
    assert any(line.startswith("Requirements:") for line in lines)
    assert "leaders.Requirements" not in result.text
    assert "comfort with Salesforce" in result.text
    assert "<" not in result.text
    assert "enable JavaScript" not in result.text


@respx.mock
def test_job_posting_json_ld_inside_a_graph_is_found():
    graph = JOB_POSTING_LD.replace(
        '{\n  "@context": "https://schema.org/",',
        '{"@context": "https://schema.org/", "@graph": [{"@type": "Organization", "name": "Ibotta"}, {',
    ).replace("</script>", "]}</script>")
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=graph)))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "Own a book of emerging brand partners" in result.text


@respx.mock
def test_json_ld_that_is_not_a_job_posting_is_ignored():
    # Career sites often ship Organization or WebSite data with a long
    # description of the company; only the @type keeps it out.
    about = "Ibotta is a performance marketing company. " * 20
    org_only = (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@type": "Organization", '
        f'"name": "Ibotta", "description": "{about}"'
        "}</script>"
    )
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=org_only)))
    assert fetch_posting(JOB_URL).status == "needs_paste"


@respx.mock
def test_malformed_json_ld_is_ignored_not_raised():
    broken = '<script type="application/ld+json">{"@type": "JobPosting", </script>'
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=broken)))
    assert fetch_posting(JOB_URL).status == "needs_paste"


@respx.mock
def test_server_rendered_posting_still_uses_page_text_over_json_ld():
    # A page that already renders its posting keeps the extraction it had;
    # JSON-LD is only the fallback for pages whose visible text is too thin.
    html = JOB_HTML.replace("</head>", JOB_POSTING_LD + "</head>")
    respx.get(JOB_URL).mock(return_value=_html_response(html))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "fleet telemetry platform" in result.text


@respx.mock
def test_html_escaped_json_ld_description_is_unescaped_to_text():
    escaped = JOB_POSTING_LD.replace("<p>", "&lt;p&gt;").replace("</p>", "&lt;/p&gt;")
    escaped = escaped.replace("<ul>", "&lt;ul&gt;").replace("</ul>", "&lt;/ul&gt;")
    escaped = escaped.replace("<li>", "&lt;li&gt;").replace("</li>", "&lt;/li&gt;")
    escaped = escaped.replace("<strong>", "&lt;strong&gt;").replace("</strong>", "&lt;/strong&gt;")
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=escaped)))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "Own a book of emerging brand partners" in result.text
    assert "<" not in result.text and "&lt;" not in result.text


@respx.mock
def test_json_ld_with_raw_newlines_inside_strings_is_still_read():
    # Strict JSON forbids a literal newline inside a string; job boards emit
    # them anyway, and a browser's JSON-LD consumers tolerate it.
    raw_newline = JOB_POSTING_LD.replace(
        "<p>Requirements:", "<p>\nRequirements:"
    )
    respx.get(JOB_URL).mock(
        return_value=_html_response(SPA_SHELL.format(ld=raw_newline))
    )
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "comfort with Salesforce" in result.text


def _ld(obj: str) -> str:
    return f'<script type="application/ld+json">{obj}</script>'


def _posting_ld(description: str, **extra: str) -> str:
    fields = {"@type": "JobPosting", "title": "Client Partner", "description": description}
    fields.update(extra)
    import json

    return _ld(json.dumps(fields))


LONG_ENOUGH = " ".join(["Own a book of emerging brand partners."] * 12)


@respx.mock
def test_a_teaser_description_in_json_ld_returns_needs_paste():
    # Some sites put only a summary in their structured data. That is no more a
    # posting than the JavaScript notice is, so it gets the same floor.
    teaser = _posting_ld("<p>See the full posting on our careers site.</p>")
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=teaser)))
    assert fetch_posting(JOB_URL).status == "needs_paste"


@respx.mock
def test_job_posting_type_given_as_a_list_is_found():
    listed = _ld(
        '{"@type": ["JobPosting"], "title": "Client Partner", '
        f'"description": "<p>{LONG_ENOUGH}</p>"}}'
    )
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=listed)))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "Own a book of emerging brand partners." in result.text


@respx.mock
def test_an_unrelated_json_ld_block_before_the_posting_is_skipped():
    breadcrumbs = _ld('{"@type": "BreadcrumbList", "itemListElement": []}')
    blocks = breadcrumbs + JOB_POSTING_LD
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=blocks)))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    assert "comfort with Salesforce" in result.text


@pytest.mark.parametrize("depth", [2000, 100_000])
@respx.mock
def test_a_pathologically_nested_json_ld_block_does_not_raise(depth):
    # json.loads raises RecursionError (not ValueError) past its own limit, and
    # a walk over a structure just under that limit recurses too deep as well.
    # Neither may escape: fetch_posting never raises. A good block after the
    # bad one is still read.
    nested = _ld("[" * depth + "]" * depth)
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=nested)))
    assert fetch_posting(JOB_URL).status == "needs_paste"
    respx.get(JOB_URL).mock(
        return_value=_html_response(SPA_SHELL.format(ld=nested + JOB_POSTING_LD))
    )
    assert fetch_posting(JOB_URL).status == "fetched"


@respx.mock
def test_a_description_the_html_parser_rejects_does_not_raise():
    # html.parser raises AssertionError on an unknown marked section.
    odd = _posting_ld(f"<p>Salary <![negotiable]> plus benefits. {LONG_ENOUGH}</p>")
    respx.get(JOB_URL).mock(return_value=_html_response(SPA_SHELL.format(ld=odd)))
    assert fetch_posting(JOB_URL).status == "needs_paste"


@respx.mock
def test_table_cells_and_definition_lists_stay_apart_and_styles_are_dropped():
    description = (
        "<style>p { color: red; }</style>"
        f"<p>{LONG_ENOUGH}</p>"
        "<table><tr><th>Salary</th><td>$150,000</td></tr>"
        "<tr><th>Location</th><td>Denver</td></tr></table>"
        "<dl><dt>Pay</dt><dd>$100k</dd></dl>"
    )
    page = SPA_SHELL.format(ld=_posting_ld(description))
    respx.get(JOB_URL).mock(return_value=_html_response(page))
    result = fetch_posting(JOB_URL)
    assert result.status == "fetched"
    lines = result.text.splitlines()
    assert "Salary $150,000" in lines
    assert "Location Denver" in lines
    assert "Pay" in lines and "$100k" in lines
    assert "color" not in result.text


LOGIN_WALL = """<!doctype html>
<html><head><title>Sign in</title></head>
<body><main>
<h1>Sign in to view this job</h1>
<p>Create a free account or sign in to see the full posting, save jobs, and
get alerts when new roles match your search. It only takes a minute.</p>
</main></body></html>"""


@respx.mock
def test_a_short_login_wall_page_returns_needs_paste():
    respx.get(JOB_URL).mock(return_value=_html_response(LOGIN_WALL))
    result = fetch_posting(JOB_URL)
    assert result.status == "needs_paste"
    assert result.text == ""


@respx.mock
def test_the_page_text_floor_is_exactly_min_posting_chars(monkeypatch):
    respx.get(JOB_URL).mock(return_value=_html_response("<html><body></body></html>"))
    monkeypatch.setattr(
        "backend.app.services.fetcher.trafilatura.extract",
        lambda *args, **kwargs: "x" * (MIN_POSTING_CHARS - 1),
    )
    assert fetch_posting(JOB_URL).status == "needs_paste"
    monkeypatch.setattr(
        "backend.app.services.fetcher.trafilatura.extract",
        lambda *args, **kwargs: "x" * MIN_POSTING_CHARS,
    )
    assert fetch_posting(JOB_URL).status == "fetched"


def test_the_floor_matches_the_figure_the_agent_guide_gives():
    from backend.mcp_ops import get_workflow_guide

    assert f"{MIN_POSTING_CHARS} characters" in get_workflow_guide()
