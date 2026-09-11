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
from rubric.schema import load_rubric

# incident_history isn't covered yet - it waits on incident_client.py (Phase 6).
TARGET_CRITERIA = (
    "test_coverage",
    "change_risk",
    "rollback_readiness",
    "ownership",
    "service_criticality",
)

DEFAULT_SERVICE_CRITICALITY_PATH = "rubric/service_criticality.yaml"
_TIER_RANK = {"P0": 0, "P1": 1, "P2": 2}

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


def _extract_change_risk(pull_request: dict) -> dict[str, Any]:
    # additions/deletions/changed_files use .get(..., 0), not _require: the
    # GitHub API omits these int fields entirely when they're zero (verified
    # on a real PR with 0 deletions), so a missing key here means 0, not
    # malformed data.
    return {
        "additions": pull_request.get("additions", 0),
        "deletions": pull_request.get("deletions", 0),
        "changed_files": pull_request.get("changed_files", 0),
    }


def _extract_rollback_readiness(pull_request: dict, files: list) -> dict[str, Any]:
    body = _require(pull_request, "body", "pr_snapshot['pull_request']") or ""

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

    return {
        "body": body,
        "feature_flag_keywords_in_body": _find_keywords(body),
        "feature_flag_keywords_in_diff": diff_matches,
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


def normalize_pr_data(
    pr_snapshot: dict[str, Any],
    codeowners_result: dict[str, Any],
    rubric: str | Path,
    service_criticality_path: str | Path = DEFAULT_SERVICE_CRITICALITY_PATH,
) -> dict[str, Any]:
    """Extract unscored per-criterion signal for test_coverage, change_risk,
    rollback_readiness, ownership, and service_criticality.

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

    return {
        "test_coverage": _extract_test_coverage(check_runs),
        "change_risk": _extract_change_risk(pull_request),
        "rollback_readiness": _extract_rollback_readiness(pull_request, files),
        "ownership": _extract_ownership(codeowners_result),
        "service_criticality": get_service_criticality(pr_snapshot, service_criticality_path),
    }
