from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator


class RubricCriterion(BaseModel):
    id: str
    name: str
    description: str
    data_source: str
    pass_example: str
    fail_example: str
    ambiguity_note: str

    @field_validator("*", mode="before")
    @classmethod
    def not_empty(cls, value, info):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{info.field_name}' must be a non-empty string")
        return value


class RubricLoadError(Exception):
    pass


def load_rubric(path: str | Path) -> list[RubricCriterion]:
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
        raise RubricLoadError(f"{path}: expected a top-level 'criteria' list")

    criteria: list[RubricCriterion] = []
    for index, entry in enumerate(data["criteria"]):
        raw_id = entry.get("id") if isinstance(entry, dict) else None
        label = raw_id if isinstance(raw_id, str) and raw_id.strip() else f"index {index}"

        try:
            criteria.append(RubricCriterion.model_validate(entry))
        except ValidationError as exc:
            field_errors = "; ".join(
                f"field '{'.'.join(str(p) for p in err['loc'])}': {err['msg']}"
                for err in exc.errors()
            )
            raise RubricLoadError(
                f"{path}: criterion '{label}' failed validation - {field_errors}"
            ) from exc

    return criteria
