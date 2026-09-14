import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from mcp_client.github_client import GitHubMCPClient, GitHubMCPError, check_ownership
from mcp_client.normalize import NormalizationError, normalize_pr_data
from rubric.criteria import DEFAULT_RUBRIC, Rubric
from scoring.gate import GateError, decide
from scoring.score import ScoringError, score_pr
from scoring.scorer import score_project

RUBRIC_PATH = "rubric/rubric.yaml"
UI_DIR = Path(__file__).resolve().parent.parent / "ui"

app = FastAPI(title="Shippable", description="LLM-powered PR readiness scorer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScoreRequest(BaseModel):
    context: str
    rubric: Rubric | None = None


class ScoreResponse(BaseModel):
    recommendation: str
    overall_score: float
    summary: str
    raw: dict


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest):
    rubric = req.rubric or DEFAULT_RUBRIC
    try:
        result = await score_project(context=req.context, rubric=rubric)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ScoreResponse(
        recommendation=result.recommendation,
        overall_score=result.overall_score,
        summary=result.summary,
        raw=result.data,
    )


# Accepts a full GitHub PR URL, "owner/repo#123", or "owner/repo 123" - one
# free-text field on the frontend rather than three separate inputs.
_PR_URL_RE = re.compile(r"github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)")
_OWNER_REPO_HASH_RE = re.compile(r"^(?P<owner>[^/\s#]+)/(?P<repo>[^/\s#]+)#(?P<number>\d+)$")
_OWNER_REPO_SPACE_RE = re.compile(r"^(?P<owner>[^/\s#]+)/(?P<repo>[^/\s#]+)\s+(?P<number>\d+)$")


def _parse_pr_reference(text: str) -> tuple[str, str, int]:
    text = text.strip()
    for pattern in (_PR_URL_RE, _OWNER_REPO_HASH_RE, _OWNER_REPO_SPACE_RE):
        match = pattern.search(text)
        if match:
            return match["owner"], match["repo"], int(match["number"])
    raise ValueError(
        f"couldn't parse a PR reference from {text!r} - use a GitHub PR URL, "
        "'owner/repo#123', or 'owner/repo 123'"
    )


class CheckRequest(BaseModel):
    pr: str


class CriterionResult(BaseModel):
    score: Literal["pass", "fail", "needs_review"]
    reasoning: str


class CheckResponse(BaseModel):
    repo: str
    pr_number: int
    decision: Literal["ready", "blocked", "needs_human_review"]
    summary: str
    criteria: dict[str, CriterionResult]


@app.post("/check", response_model=CheckResponse)
async def check(req: CheckRequest):
    """Run the full readiness pipeline for one PR: fetch it from GitHub,
    extract per-criterion signal, score each of the six criteria, and roll
    that up into a ship/no-ship gate decision.
    """
    try:
        owner, repo, pr_number = _parse_pr_reference(req.pr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        async with GitHubMCPClient() as client:
            pr_snapshot = await client.get_pr_snapshot(owner, repo, pr_number)
            codeowners_content = await client.get_codeowners(owner, repo)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"missing required env var: {exc}")
    except GitHubMCPError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub MCP error: {exc}")

    codeowners_result = check_ownership(pr_snapshot, codeowners_content)

    try:
        normalized = normalize_pr_data(pr_snapshot, codeowners_result, RUBRIC_PATH)
    except NormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        scores = await score_pr(normalized, RUBRIC_PATH)
    except ScoringError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    try:
        gate_decision = decide(scores)
    except GateError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return CheckResponse(
        repo=f"{owner}/{repo}",
        pr_number=pr_number,
        decision=gate_decision.decision,
        summary=gate_decision.summary,
        criteria=scores,
    )


@app.get("/")
async def root():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")
