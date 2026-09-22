"""DELETE /api/profiles/{id}/documents/{doc_id}: repairs an upload made to the
wrong person without touching the built master profile."""
from __future__ import annotations

from sqlmodel import Session, select

from backend.app.models import Profile, SourceDocument
from backend.app.schemas import Contact, MasterProfile, UsageInfo
from backend.app.services import intake, pipeline

MASTER = {
    "summary_notes": "Backend engineer.",
    "experiences": [{
        "company": "Meridian Analytics", "title": "Senior Software Engineer",
        "start": "2021-03", "end": None, "location": "Remote",
        "bullets": [{"text": "Built APIs", "tags": ["python"]}],
    }],
    "projects": [], "skills": [], "education": [], "certifications": [], "extras": [],
}


def _person(client, name="Ada") -> int:
    resp = client.post("/api/profiles", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _upload(client, pid, filename, text) -> int:
    resp = client.post(f"/api/profiles/{pid}/documents",
                       json={"filename": filename, "text": text})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_removes_the_document(client, engine):
    pid = _person(client)
    kept = _upload(client, pid, "resume.txt", "My resume")
    doomed = _upload(client, pid, "someone_else.txt", "Not my resume")

    resp = client.delete(f"/api/profiles/{pid}/documents/{doomed}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": doomed}
    docs = client.get(f"/api/profiles/{pid}").json()["documents"]
    assert [d["id"] for d in docs] == [kept]
    with Session(engine) as s:
        assert s.get(SourceDocument, doomed) is None


def test_unknown_document_is_404(client):
    pid = _person(client)

    resp = client.delete(f"/api/profiles/{pid}/documents/9999")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "document not found"


def test_another_persons_document_is_404_and_kept(client):
    ada = _person(client, "Ada")
    ben = _person(client, "Ben")
    bens_doc = _upload(client, ben, "ben.txt", "Ben's resume")

    resp = client.delete(f"/api/profiles/{ada}/documents/{bens_doc}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "document not found"
    docs = client.get(f"/api/profiles/{ben}").json()["documents"]
    assert [d["id"] for d in docs] == [bens_doc]


def test_unknown_person_is_404(client):
    resp = client.delete("/api/profiles/9999/documents/1")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "profile not found"


def test_the_master_profile_is_unchanged(client):
    pid = _person(client)
    client.put(f"/api/profiles/{pid}", json={"master_profile": MASTER})
    doc = _upload(client, pid, "resume.txt", "My resume")
    before = client.get(f"/api/profiles/{pid}").json()["master_profile"]

    assert client.delete(f"/api/profiles/{pid}/documents/{doc}").status_code == 200

    after = client.get(f"/api/profiles/{pid}").json()
    assert after["documents"] == []
    assert after["master_profile"] == before
    assert after["master_profile"]["experiences"][0]["company"] == "Meridian Analytics"


def test_the_next_build_reads_only_what_remains(client, monkeypatch):
    pid = _person(client)
    _upload(client, pid, "resume.txt", "My resume")
    doomed = _upload(client, pid, "someone_else.txt", "Not my resume")
    client.delete(f"/api/profiles/{pid}/documents/{doomed}")
    seen = {}

    def fake_build(docs, claude):
        seen["docs"] = list(docs)
        return MasterProfile(), Contact(name="Ada"), UsageInfo()

    monkeypatch.setattr(intake, "build_master_profile", fake_build)

    assert client.post(f"/api/profiles/{pid}/build").status_code == 200
    assert seen["docs"] == ["My resume"]


def test_voice_sample_falls_back_to_the_next_newest_document(client, engine):
    pid = _person(client)
    _upload(client, pid, "resume.txt", "My own writing")
    doomed = _upload(client, pid, "someone_else.txt", "Somebody else's writing")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid))[0] == "Somebody else's writing"

    client.delete(f"/api/profiles/{pid}/documents/{doomed}")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid))[0] == "My own writing"


def test_removing_the_last_document_leaves_no_voice_sample(client, engine):
    pid = _person(client)
    only = _upload(client, pid, "resume.txt", "My own writing")

    client.delete(f"/api/profiles/{pid}/documents/{only}")

    with Session(engine) as s:
        assert pipeline._voice_for(s, s.get(Profile, pid)) == (None, None)
        remaining = s.exec(
            select(SourceDocument).where(SourceDocument.profile_id == pid)
        ).all()
    assert remaining == []
