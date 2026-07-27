"""End-to-end smoke test: the full stack in fake mode, driven through the real app.

No services are monkeypatched. The only patches:
- BackgroundTasks.add_task is dropped (both variants) so the test drives the
  pipeline synchronously via direct pipeline calls instead of relying on
  BackgroundTasks execution semantics inside TestClient.
- render_pdf is stubbed in the fast (non-pdf) variant only; the @pytest.mark.pdf
  variant uses the real Playwright/Chromium renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from starlette.background import BackgroundTasks

from backend.app.services import pipeline, render
from backend.app.services.claude import ClaudeService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = PROJECT_ROOT / "backend" / "app" / "fixtures"

POSTING_URL = "https://jobs.example.com/postings/senior-backend-4471"

POSTING_HTML = """<!DOCTYPE html>
<html>
<head><title>Senior Backend Engineer - Job Posting</title></head>
<body>
<article>
  <h1>Senior Backend Engineer</h1>
  <p>We are looking for a Senior Backend Engineer to join our platform team and take
  ownership of the services that power our analytics products. You will design and
  operate Python services in production, collaborate with product engineers on API
  design, and help us keep our data pipeline fast, observable, and reliable as our
  customer base grows across three continents.</p>
  <p>In this role you will build and maintain FastAPI services backed by PostgreSQL,
  design schemas and migrations, own the reliability of asynchronous job processing,
  and instrument everything with meaningful metrics and traces. You will review code,
  mentor mid-level engineers, and participate in a humane on-call rotation with real
  influence over what pages you and what does not.</p>
  <p>Requirements: five or more years of professional software engineering experience,
  deep working knowledge of Python and at least one modern web framework such as
  FastAPI or Django, strong SQL skills, and experience deploying and operating
  services in a cloud environment with CI/CD. You write clearly and communicate
  trade-offs honestly.</p>
  <p>Nice to have: experience with React and TypeScript, Kubernetes, streaming
  systems such as Kafka, and infrastructure as code. Familiarity with data-intensive
  applications and cost-aware architecture decisions is a strong plus.</p>
  <p>We offer remote-friendly work with quarterly team onsites, a professional
  development budget, and transparent salary bands. Our interview process is four
  stages and we always tell you where you stand within two business days.</p>
</article>
</body>
</html>"""

PASTED_RESUME_TEXT = """Professional summary: backend-leaning software engineer with
production Python experience, API design, and data pipeline work.

Experience includes building web services, maintaining CI/CD pipelines, operating
SQL databases, mentoring junior engineers, and shipping developer tooling.

Skills: Python, FastAPI, SQL, Docker, TypeScript, React, testing, observability.

Education: bachelor's degree in a technical field.
"""

EXPORT_KINDS = (
    "resume.pdf",
    "resume.html",
    "resume.txt",
    "cover_letter.pdf",
    "cover_letter.txt",
)


def _reset_settings_cache() -> None:
    from backend.app import config

    cache_clear = getattr(config.get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


@pytest.fixture(autouse=True)
def _settings_cache_guard():
    """Ensure cached Settings never leak between this module's tests and others."""
    _reset_settings_cache()
    yield
    _reset_settings_cache()


def _make_app(tmp_path, monkeypatch):
    """Real create_app() in fake mode with an isolated data dir.

    BackgroundTasks.add_task is dropped so no API call runs the pipeline
    implicitly -- this test drives the pipeline synchronously and explicitly.
    """
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        BackgroundTasks, "add_task", lambda self, func, *args, **kwargs: None
    )
    _reset_settings_cache()
    from backend.app.main import create_app

    return create_app()


def _intake_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "intake.json").read_text(encoding="utf-8"))


def _tailor_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "tailor.json").read_text(encoding="utf-8"))


def _first_experience_company(tailor: dict) -> str:
    for section in tailor["resume"]["sections"]:
        if section["type"] == "experience" and section["items"]:
            return section["items"][0]["company"]
    raise AssertionError("tailor.json fixture has no experience items")


def _run_full_flow(client: TestClient, engine, claude: ClaudeService) -> int:
    """Shared flow for both variants. Returns the created application id."""
    intake = _intake_fixture()
    tailor = _tailor_fixture()

    # 1. Create a profile.
    r = client.post("/api/profiles", json={"name": "E2E Test User"})
    assert r.status_code in (200, 201), r.text
    profile_id = r.json()["id"]

    # 2. Upload a pasted source document.
    r = client.post(
        f"/api/profiles/{profile_id}/documents",
        json={"filename": "resume_notes.txt", "text": PASTED_RESUME_TEXT},
    )
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    assert doc["filename"] == "resume_notes.txt"
    assert doc["kind"] in ("paste", "txt")

    # 3. Build the master profile: the real intake path through fake Claude.
    r = client.post(f"/api/profiles/{profile_id}/build")
    assert r.status_code == 200, r.text
    built = r.json()
    assert "usage" in built
    assert built["usage"]["cost_usd"] == 0.0  # fake mode reports zero usage
    assert built["master_profile"]["experiences"], "intake produced no experiences"
    assert (
        built["master_profile"]["experiences"][0]["company"]
        == intake["master_profile"]["experiences"][0]["company"]
    )

    # 4. Batch-create ONE application. add_task is dropped, so it stays queued.
    r = client.post(
        "/api/applications/batch",
        json={
            "profile_id": profile_id,
            "jobs": [
                {"url": POSTING_URL, "depth": "standard", "template": "slate"}
            ],
        },
    )
    assert r.status_code in (200, 201), r.text
    apps = r.json()
    assert len(apps) == 1
    app_id = apps[0]["id"]
    assert apps[0]["status"] == "queued"

    # 5. Drive the pipeline synchronously. Only the posting URL is HTTP-mocked;
    # respx also fails the test if anything tries to reach the real network.
    with respx.mock:
        respx.get(POSTING_URL).mock(
            return_value=httpx.Response(200, html=POSTING_HTML)
        )
        pipeline.process_application(app_id, engine=engine, claude=claude)

    # 6. Final status: ready, version 1, content present.
    r = client.get(f"/api/applications/{app_id}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["status"] == "ready", detail.get("error_message")
    assert detail["version"] == 1
    assert detail["resume"] is not None
    assert detail["cover_letter_md"]
    assert detail["raw_text_present"] is True
    assert detail["parsed"]["company"], "parsed posting missing company"
    assert detail["stage"] == "drafted"  # saved -> drafted: the one sanctioned status/stage coupling

    # 7. Preview HTML renders the tailored resume (fixture company + contact name).
    r = client.get(f"/api/applications/{app_id}/preview")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert _first_experience_company(tailor) in r.text
    assert tailor["resume"]["contact"]["name"] in r.text

    # 8. All five export endpoints serve files.
    for kind in EXPORT_KINDS:
        r = client.get(f"/api/applications/{app_id}/exports/{kind}")
        assert r.status_code == 200, f"export {kind} -> {r.status_code}"

    # 9. ATS text starts with the fixture contact name uppercased.
    r = client.get(f"/api/applications/{app_id}/exports/resume.txt")
    assert r.status_code == 200
    assert r.text.startswith(tailor["resume"]["contact"]["name"].upper())

    # 10. Application listing shows cost fields.
    r = client.get(f"/api/applications?profile_id={profile_id}")
    assert r.status_code == 200
    rows = [row for row in r.json() if row["id"] == app_id]
    assert len(rows) == 1
    row = rows[0]
    assert "cost_usd" in row
    assert isinstance(row["cost_usd"], (int, float))
    assert row["cost_usd"] == 0.0  # fake mode
    assert row["depth"] == "standard"
    assert row["template"] == "slate"

    # 11. Regenerate with feedback bumps version to 2.
    feedback = "Emphasize the data-platform work more."
    r = client.post(
        f"/api/applications/{app_id}/regenerate", json={"feedback": feedback}
    )
    assert r.status_code in (200, 201), r.text
    # add_task is dropped, so perform the regeneration explicitly:
    pipeline.regenerate_application(app_id, feedback, engine=engine, claude=claude)
    r = client.get(f"/api/applications/{app_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["version"] == 2
    assert detail["status"] == "ready"

    return app_id


def test_e2e_fake_mode_full_flow(tmp_path, monkeypatch):
    """Fast variant: real everything except render_pdf (stubbed) and Claude (fake)."""

    def fake_render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4 stub e2e\n")

    # Patch BEFORE create_app so demo seeding at startup also uses the stub.
    monkeypatch.setattr(render, "render_pdf", fake_render_pdf)
    fastapi_app = _make_app(tmp_path, monkeypatch)
    claude = ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
    with TestClient(fastapi_app) as client:
        _run_full_flow(client, fastapi_app.state.engine, claude)


@pytest.mark.pdf
def test_e2e_real_pdf(tmp_path, monkeypatch):
    """PDF variant: same flow with the REAL Playwright renderer; asserts %PDF bytes."""
    fastapi_app = _make_app(tmp_path, monkeypatch)
    claude = ClaudeService(fake_mode=True, fixtures_dir=FIXTURES_DIR)
    with TestClient(fastapi_app) as client:
        app_id = _run_full_flow(client, fastapi_app.state.engine, claude)
        r = client.get(f"/api/applications/{app_id}/exports/resume.pdf")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF"), r.content[:16]


def test_readme_quickstart():
    readme_path = PROJECT_ROOT / "README.md"
    assert readme_path.exists(), "README.md is missing"
    readme = readme_path.read_text(encoding="utf-8")
    for needle in (
        "pip install -r requirements.txt",
        "playwright install chromium",
        "python run.py",
        "TAILORED_FAKE=1",
        "ANTHROPIC_API_KEY",
        'pytest -m "not pdf"',
        "TAILORED_PORT",
    ):
        assert needle in readme, f"README.md missing: {needle}"
