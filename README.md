# Shippable

LLM-powered project readiness scorer. A FastAPI service that scores a project's
readiness to ship against a rubric, using the Anthropic API.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in ANTHROPIC_API_KEY
```

## Run

```
uvicorn api.main:app --reload
```

- `GET /health` — health check
- `POST /score` — score a project's readiness given `{"context": "..."}`
