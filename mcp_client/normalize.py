"""Extract raw, unscored signal for the rubric criteria from a PR snapshot.

normalize_pr_data() turns mcp_client.github_client's get_pr_snapshot() /
check_ownership() output into the per-criterion inputs the scorer will
eventually judge. It deliberately does no judging itself - no pass/fail,
no score - only extraction, so a change in scoring logic never has to
touch this file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from mcp_client.github_client import _codeowners_pattern_to_regex
from mcp_client.incident_client import get_recent_incidents
from rubric.schema import load_rubric

TARGET_CRITERIA = (
    "test_coverage",
    "change_risk",
    "rollback_readiness",
    "ownership",
    "service_criticality",
    "incident_history",
)

DEFAULT_SERVICE_CRITICALITY_PATH = "rubric/service_criticality.yaml"
_TIER_RANK = {"P0": 0, "P1": 1, "P2": 2}

# rollback_readiness's near-zero-risk threshold: total changed lines at or
# under this, on one of these tiers, counts as near-zero risk. Chosen as 20
# rather than a stricter 10 after comparing both against the 20-PR
# validation set (docs/pipeline_validation_batch2.md): at 10, a 17-line
# backward-compatible .d.ts interface addition (vscode#289457) and a
# 20-line dependency-security bump (langgraph#8449) both landed on a hard
# fail purely for lacking a stated rollback sentence, which is stricter
# than how a human reviewer would actually triage either PR. Raising the
# threshold only ever softens fail to needs_review, never to pass - the
# pass path via near_zero_risk still requires content_self_evidently_reversible
# to be true independently - so widening this bucket doesn't risk silently
# clearing a change that's actually risky, only avoids auto-blocking one
# that isn't self-evidently safe but also isn't large either.
_NEAR_ZERO_RISK_MAX_CHANGED_LINES = 20
_NON_CRITICAL_TIERS = ("unmatched", "P2")

_COVERAGE_NAME_HINTS = ("coverage", "codecov", "coveralls")
_TEST_NAME_HINTS = ("test",)


def _matches_any_hint(name: str, hints: tuple[str, ...]) -> bool:
    # \b before, not after, so "test", "tests", "testing", "unit-test" all
    # match but "latest" (which contains "test" as a raw substring) doesn't.
    lowered = name.lower()
    return any(re.search(rf"\b{re.escape(hint)}", lowered) for hint in hints)

_FEATURE_FLAG_KEYWORDS = (
    "feature flag",
    "feature-flag",
    "featureflag",
    "feature_flag",
    "launchdarkly",
    "unleash",
    "flagsmith",
    "split.io",
    "rollout flag",
)


class NormalizationError(Exception):
    """Raised when pr_snapshot, codeowners_result, or rubric is missing an expected field."""


def _require(data: Any, key: str, context: str) -> Any:
    if not isinstance(data, dict):
        raise NormalizationError(f"{context} must be a dict, got {type(data).__name__}")
    if key not in data:
        raise NormalizationError(f"{context} is missing required field '{key}'")
    return data[key]


def _find_keywords(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({kw for kw in _FEATURE_FLAG_KEYWORDS if kw in lowered})


def _added_lines(patch: str) -> str:
    """Join the lines a patch actually adds (drop the +++ file header and context/removed lines)."""
    return "\n".join(
        line[1:] for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _extract_test_coverage(check_runs: dict) -> dict[str, Any]:
    runs = _require(check_runs, "check_runs", "pr_snapshot['check_runs']")

    test_suite_check_runs = []
    coverage_check_runs = []
    for run in runs:
        name = _require(run, "name", "pr_snapshot['check_runs']['check_runs'][*]")
        entry = {
            "name": name,
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
        }
        if _matches_any_hint(name, _COVERAGE_NAME_HINTS):
            coverage_check_runs.append(entry)
        elif _matches_any_hint(name, _TEST_NAME_HINTS):
            test_suite_check_runs.append(entry)

    # Lists, not a single value: a repo can run more than one test-suite job
    # (unit, integration, ...) or more than one coverage check (patch,
    # project, ...), and collapsing them here would be a scoring judgment,
    # not extraction.
    return {
        "test_suite_check_runs": test_suite_check_runs,
        "coverage_check_runs": coverage_check_runs,
    }


def _extract_change_risk(pull_request: dict, service_criticality: dict[str, Any]) -> dict[str, Any]:
    # additions/deletions/changed_files use .get(..., 0), not _require: the
    # GitHub API omits these int fields entirely when they're zero (verified
    # on a real PR with 0 deletions), so a missing key here means 0, not
    # malformed data.
    #
    # service_criticality's tier/matched_files are included here too - the
    # rubric's data_source for this criterion explicitly calls for diff
    # stats cross-referenced against the criticality config, so the scoring
    # prompt needs both, not raw size alone.
    return {
        "additions": pull_request.get("additions", 0),
        "deletions": pull_request.get("deletions", 0),
        "changed_files": pull_request.get("changed_files", 0),
        "service_criticality_tier": service_criticality["tier"],
        "service_criticality_matched_files": service_criticality["matched_files"],
    }


def _extract_rollback_readiness(
    pull_request: dict, files: list, change_risk: dict[str, Any]
) -> dict[str, Any]:
    # body uses .get(..., ""), not _require: the GitHub API (via the MCP
    # server) omits this field entirely when it's empty, the same
    # omitempty pattern already handled for additions/deletions/changed_files
    # in _extract_change_risk (verified on a real PR with no body).
    body = pull_request.get("body") or ""

    diff_matches: dict[str, list[str]] = {}
    for file_entry in files:
        filename = _require(file_entry, "filename", "pr_snapshot['files'][*]")
        patch = file_entry.get("patch")
        if not patch:
            # GitHub omits patch for binary files and very large diffs;
            # that's a legitimate absence, not malformed data.
            continue
        matches = _find_keywords(_added_lines(patch))
        if matches:
            diff_matches[filename] = matches

    # is_near_zero_risk is computed here, in code, from change_risk's diff
    # size and service tier - not left for the model to eyeball from raw
    # numbers in prose. Handing the model additions/deletions directly and
    # asking it to judge "is this small" produced inconsistent fail vs.
    # needs_review calls across near-identical diffs (see
    # docs/pipeline_validation_batch2.md); a single boolean, computed once,
    # can't be miscategorized by size regardless of what the diff contains.
    total_changed_lines = change_risk["additions"] + change_risk["deletions"]
    is_near_zero_risk = (
        total_changed_lines <= _NEAR_ZERO_RISK_MAX_CHANGED_LINES
        and change_risk["service_criticality_tier"] in _NON_CRITICAL_TIERS
    )

    return {
        "body": body,
        "feature_flag_keywords_in_body": _find_keywords(body),
        "feature_flag_keywords_in_diff": diff_matches,
        "is_near_zero_risk": is_near_zero_risk,
    }


def _extract_ownership(codeowners_result: dict) -> dict[str, Any]:
    context = "codeowners_result"
    return {
        "matched_owners": _require(codeowners_result, "matched_owners", context),
        "approving_reviewers": _require(codeowners_result, "approving_reviewers", context),
        "is_owned": _require(codeowners_result, "is_owned", context),
    }


def get_service_criticality(
    pr_snapshot: dict[str, Any],
    service_criticality_path: str | Path = DEFAULT_SERVICE_CRITICALITY_PATH,
) -> dict[str, Any]:
    """Match a PR's changed files against the service-criticality config.

    The config is a flat {pattern: tier} mapping (rubric/service_criticality.yaml).
    Patterns are matched with the same gitignore-style matcher CODEOWNERS
    uses (github_client._codeowners_pattern_to_regex) rather than a
    second, separate implementation. Returns the highest-severity tier
    matched across all touched files (P0 > P1 > P2), or "unmatched" if no
    touched file matches any config entry - never a default tier, since an
    unclassified service should never silently read as low-risk.
    """
    files = _require(pr_snapshot, "files", "pr_snapshot")

    path = Path(service_criticality_path)
    try:
        config = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise NormalizationError(f"couldn't read service criticality config {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise NormalizationError(f"{path} must be a mapping of pattern -> tier")

    rules = []
    for pattern, tier in config.items():
        if tier not in _TIER_RANK:
            raise NormalizationError(
                f"{path}: entry {pattern!r} has unrecognized tier {tier!r} "
                f"(expected one of {sorted(_TIER_RANK)})"
            )
        rules.append((pattern, tier, _codeowners_pattern_to_regex(pattern)))

    matches: list[dict[str, str]] = []
    for file_entry in files:
        filename = _require(file_entry, "filename", "pr_snapshot['files'][*]")
        for pattern, tier, regex in rules:
            if regex.match(filename):
                matches.append({"filename": filename, "pattern": pattern, "tier": tier})

    if not matches:
        return {"tier": "unmatched", "matched_files": []}

    highest_tier = min((m["tier"] for m in matches), key=lambda t: _TIER_RANK[t])
    return {"tier": highest_tier, "matched_files": matches}


def _service_name_from_pattern(pattern: str) -> str:
    """Derive a bare service name from a service_criticality.yaml pattern.

    Patterns are directory-anchored paths like "services/payments-api/";
    the service name is the final path segment, "payments-api", which is
    also how incident_client.py's mock PagerDuty data is keyed.
    """
    return pattern.rstrip("/").rsplit("/", 1)[-1]


def _extract_incident_history(service_criticality: dict[str, Any]) -> dict[str, Any]:
    """Look up recent incidents for whichever service the PR's touched files
    matched in service_criticality.yaml - the same match that determines
    change_risk's tier also determines which service to query here, so
    there's no separate path-matching logic to keep in sync.

    A PR that touched no known service (tier "unmatched") has no service to
    query, so this returns no incidents rather than guessing one.
    """
    matched_files = service_criticality["matched_files"]
    if not matched_files:
        return {"service_name": None, "incidents": []}

    tier = service_criticality["tier"]
    matched = next(m for m in matched_files if m["tier"] == tier)
    service_name = _service_name_from_pattern(matched["pattern"])
    return {
        "service_name": service_name,
        "incidents": get_recent_incidents(service_name),
    }


def normalize_pr_data(
    pr_snapshot: dict[str, Any],
    codeowners_result: dict[str, Any],
    rubric: str | Path,
    service_criticality_path: str | Path = DEFAULT_SERVICE_CRITICALITY_PATH,
) -> dict[str, Any]:
    """Extract unscored per-criterion signal for test_coverage, change_risk,
    rollback_readiness, ownership, service_criticality, and incident_history.

    `rubric` is a path to rubric.yaml, loaded via rubric.schema.load_rubric()
    so this stays honest to whatever the rubric currently defines - if one
    of the target criteria has been renamed or removed there, that's a real
    integration break and raises rather than silently dropping it.
    """
    criterion_ids = {criterion.id for criterion in load_rubric(rubric)}
    missing_criteria = [cid for cid in TARGET_CRITERIA if cid not in criterion_ids]
    if missing_criteria:
        raise NormalizationError(
            f"rubric {rubric!r} is missing required criteria: {', '.join(missing_criteria)}"
        )

    pull_request = _require(pr_snapshot, "pull_request", "pr_snapshot")
    check_runs = _require(pr_snapshot, "check_runs", "pr_snapshot")
    files = _require(pr_snapshot, "files", "pr_snapshot")

    service_criticality = get_service_criticality(pr_snapshot, service_criticality_path)
    change_risk = _extract_change_risk(pull_request, service_criticality)

    return {
        "test_coverage": _extract_test_coverage(check_runs),
        "change_risk": change_risk,
        "rollback_readiness": _extract_rollback_readiness(pull_request, files, change_risk),
        "ownership": _extract_ownership(codeowners_result),
        "service_criticality": service_criticality,
        "incident_history": _extract_incident_history(service_criticality),
    }
