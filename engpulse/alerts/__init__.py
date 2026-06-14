"""Alert routing & role-based digests (Module K)."""

from engpulse.alerts.config import AlertConfig, load_alert_config
from engpulse.alerts.digest import DigestReport, build_digest, render_digest
from engpulse.alerts.router import Alert, route_alerts, route_project

__all__ = [
    "AlertConfig",
    "load_alert_config",
    "Alert",
    "route_alerts",
    "route_project",
    "DigestReport",
    "build_digest",
    "render_digest",
]
