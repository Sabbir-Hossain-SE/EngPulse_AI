"""Sub-step 6.2 — alert routing, de-dup, suppression, and role-based digests."""

from __future__ import annotations

from datetime import datetime, timezone

from engpulse.alerts import build_digest, render_digest, route_project
from engpulse.alerts.config import AlertConfig
from engpulse.eval.harness import ephemeral_corpus_session

AS_OF = datetime(2026, 6, 14, tzinfo=timezone.utc)


def _route(config: AlertConfig | None = None):
    session = ephemeral_corpus_session()
    return route_project(session, "acme/payments", team_key="PAY", as_of=AS_OF, config=config)


def test_routing_assigns_types_owners_and_roles():
    alerts, score = _route()
    by_subject = {a.subject: a for a in alerts}

    # Knowledge risk → EM, owner = module owner.
    kr = by_subject["auth/tokens.py"]
    assert kr.type == "knowledge_risk" and kr.roles == ["EM"] and kr.owner == "dave"

    # Delivery risk on PAY-12 → EM + PM, owner = assignee.
    pay12 = by_subject["PAY-12"]
    assert pay12.type == "delivery_risk" and set(pay12.roles) == {"EM", "PM"}
    assert pay12.owner == "dave"

    # Every alert carries an action and a confidence.
    assert all(a.recommended_action and a.confidence > 0 for a in alerts)


def test_dedup_collapses_multiple_flags_on_one_subject():
    alerts, _ = _route()
    pay12 = next(a for a in alerts if a.subject == "PAY-12")
    # stale_issue + deadline_drift + re_estimation → one alert, reasons merged.
    assert set(pay12.reasons) == {"stale_issue", "deadline_drift", "re_estimation"}
    assert pay12.severity == "high"  # escalated to the max contributing severity


def test_suppression_drops_low_severity():
    # PR#1 execution alert is high (abandoned), so it survives; but a medium floor
    # should drop any purely-low alerts.
    high_floor, _ = _route(AlertConfig(min_severity="high"))
    assert all(a.severity in ("high", "critical") for a in high_floor)


def test_score_drop_emits_project_alert():
    alerts, score = _route()
    project = [a for a in alerts if a.subject == "project"]
    assert score.band == "At Risk"
    assert project and project[0].type == "delivery_risk"
    assert project[0].severity == "high"


def test_digest_filters_by_role():
    alerts, score = _route()
    em = build_digest(alerts, score, role="EM")
    ic = build_digest(alerts, score, role="IC")

    em_subjects = {a.subject for a in em.alerts}
    assert "auth/tokens.py" in em_subjects        # knowledge risk → EM
    assert "PAY-12" in em_subjects                 # delivery risk → EM
    assert all("IC" not in a.roles for a in em.alerts)

    # IC gets execution items (their stalled PR), not knowledge/delivery.
    ic_types = {a.type for a in ic.alerts}
    assert ic_types == {"execution"}

    rendered = render_digest(em)
    assert "Daily Digest — EM" in rendered
    assert "auth/tokens.py" in rendered
