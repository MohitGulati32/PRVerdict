# This client returns mock data, not a live PagerDuty connection. PagerDuty
# requires a work email for both its standard trial and developer account
# signup, which was not available for this project. The function signature
# and return shape match the real pagerduty-mcp-server's incident-listing
# tool (status, urgency, summary fields), so swapping in a live connection
# later only requires replacing the file read with the same JSON-RPC/stdio
# pattern used in github_client.py, not restructuring anything downstream.
#
# PagerDuty has no native P0/P1/P2 concept - it only has urgency (high/low)
# and status (triggered/acknowledged/resolved). The rubric's incident_history
# criterion maps its P0/P1/P2 severities onto urgency: high is a P0/P1
# equivalent, low is a P2 equivalent. See mock_data/pagerduty_incidents.json.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_INCIDENTS_PATH = "mock_data/pagerduty_incidents.json"
RECENT_WINDOW_DAYS = 30


class IncidentClientError(Exception):
    """Raised when the mock incidents file can't be read/parsed, or an
    incident entry is missing a required field."""


def get_recent_incidents(
    service_name: str,
    incidents_path: str | Path = DEFAULT_INCIDENTS_PATH,
) -> list[dict[str, Any]]:
    """Return service_name's incidents from the last 30 days.

    Each incident is {"status": ..., "urgency": ..., "summary": ...} - the
    same fields the real pagerduty-mcp-server's incident-listing tool
    returns, so normalize.py and scoring don't need to know or care which
    one is active. Returns [] for a service not present in the file, same
    as a live PagerDuty query would for a service with no incidents.
    """
    path = Path(incidents_path)
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise IncidentClientError(f"couldn't read mock incidents file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise IncidentClientError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise IncidentClientError(f"{path} must be a mapping of service name -> incident list")

    incidents = data.get(service_name, [])

    recent: list[dict[str, Any]] = []
    for incident in incidents:
        for field in ("status", "urgency", "summary", "days_ago"):
            if field not in incident:
                raise IncidentClientError(
                    f"{path}: an incident for {service_name!r} is missing required field {field!r}"
                )
        if incident["days_ago"] <= RECENT_WINDOW_DAYS:
            recent.append({
                "status": incident["status"],
                "urgency": incident["urgency"],
                "summary": incident["summary"],
            })

    return recent
