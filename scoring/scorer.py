import os
import anthropic
from rubric.criteria import Rubric, DEFAULT_RUBRIC


MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are a senior engineering reviewer assessing whether a software project is ready to ship.
You will be given a rubric and project context. For each criterion, provide:
1. A score from 0–10
2. A one-sentence rationale
3. Any blocking issues (if criterion is required and score < 7)

Respond in structured JSON matching the schema:
{
  "scores": [{"criterion": str, "score": int, "rationale": str, "blocking": bool}],
  "overall_score": float,
  "recommendation": "ship" | "hold" | "conditional",
  "summary": str
}"""


class ScoringResult:
    def __init__(self, raw: str):
        import json
        self.raw = raw
        self.data = json.loads(raw)

    @property
    def recommendation(self) -> str:
        return self.data.get("recommendation", "unknown")

    @property
    def overall_score(self) -> float:
        return self.data.get("overall_score", 0.0)

    @property
    def summary(self) -> str:
        return self.data.get("summary", "")


async def score_project(context: str, rubric: Rubric = DEFAULT_RUBRIC) -> ScoringResult:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = f"{rubric.to_prompt_fragment()}\n\n---\n\nProject context:\n{context}"

    stream = client.messages.stream(
        model=MODEL,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    with stream as s:
        message = s.get_final_message()

    text_blocks = [b.text for b in message.content if hasattr(b, "text")]
    raw_json = text_blocks[-1].strip() if text_blocks else "{}"
    # Strip markdown fences if the model wraps the JSON
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]

    return ScoringResult(raw_json.strip())
