"""Tests for the template gallery API (list + live preview)."""
from __future__ import annotations

from backend.app.services.render import TEMPLATES


def test_list_templates_returns_every_registered_template_in_order(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert [t["name"] for t in data] == list(TEMPLATES)
    for item in data:
        assert set(item.keys()) == {"name", "label", "description", "best_for"}
        assert item["label"] and item["description"] and item["best_for"]


def test_list_templates_labels_are_not_raw_ids(client):
    """The dropdowns render label, so a label equal to the id is a regression."""
    data = client.get("/api/templates").json()
    for item in data:
        assert item["label"] != item["name"]


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
