from pydantic import BaseModel
from typing import Any


class Criterion(BaseModel):
    name: str
    description: str
    weight: float = 1.0
    required: bool = False


class Rubric(BaseModel):
    name: str
    criteria: list[Criterion]

    def to_prompt_fragment(self) -> str:
        lines = [f"Rubric: {self.name}", ""]
        for c in self.criteria:
            req = " [REQUIRED]" if c.required else ""
            lines.append(f"- {c.name}{req} (weight {c.weight}): {c.description}")
        return "\n".join(lines)


DEFAULT_RUBRIC = Rubric(
    name="Default Shippability Rubric",
    criteria=[
        Criterion(
            name="Functionality",
            description="Core features work correctly and meet the stated requirements.",
            weight=2.0,
            required=True,
        ),
        Criterion(
            name="Test coverage",
            description="Critical paths have automated tests; no obvious gaps.",
            weight=1.5,
        ),
        Criterion(
            name="Documentation",
            description="Public APIs, setup steps, and key decisions are documented.",
            weight=1.0,
        ),
        Criterion(
            name="Security",
            description="No obvious vulnerabilities; secrets are not hard-coded.",
            weight=1.5,
            required=True,
        ),
        Criterion(
            name="Observability",
            description="Errors are logged; the service can be monitored in production.",
            weight=1.0,
        ),
    ],
)
