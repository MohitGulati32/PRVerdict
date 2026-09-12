# Real PRs used for validation

Real GitHub PRs used to exercise `normalize_pr_data()` / `score_pr()` end-to-end
against live data during development. Recorded here since these numbers aren't
derivable from git history and would otherwise have to be rediscovered by hand
each time. Referenced from `rubric/service_criticality.yaml`'s "Phase 8
validation notes" pointer.

## langchain-ai/langgraph#1075

Zero-CODEOWNERS-file case: langgraph has no CODEOWNERS at all, so `ownership`
should read `needs_review`, not `fail`, per that criterion's ambiguity_note.
Also has an empty PR body, which is what surfaced the `_extract_rollback_readiness`
crash fixed in commit `97b74cf` (GitHub/MCP server omits the `body` field
entirely rather than sending `""`).

## langchain-ai/langgraph#8598

`test_coverage` ambiguity case: 28 real, passing test-suite check runs across
multiple libs (Python 3.10-3.14 matrix) with zero coverage-related check runs
of any kind. Confirms `test_coverage` correctly returns `needs_review` rather
than a guessed `pass`, driven by genuine CI activity rather than an absence of
CI altogether.

Replaces **langchain-ai/langgraph#1169**, which technically satisfied the same
ambiguity_note but had zero check runs of any kind (no CI ran at all) - a much
weaker demonstration than "tests ran and passed, but coverage tooling
specifically wasn't configured."

## microsoft/vscode#175525

Positive CODEOWNERS ownership-match case: touches only `src/vscode-dts/vscode.d.ts`,
which CODEOWNERS assigns to `@TylerLeonhardt` and `@alexr00`. Approved directly
by `TylerLeonhardt`, so `check_ownership()` returns `is_owned: true` and
`score_pr()`'s reasoning names the actual matched approver rather than making a
generic claim.

An alternate that also confirms `is_owned: true` is **microsoft/vscode#289457**
(same file, approved by `alexr00`), in case a second example is ever needed.

Replaces **microsoft/vscode#316565**, which touches `src/vs/workbench/...` and
`src/vs/sessions/...` paths that aren't covered by vscode's CODEOWNERS at all -
`DonJayamanne`'s approval there doesn't confirm ownership because vscode's
CODEOWNERS file is sparse (a handful of workflow files, `vscode.d.ts`, and two
eslint-allowlist files) and never names that path or that reviewer.
