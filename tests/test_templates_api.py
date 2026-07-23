"""Tests for the template gallery API (list + live preview)."""
from __future__ import annotations

from backend.app.services.render import TEMPLATES


def test_list_templates_returns_four_in_order(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert [t["name"] for t in data] == list(TEMPLATES)
    for t in data:
        assert set(t.keys()) == {"name", "label", "description", "best_for"}


def test_preview_each_template_renders_the_sample_resume(client):
    for name in TEMPLATES:
        resp = client.get(f"/api/templates/preview/{name}")
        assert resp.status_code == 200, resp.text
        assert "<style>" in resp.text
        assert "Cascade Analytics" in resp.text


def test_preview_unknown_template_404s(client):
    resp = client.get("/api/templates/preview/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown template"
