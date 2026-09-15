"""Roll up score_pr()'s per-criterion scores into one ship/no-ship decision.

decide() is pure aggregation over an already-scored dict - it makes no
Claude calls and does no judging of its own, so a change in gating policy
never has to touch scoring/score.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Decision = Literal["ready", "blocked", "needs_human_review"]

_VALID_SCORES = {"pass", "fail", "needs_review"}


class GateError(Exception):
    """Raised when scores is missing a criterion's score/reasoning, or a
    criterion's score isn't one of pass/fail/needs_review."""


@dataclass(frozen=True)
class GateDecision:
    decision: Decision
    summary: str


def decide(scores: dict[str, dict[str, str]]) -> GateDecision:
    """Decide ready / blocked / needs_human_review from score_pr()'s output.

    - blocked if any criterion scored fail
    - needs_human_review if any criterion scored needs_review and none failed
    - ready only if every criterion scored pass

    Raises GateError if a criterion is missing its score or reasoning, or
    uses a score value other than pass/fail/needs_review - decide() trusts
    score_pr()'s contract and surfaces a violation of it rather than
    silently misclassifying the PR.
    """
    failing: list[tuple[str, str]] = []
    needs_review: list[tuple[str, str]] = []

    for criterion_id, result in scores.items():
        score = result.get("score")
        reasoning = result.get("reasoning")
        if score not in _VALID_SCORES:
            raise GateError(f"criterion {criterion_id!r} has an unrecognized score {score!r}")
        if not reasoning:
            raise GateError(f"criterion {criterion_id!r} is missing its reasoning")

        if score == "fail":
            failing.append((criterion_id, reasoning))
        elif score == "needs_review":
            needs_review.append((criterion_id, reasoning))

    if failing:
        decision: Decision = "blocked"
    elif needs_review:
        decision = "needs_human_review"
    else:
        decision = "ready"

    if decision == "ready":
        summary = "Every criterion passed."
    else:
        parts = []
        if failing:
            parts.append(f"Blocked: {', '.join(cid for cid, _ in failing)} failed.")
        if needs_review:
            parts.append(f"Needs review: {', '.join(cid for cid, _ in needs_review)}.")
        summary = " ".join(parts)

    return GateDecision(decision=decision, summary=summary)
