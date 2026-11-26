"""The shared AI draft and running-build lookup that let a second device (phone) pick up work."""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.services.auto_generate import (
    AutoGenerateJob,
    PROPOSAL_TTL,
    StoredProposal,
    ai_session_store,
    job_store,
    proposal_store,
)


@pytest.fixture(autouse=True)
def fresh_session():
    asyncio.run(ai_session_store.reset())
    job_store._jobs.clear()
    yield
    asyncio.run(ai_session_store.reset())
    job_store._jobs.clear()


def test_session_starts_empty(client):
    body = client.get("/api/auto-generate/session").json()
    assert body["session"]["prompt"] == ""
    assert body["proposal"] is None
    assert body["active_job"] is None


def test_put_is_visible_to_the_next_reader_and_bumps_version(client):
    before = client.get("/api/auto-generate/session").json()["version"]
    draft = {"prompt": "90s one-hit wonders", "mode": "mixed", "project_name": "Friday", "transition_mode": "ai"}
    client.put("/api/auto-generate/session", json=draft)

    body = client.get("/api/auto-generate/session").json()
    assert body["version"] == before + 1
    assert body["session"]["prompt"] == "90s one-hit wonders"
    assert body["session"]["mode"] == "mixed"
    assert body["session"]["transition_mode"] == "ai"


def test_session_includes_its_live_proposal(client):
    proposal = StoredProposal(
        proposal_id="p-session",
        prompt="test",
        normalized_prompt="test",
        items=[],
        expires_at=datetime.utcnow() + PROPOSAL_TTL,
        mode="videos",
    )
    asyncio.run(proposal_store.save(proposal))
    client.put("/api/auto-generate/session", json={"prompt": "test", "proposal_id": "p-session"})

    body = client.get("/api/auto-generate/session").json()
    assert body["proposal"]["proposal_id"] == "p-session"
    assert body["proposal"]["mode"] == "videos"


def test_expired_proposal_is_not_returned(client):
    client.put("/api/auto-generate/session", json={"prompt": "x", "proposal_id": "gone"})
    assert client.get("/api/auto-generate/session").json()["proposal"] is None


def test_invalid_session_is_rejected(client):
    resp = client.put("/api/auto-generate/session", json={"mode": "podcasts"})
    assert resp.status_code == 422


def test_active_job_is_the_latest_running_one(client):
    assert client.get("/api/auto-generate/jobs/active").json() is None

    now = datetime.utcnow()
    done = AutoGenerateJob(job_id="done", project_id=1, total_clips=60, phase="complete", updated_at=now)
    old = AutoGenerateJob(job_id="old", project_id=2, total_clips=60, phase="processing",
                          updated_at=now - timedelta(minutes=5))
    new = AutoGenerateJob(job_id="new", project_id=3, total_clips=60, phase="rendering", updated_at=now)
    for job in (done, old, new):
        job_store._jobs[job.job_id] = job

    assert client.get("/api/auto-generate/jobs/active").json()["job_id"] == "new"
    # The session reports it too, so one request restores the whole AI screen.
    assert client.get("/api/auto-generate/session").json()["active_job"]["job_id"] == "new"
    # A real job id still resolves through the old route.
    assert client.get("/api/auto-generate/jobs/old").json()["project_id"] == 2


def test_clear_resets_the_draft(client):
    client.put("/api/auto-generate/session", json={"prompt": "something"})
    body = client.delete("/api/auto-generate/session").json()
    assert body["session"]["prompt"] == ""
