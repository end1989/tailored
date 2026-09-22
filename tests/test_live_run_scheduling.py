"""The live-run registry covers the whole life of a scheduled pipeline run:
from the moment a route schedules it until the task has finished, counted per
application id so overlapping runs on one id each hold it live. A deleted
row's id is reissued by SQLite, so a delete that slips past a pending or
running run would let that run write into a different application."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from backend.app.services import pipeline


def _person(client, name="Ada") -> int:
    resp = client.post("/api/profiles", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _saved_application(client, profile_id) -> int:
    resp = client.post("/api/applications/batch", json={
        "profile_id": profile_id, "generate": False,
        "jobs": [{"url": "https://jobs.example.com/posting"}],
    })
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


# --- reference counting (finding 2) ----------------------------------------


def test_nested_runs_on_one_id_keep_it_live_until_both_exit():
    with pipeline.live_run(4301):
        with pipeline.live_run(4301):
            assert pipeline.is_live(4301)
        assert pipeline.is_live(4301)
        assert 4301 in pipeline.live_application_ids()
    assert not pipeline.is_live(4301)
    assert 4301 not in pipeline.live_application_ids()


def test_the_first_of_two_overlapping_runs_to_finish_does_not_release_the_other():
    first, second = pipeline.live_run(4302), pipeline.live_run(4302)
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)  # the run that started first ends first
    assert pipeline.is_live(4302)
    assert 4302 in pipeline.live_application_ids()
    second.__exit__(None, None, None)
    assert not pipeline.is_live(4302)
    assert 4302 not in pipeline.live_application_ids()


def test_a_raise_in_the_inner_run_releases_only_that_run():
    with pipeline.live_run(4303):
        with pytest.raises(RuntimeError):
            with pipeline.live_run(4303):
                raise RuntimeError("inner")
        assert pipeline.is_live(4303)
    assert not pipeline.is_live(4303)


def test_a_raise_in_the_outer_run_releases_only_that_run():
    with pytest.raises(RuntimeError):
        with pipeline.live_run(4304):
            with pipeline.live_run(4304):
                pass
            assert pipeline.is_live(4304)
            raise RuntimeError("outer")
    assert not pipeline.is_live(4304)
    assert 4304 not in pipeline.live_application_ids()


# --- schedule_run (finding 1) ----------------------------------------------


def test_schedule_run_holds_the_id_live_from_scheduling_until_the_task_ends():
    tasks = BackgroundTasks()
    seen = []

    def work(app_id, text):
        seen.append((app_id, text, pipeline.is_live(app_id)))

    pipeline.schedule_run(tasks, work, 4310, "posting text")
    assert pipeline.is_live(4310)  # scheduled, not started
    assert seen == []

    asyncio.run(tasks())
    assert seen == [(4310, "posting text", True)]
    assert not pipeline.is_live(4310)


def test_schedule_run_releases_the_id_when_the_task_raises():
    tasks = BackgroundTasks()

    def work(app_id):
        raise RuntimeError("boom")

    pipeline.schedule_run(tasks, work, 4311)
    assert pipeline.is_live(4311)
    with pytest.raises(RuntimeError):
        asyncio.run(tasks())
    assert not pipeline.is_live(4311)


def test_schedule_run_and_the_entry_points_own_registration_nest():
    tasks = BackgroundTasks()
    seen = []

    @pipeline._registers_live_run
    def entry_point(app_id):
        seen.append(pipeline.is_live(app_id))

    pipeline.schedule_run(tasks, entry_point, 4312)
    asyncio.run(tasks())
    assert seen == [True]
    assert not pipeline.is_live(4312)


# --- every scheduling endpoint registers before its task runs --------------


ENDPOINTS = {
    # name: (pipeline function the route schedules, request builder)
    "batch": ("process_application", lambda c, pid, aid: c.post(
        "/api/applications/batch",
        json={"profile_id": pid, "jobs": [{"url": "https://jobs.example.com/b"}]})),
    "paste": ("resume_after_paste", lambda c, pid, aid: c.post(
        f"/api/applications/{aid}/paste", json={"text": "posting text"})),
    "regenerate": ("regenerate_application", lambda c, pid, aid: c.post(
        f"/api/applications/{aid}/regenerate", json={"feedback": "shorter"})),
    "retry": ("process_application", lambda c, pid, aid: c.post(
        f"/api/applications/{aid}/retry")),
    "generate": ("process_application", lambda c, pid, aid: c.post(
        f"/api/applications/{aid}/generate")),
}


@pytest.fixture
def stubbed_pipeline(monkeypatch):
    """Replace the three entry points with stubs that record whether their id
    is live while they run. The stubs do not register themselves, so what they
    see is the route's own registration."""
    state = {"seen": [], "raise": False}

    def make(name):
        def stub(app_id, *args, **kwargs):
            state["seen"].append((name, app_id, pipeline.is_live(app_id)))
            if state["raise"]:
                raise RuntimeError(f"{name} failed")
        return stub

    for name in ("process_application", "resume_after_paste",
                 "regenerate_application"):
        monkeypatch.setattr(pipeline, name, make(name))
    return state


@pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
def test_each_scheduling_endpoint_registers_the_id_before_its_task_runs(
        client, stubbed_pipeline, endpoint):
    func_name, send = ENDPOINTS[endpoint]
    pid = _person(client)
    aid = _saved_application(client, pid)

    resp = send(client, pid, aid)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()[0]["id"] if endpoint == "batch" else aid

    assert stubbed_pipeline["seen"] == [(func_name, run_id, True)]
    assert not pipeline.is_live(run_id)


@pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
def test_each_scheduling_endpoint_releases_the_id_when_its_task_raises(
        app, stubbed_pipeline, endpoint):
    func_name, send = ENDPOINTS[endpoint]
    client = TestClient(app, raise_server_exceptions=False)
    pid = _person(client)
    aid = _saved_application(client, pid)
    stubbed_pipeline["raise"] = True

    resp = send(client, pid, aid)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()[0]["id"] if endpoint == "batch" else aid

    assert stubbed_pipeline["seen"] == [(func_name, run_id, True)]
    assert not pipeline.is_live(run_id)


# --- single-application delete refuses a live id ---------------------------


def test_delete_is_refused_while_a_run_holds_the_id(client):
    aid = _saved_application(client, _person(client))

    with pipeline.live_run(aid):
        resp = client.delete(f"/api/applications/{aid}")
        assert resp.status_code == 409, resp.text
        assert "wait for it to finish" in resp.json()["detail"]
        assert client.get(f"/api/applications/{aid}").status_code == 200

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": aid}


def test_delete_is_refused_between_scheduling_and_the_task_starting(client):
    aid = _saved_application(client, _person(client))
    tasks = BackgroundTasks()
    pipeline.schedule_run(tasks, lambda app_id: None, aid)

    resp = client.delete(f"/api/applications/{aid}")
    assert resp.status_code == 409, resp.text
    assert "wait for it to finish" in resp.json()["detail"]

    asyncio.run(tasks())
    assert client.delete(f"/api/applications/{aid}").status_code == 200
