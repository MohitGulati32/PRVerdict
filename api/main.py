from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

from rubric.criteria import DEFAULT_RUBRIC, Rubric
from scoring.scorer import score_project

app = FastAPI(title="Shippable", description="LLM-powered project readiness scorer")


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
