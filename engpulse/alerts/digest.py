"""Role-based digests: filter routed alerts to a recipient role and render.

A Daily Digest is the role's open alerts plus the project health line; the
Weekly report is the same shape, framed as a health report. Every alert carries
its evidence, recommended action, owner, and confidence (PRD §11).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from engpulse.alerts.config import severity_rank
from engpulse.alerts.router import Alert
from engpulse.scoring import ProjectScore


class DigestReport(BaseModel):
    role: str
    period: str            # daily | weekly
    project: str
    composite: float
    band: str
    alerts: list[Alert] = Field(default_factory=list)


def build_digest(
    alerts: list[Alert], score: ProjectScore, role: str, period: str = "daily"
) -> DigestReport:
    role_alerts = [a for a in alerts if role in a.roles]
    role_alerts.sort(key=lambda a: severity_rank(a.severity), reverse=True)
    return DigestReport(
        role=role, period=period, project=score.project,
        composite=score.composite, band=score.band, alerts=role_alerts,
    )


def render_digest(digest: DigestReport) -> str:
    title = "Weekly Project Health Report" if digest.period == "weekly" else "Daily Digest"
    lines = [
        f"# EngPulse {title} — {digest.role}",
        f"**{digest.project}** health: {digest.composite:.1f} ({digest.band})",
        "",
    ]
    if not digest.alerts:
        lines.append("_No alerts for this role._")
        return "\n".join(lines)

    for a in digest.alerts:
        owner = f" · owner: {a.owner}" if a.owner else ""
        reasons = f" (reasons: {', '.join(a.reasons)})" if a.reasons else ""
        lines.append(
            f"- **[{a.severity.upper()}] {a.type}** · {a.subject}{owner}{reasons}\n"
            f"    - action: {a.recommended_action}\n"
            f"    - confidence: {a.confidence:.2f} · evidence: {a.evidence}"
        )
    return "\n".join(lines)
