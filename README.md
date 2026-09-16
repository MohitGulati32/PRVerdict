# PRVerdict

A release readiness gate that pulls live PR, CI, and review signals through MCP and scores them against a rubric, instead of trusting a tracker status that just says "done."

## The problem

A ticket marked done and a PR marked merged do not confirm a change is actually safe to ship. Tests might not be running. A rollback plan might not exist. The person who approved the PR might not actually own the code they approved. None of that shows up in a project board.

PRVerdict checks six things a human reviewer would normally have to remember to check by hand, using live data pulled through the Model Context Protocol rather than a custom integration written against each data source.

## The result, in one line

Across 20 real, unmodified pull requests from two active, well maintained open source repositories, **0 came back fully ready.** 13 were blocked outright, 7 needed a human look. That is not a bug in the tool. It is a fairly direct measurement of how rarely a real PR actually clears a complete readiness bar, even in well maintained codebases.

## The six criteria

| Criterion | What it checks | Data source |
|---|---|---|
| Test Coverage | CI check run status for the test suite and any coverage related check | GitHub MCP, check runs |
| Change Risk | Whether the diff's size and blast radius is proportionate to its review, weighted by service criticality | GitHub MCP, diff stats, cross referenced with the service tier config |
| Service Criticality | Whether the touched service is tagged business critical, customer facing, or on the incident escalation path | A manually maintained config mapping paths to a P0/P1/P2 tier |
| Rollback Readiness | Whether the PR documents how to revert the change safely, or is content that is self evidently reversible | GitHub MCP, PR body, diff content, plus deterministic size/tier signals (see below) |
| Ownership | Whether the PR was approved by someone who actually owns the changed code per CODEOWNERS, not just any reviewer | GitHub MCP, CODEOWNERS file, approvals |
| Incident History | Whether the touched service has had a recent incident, a correlational risk signal, not a direct measure of this PR | PagerDuty MCP (see "What's mocked" below) |

Each criterion is scored independently by Claude as pass, fail, or needs_review, with a plain language reasoning string, then combined into an overall decision: ready, blocked, or needs_human_review. Blocked if any criterion fails. Needs_human_review if any criterion is uncertain and none failed outright.

## Why MCP, specifically

Most "AI checks your PR" tools are built by writing custom integration code against each data source's REST API. PRVerdict instead connects to the official GitHub MCP server and a PagerDuty MCP server, meaning the tool describes its own capabilities to the client rather than being hand wrapped per endpoint. The same MCP servers this project uses would work identically behind a different LLM client, that portability is the actual point, not an implementation detail.

## The rollback_readiness story

This is the criterion that took the most iteration, and it is the most interesting finding in the whole build, worth walking through directly rather than summarizing away.

Early in validation, rollback_readiness was hard blocking clearly low risk changes, a 9-line defensive guard fix, a routine dependency bump, on the same bar as a genuinely risky change. The fix was to scale the bar with the change's actual risk: a small, low blast radius change should not need the same rollback documentation as a large one touching a critical service.

That fix introduced a new problem. Across three separate rounds of rewriting the rubric's prose instructions, the model kept independently disagreeing with an explicit hard fail rule whenever a large diff's content was docstring or comment only, softening what the rubric said should be a clear fail toward needs_review. This happened with three different, increasingly explicit wordings of the same rule. That consistency was itself the signal: this was not the model failing to follow instructions, it was the model repeatedly reaching a defensible judgment that a natural language size threshold could not reliably override.

The fix was architectural, not another wording attempt. Rollback_readiness no longer asks the model for a final label at all. It asks for exactly two narrow, factual boolean judgments, is this content self evidently reversible, and is a rollback mechanism actually named, and combines those two booleans with an already deterministically computed near_zero_risk flag entirely in code. The model judges content, which it is genuinely good at. Code owns the boundary logic, which it is actually reliable at. Verified by calling the same PR three times back to back and getting an identical label every time, something the prior prose based version could not guarantee.

## What's real, and what's mocked

- **GitHub MCP integration**: fully live. Real JSON RPC over stdio against the official GitHub MCP server, PR data, CI checks, review comments, and CODEOWNERS, all fetched live for every check.
- **Incident History / PagerDuty MCP**: mock backed. Both PagerDuty's standard trial and its developer account program require a work email, which was not available for this project. The client's function signature and field names match the real pagerduty-mcp-server's actual schema exactly (status/urgency, not a native P0/P1/P2, PagerDuty has no such field), so swapping in a live connection is a drop in change, not a rewrite.
- **Service Criticality config**: illustrative. The six example service names and tiers do not correspond to either validation repo's real structure, since neither is a microservices codebase. In a real deployment this file is replaced with the target org's actual service to path mapping. Validated separately via constructed test scenarios rather than against the real PR set.

## Known limitations

- **claude-opus-5 has no adjustable sampling.** Temperature, top_p, and top_k are all rejected outright by the API for this model. Two full independent 20-PR validation runs at default sampling showed 0 gate decision disagreements, though 4 of 120 individual criterion scores varied between runs without ever changing a final decision. Rollback_readiness's deterministic architecture makes it immune to this; the other five criteria are not, and this is disclosed rather than worked around further.
- **The near_zero_risk threshold (20 changed lines) is a hard cutoff**, which means two similarly sized PRs can land on different sides of it. This is a deliberate trade for predictability over the alternative, prose based judgment that proved inconsistent across rounds of testing.
- **Observability and full Deployment Safety are out of scope for v1.** Both would require a third and fourth live integration (a monitoring tool, a deploy pipeline) beyond what this build's scope covered.
- **Ownership cannot yet resolve team based CODEOWNERS entries** (`@org/team`). An approval from an actual team member currently surfaces as needs_review rather than a confirmed pass, since verifying team membership needs a separate API call not yet built.

## Running it locally

```bash
git clone https://github.com/MohitGulati32/PRVerdict.git
cd PRVerdict
pip install -r requirements.txt
```

Set the following in `.env`:
```
ANTHROPIC_API_KEY=your_key
GITHUB_PERSONAL_ACCESS_TOKEN=your_token
```

Start the GitHub MCP server (requires Docker):
```bash
docker run -i --read-only ghcr.io/github/github-mcp-server
```

Start the app:
```bash
uvicorn api.main:app --reload
```

Open `http://localhost:8000`, paste a PR URL, and run it.
