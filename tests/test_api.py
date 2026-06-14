"""Sub-step 7.1 — FastAPI endpoints over the ephemeral corpus DB (no services)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engpulse.api.deps import get_session
from engpulse.api.main import app
from engpulse.api.services import clear_caches
from engpulse.eval.harness import ephemeral_corpus_session

AS_OF = "2026-06-14"


@pytest.fixture()
def client():
    session = ephemeral_corpus_session()
    clear_caches()
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()
    clear_caches()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_projects(client):
    repos = [p["repo"] for p in client.get("/projects").json()]
    assert "acme/payments" in repos


def test_score_endpoint(client):
    resp = client.get("/score", params={"repo": "acme/payments", "team": "PAY", "as_of": AS_OF})
    body = resp.json()
    assert resp.status_code == 200
    assert body["composite"] == 70.0
    assert body["band"] == "At Risk"
    assert {s["name"] for s in body["sub_scores"]} == {
        "review_flow", "delivery", "ci_test", "knowledge"
    }


def test_alerts_endpoint_role_filter(client):
    resp = client.get("/alerts", params={
        "repo": "acme/payments", "team": "PAY", "role": "EM", "as_of": AS_OF})
    subjects = {a["subject"] for a in resp.json()["alerts"]}
    assert "auth/tokens.py" in subjects and "PAY-12" in subjects


def test_digest_endpoint(client):
    resp = client.get("/digest", params={
        "repo": "acme/payments", "team": "PAY", "role": "EM", "as_of": AS_OF})
    assert "Daily Digest — EM" in resp.json()["markdown"]


def test_knowledge_endpoint(client):
    resp = client.get("/knowledge", params={"repo": "acme/payments"})
    flagged = {f["module"] for f in resp.json()["flags"]}
    assert "auth/tokens.py" in flagged


def test_ask_endpoint_grounded(client):
    resp = client.post("/ask", json={
        "question": "who owns the auth tokens module", "repo": "acme/payments",
        "team": "PAY", "as_of": AS_OF})
    body = resp.json()
    assert body["abstained"] is False
    assert "metric:auth/tokens.py" in body["citations"]


def test_ask_endpoint_abstains(client):
    resp = client.post("/ask", json={
        "question": "what is the meaning of life", "repo": "acme/payments"})
    assert resp.json()["abstained"] is True
