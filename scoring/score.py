"""Score a PR's normalized signal against the rubric, one criterion at a time.

Takes normalize_pr_data()'s output and scores all six criteria that have a
real data source (test_coverage, change_risk, service_criticality,
rollback_readiness, ownership, incident_history).

Each criterion gets its own Claude call: the system prompt is that
criterion's rubric text (description, data_source, pass_example,
fail_example, ambiguity_note) and nothing else, so Claude judges strictly
from the extracted signal for that one criterion rather than the whole PR
at once.
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

    owns_client = client is None
    client = client or anthropic.AsyncAnthropic()
    try:
        scores = await asyncio.gather(*(
            _score_criterion(client, criteria_by_id[cid], normalized[cid])
            for cid in TARGET_CRITERIA
        ))
    finally:
        if owns_client:
            await client.close()

    return dict(zip(TARGET_CRITERIA, scores))
