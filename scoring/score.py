"""Score a PR's normalized signal against the rubric, one criterion at a time.

Takes normalize_pr_data()'s output and scores all six criteria that have a
real data source (test_coverage, change_risk, service_criticality,
rollback_readiness, ownership, incident_history).

Each criterion gets its own Claude call: the system prompt is that
criterion's rubric text (description, data_source, pass_example,
fail_example, ambiguity_note) and nothing else, so Claude judges strictly
from the extracted signal for that one criterion rather than the whole PR
at once.

rollback_readiness is the one exception to "Claude outputs the score
directly": asking it for a final pass/fail/needs_review label let it talk
itself into softening an unambiguous large-diff-no-plan case toward
needs_review whenever the diff's content looked docstring-like, even when
the rubric text said explicitly not to (see docs/pipeline_validation_batch2.md).
So Claude is only asked for two independent boolean judgments about the
diff's content and body; the final label is then computed deterministically
in code from those two booleans plus the already-computed near_zero_risk
flag, so the same signal can never produce a different label across runs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from mcp_client.normalize import TARGET_CRITERIA
from rubric.schema import RubricCriterion, load_rubric

load_dotenv()

MODEL = "claude-opus-5"


class ScoringError(Exception):
    """Raised when the rubric or normalized data is missing a required criterion,
    or Claude's response can't be validated against CriterionScore."""


class CriterionScore(BaseModel):
    score: Literal["pass", "fail", "needs_review"] = Field(
        description="pass if the signal clearly satisfies the criterion, fail if it "
        "clearly doesn't, needs_review if the signal is ambiguous or incomplete per "
        "the criterion's ambiguity_note."
    )
    reasoning: str = Field(description="One sentence explaining the score.")


def _system_prompt(criterion: RubricCriterion) -> list[dict[str, Any]]:
    text = (
        f"You are scoring one PR-readiness criterion: {criterion.name}.\n\n"
        f"Description: {criterion.description}\n\n"
        f"Data source: {criterion.data_source}\n\n"
        f"Pass example: {criterion.pass_example}\n\n"
        f"Fail example: {criterion.fail_example}\n\n"
        f"Ambiguity note: {criterion.ambiguity_note}\n\n"
        "Score strictly from the extracted signal given in the next message - "
        "do not assume data that isn't there. If the signal doesn't clearly "
        "map to the pass or fail examples above, or the ambiguity note "
        "applies, use needs_review rather than guessing."
    )
    # Static per criterion across every PR - only the user message (the
    # extracted signal) varies, so this is a clean prompt-cache breakpoint.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


async def _score_criterion(
    client: anthropic.AsyncAnthropic,
    criterion: RubricCriterion,
    signal: Any,
) -> dict[str, str]:
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        system=_system_prompt(criterion),
        messages=[{
            "role": "user",
            "content": f"Extracted signal for this PR's {criterion.name} criterion:\n\n"
            f"{json.dumps(signal, indent=2)}",
        }],
        output_format=CriterionScore,
    )

    if response.parsed_output is None:
        raise ScoringError(
            f"criterion {criterion.id!r}: no parsed output (stop_reason={response.stop_reason!r})"
        )

    try:
        validated = CriterionScore.model_validate(response.parsed_output.model_dump())
    except ValidationError as exc:
        raise ScoringError(f"criterion {criterion.id!r}: response failed validation - {exc}") from exc

    return {"score": validated.score, "reasoning": validated.reasoning}


class RollbackReadinessJudgment(BaseModel):
    content_self_evidently_reversible: bool = Field(
        description="True if the diff's content is self-evidently reversible on its "
        "face - a docstring, comment, or plain-text documentation edit with no "
        "behavioral, schema, or config impact. False for a logic change, a config "
        "tweak, or any behavior-affecting fix."
    )
    explicit_rollback_stated: bool = Field(
        description="True only if the PR body or diff actually names a real rollback "
        "mechanism - a stated rollback plan, a feature flag, or confirmation the "
        "change is purely additive/naturally reversible. False if rollback is "
        "unaddressed, or only mentioned vaguely (e.g. 'can revert if needed') "
        "without naming the actual mechanism."
    )
    reasoning: str = Field(description="One sentence explaining both judgments.")


def _rollback_readiness_system_prompt(criterion: RubricCriterion) -> list[dict[str, Any]]:
    text = (
        f"You are evaluating one PR-readiness criterion: {criterion.name}.\n\n"
        f"Description: {criterion.description}\n\n"
        f"Data source: {criterion.data_source}\n\n"
        f"Pass example: {criterion.pass_example}\n\n"
        f"Fail example: {criterion.fail_example}\n\n"
        f"Ambiguity note: {criterion.ambiguity_note}\n\n"
        "Do not output a final pass/fail/needs_review score - that label is "
        "computed deterministically in code from your two judgments below, "
        "combined with the near_zero_risk flag already present in the signal. "
        "Judge only the diff's content and body, from the extracted signal "
        "given in the next message. Do not assume data that isn't there."
    )
    # Static per criterion across every PR - only the user message (the
    # extracted signal) varies, so this is a clean prompt-cache breakpoint.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _compute_rollback_readiness_score(
    judgment: RollbackReadinessJudgment, signal: dict[str, Any]
) -> dict[str, str]:
    """Deterministically map the model's two booleans + the already-computed
    near_zero_risk flag onto a final pass/fail/needs_review label.

    - explicit_rollback_stated: pass, regardless of size or content type.
    - content_self_evidently_reversible (and no explicit plan): pass if
      near_zero_risk, needs_review otherwise - large-but-harmless content is
      never a hard fail.
    - neither true, near_zero_risk: needs_review (a process gap, not a
      confirmed-safe change, but not risky enough to block either).
    - neither true, not near_zero_risk: fail. This is the only path to fail.
    """
    near_zero_risk = signal["is_near_zero_risk"]

    if judgment.explicit_rollback_stated:
        score = "pass"
    elif judgment.content_self_evidently_reversible:
        score = "pass" if near_zero_risk else "needs_review"
    elif near_zero_risk:
        score = "needs_review"
    else:
        score = "fail"

    reasoning = (
        f"{judgment.reasoning} (content_self_evidently_reversible="
        f"{judgment.content_self_evidently_reversible}, explicit_rollback_stated="
        f"{judgment.explicit_rollback_stated}, near_zero_risk={near_zero_risk})"
    )
    return {"score": score, "reasoning": reasoning}


async def _score_rollback_readiness(
    client: anthropic.AsyncAnthropic,
    criterion: RubricCriterion,
    signal: dict[str, Any],
) -> dict[str, str]:
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        system=_rollback_readiness_system_prompt(criterion),
        messages=[{
            "role": "user",
            "content": f"Extracted signal for this PR's {criterion.name} criterion:\n\n"
            f"{json.dumps(signal, indent=2)}",
        }],
        output_format=RollbackReadinessJudgment,
    )

    if response.parsed_output is None:
        raise ScoringError(
            f"criterion {criterion.id!r}: no parsed output (stop_reason={response.stop_reason!r})"
        )

    try:
        judgment = RollbackReadinessJudgment.model_validate(response.parsed_output.model_dump())
    except ValidationError as exc:
        raise ScoringError(f"criterion {criterion.id!r}: response failed validation - {exc}") from exc

    return _compute_rollback_readiness_score(judgment, signal)


async def score_pr(
    normalized: dict[str, Any],
    rubric: str | Path,
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, dict[str, str]]:
    """Score TARGET_CRITERIA (test_coverage, change_risk, service_criticality,
    rollback_readiness, ownership, incident_history) against
    normalize_pr_data()'s output.

    Returns {criterion_id: {"score": "pass"|"fail"|"needs_review", "reasoning": str}}.
    Raises ScoringError if the rubric or normalized data is missing one of
    the target criteria, or if a response can't be validated.
    """
    criteria_by_id = {criterion.id: criterion for criterion in load_rubric(rubric)}

    missing_from_rubric = [cid for cid in TARGET_CRITERIA if cid not in criteria_by_id]
    if missing_from_rubric:
        raise ScoringError(
            f"rubric {rubric!r} is missing required criteria: {', '.join(missing_from_rubric)}"
        )

    missing_from_data = [cid for cid in TARGET_CRITERIA if cid not in normalized]
    if missing_from_data:
        raise ScoringError(
            f"normalized data is missing required criteria: {', '.join(missing_from_data)}"
        )

    async def _score_one(cid: str) -> dict[str, str]:
        criterion, signal = criteria_by_id[cid], normalized[cid]
        if cid == "rollback_readiness":
            return await _score_rollback_readiness(client, criterion, signal)
        return await _score_criterion(client, criterion, signal)

    owns_client = client is None
    client = client or anthropic.AsyncAnthropic()
    try:
        scores = await asyncio.gather(*(_score_one(cid) for cid in TARGET_CRITERIA))
    finally:
        if owns_client:
            await client.close()

    return dict(zip(TARGET_CRITERIA, scores))
