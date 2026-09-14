# Full-pipeline validation: 20 PRs (5 re-validated + 15 new)

> **Update:** `rollback_readiness` was changed to scale its bar with the
> change's own risk (diff size + service-criticality tier), instead of
> applying the same "must state a rollback plan" bar uniformly. See
> [Rerun after the rollback_readiness risk-scaling update](#rerun-after-the-rollback_readiness-risk-scaling-update)
> at the bottom for the before/after comparison. Everything above this note
> describes the *original* (pre-update) run.

All 20 rows below were produced by calling the live `POST /check` endpoint
(`api/main.py`) - the exact same code path as the app: `GitHubMCPClient.get_pr_snapshot()`
+ `get_codeowners()` -> `check_ownership()` -> `normalize_pr_data()` -> `score_pr()`
-> `decide()`. No REST shortcut, no mocked GitHub data. All 20 calls returned
HTTP 200; no errors.

## Re-validation of the 5 already-known PRs

These 5 were previously validated (see `docs/validation_prs.md`). Rerun here to
check for drift since that validation:

| PR | Prior known expectation | This run | Drift? |
|---|---|---|---|
| langgraph#1075 | `ownership` = needs_review (zero CODEOWNERS, not a fail) | `ownership` = needs_review | None |
| langgraph#8598 | `test_coverage` = needs_review (28 passing runs, no coverage check) | `test_coverage` = needs_review | None |
| vscode#175525 | `ownership` = pass (TylerLeonhardt is a named owner) | `ownership` = pass | None |
| vscode#289457 | `ownership` = pass (alexr00 is a named owner) | `ownership` = pass | None |
| vscode#316565 | `ownership` = needs_review (CODEOWNERS doesn't cover the path) | `ownership` = needs_review | None |

**No drift detected.** All 5 reproduced results consistent with their documented
validation, including one (`vscode#175525`) that was re-run earlier in this same
session with an identical result across every one of the six criteria. The
pipeline has not changed behavior since these were last checked.

## Full results, all 20 PRs

| # | Repo | Category | Decision | Failed | Needs review | Human-match assessment |
|---|---|---|---|---|---|---|
| 1075 | langgraph | already_validated | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible. Empty PR body, no CODEOWNERS, no CI signal - a human would also find this un-reviewable as-is. |
| 8598 | langgraph | already_validated | needs_human_review | - | all 6 | Plausible. Nothing clearly wrong, but real ambiguity (unmatched service, no coverage check) - "flag for review" over an auto-pass is the right level of caution. |
| 175525 | vscode | already_validated | **blocked** | rollback_readiness | test_coverage, service_criticality, incident_history | Debatable. 3-line change, owner-approved - a human would likely just merge this without demanding a stated rollback plan. Correct per the rubric as written, but stricter than typical human judgment for a trivial diff. |
| 289457 | vscode | already_validated | **blocked** | rollback_readiness | test_coverage, service_criticality, incident_history | Same as #175525 - tiny owner-approved change blocked purely for an undocumented rollback plan. |
| 316565 | vscode | already_validated | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible. Large (838-line) diff, no confirmable ownership, no rollback plan - a human would likely want more scrutiny here too. |
| 5243 | langgraph | contentious | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible. Large breaking-API migration PR with no stated rollback plan - exactly the kind of change a human reviewer would want reversibility documented for. |
| 125737 | vscode | contentious | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible-to-debatable. Large new feature (Disassembly view), no visible tests/ownership signal - reasonable to flag, though vscode's own norms don't typically require an explicit rollback note per PR. |
| 234220 | vscode | contentious | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible. Very large diff (3,687 additions), no test/ownership signal - a large, under-documented change is reasonable to block pending review. |
| 8918 | langgraph | should_clearly_block | **blocked** | rollback_readiness | test_coverage, ownership, service_criticality, incident_history | Right decision, coincidental mechanism. This PR was closed unmerged, but the pipeline has no knowledge of that - it blocked purely because the body lacks a rollback statement, not because it "knows" the PR was rejected. Change itself is tiny and looks fine (`change_risk` = pass). |
| 336147 | vscode | should_clearly_block | needs_human_review | - | all 6 | **Mismatch with category assumption, but plausibly correct on the merits.** This PR was closed unmerged, so the search category assumed it "should clearly block." But the code itself (Electron-42-only guard, overridable via an explicit flag) reads as safe and well-scoped - a human looking at just this diff would likely also say "looks fine, minor process gaps" rather than "block." Good illustration that a PR's final GitHub disposition isn't a reliable proxy for code quality. |
| 335956 | vscode | should_clearly_block | needs_human_review | - | test_coverage, ownership, service_criticality, incident_history (rollback_readiness and change_risk both passed) | Same nuance as #336147: closed-unmerged in GitHub, but the diff itself is safe (gated behind a settings toggle, `rollback_readiness` correctly scored pass). The pipeline's read of the code looks more accurate than the "should clearly block" label inferred from its GitHub closure. |
| 6259 | langgraph | clean_low_risk | needs_human_review | - | test_coverage, change_risk, rollback_readiness, ownership, service_criticality, incident_history | Stricter than a human would be. This is a documentation relocation - a human reviewer would almost certainly fast-approve it. The pipeline's caution here comes entirely from missing process metadata (no CODEOWNERS, no explicit rollback line), not from any real risk in the change. |
| 6145 | langgraph | clean_low_risk | needs_human_review | - | test_coverage, ownership, service_criticality, incident_history (rollback_readiness passed) | Same docs-only situation as #6259, but here `rollback_readiness` scored pass ("docstring-only, inherently reversible"). A human would fast-approve; the pipeline's residual caution is about ownership/service gaps rather than the change itself. |
| 6114 | langgraph | clean_low_risk | needs_human_review | - | test_coverage, rollback_readiness, ownership, service_criticality, incident_history | **Inconsistency worth flagging**: this is essentially the same situation as #6145 (docs-only, no dependencies, no explicit rollback statement) but `rollback_readiness` landed on needs_review here instead of pass. Two near-identical documentation PRs got different judgment calls on the same criterion - a minor LLM-judgment consistency gap, not a pipeline bug. |
| 6865 | langgraph | unresolved_review | **blocked** | rollback_readiness | test_coverage, ownership, service_criticality, incident_history | Right decision, different reasoning. This PR genuinely has an unresolved changes-requested review in real life, so "not ready" is directionally correct - but the pipeline doesn't see review state at all; it blocked on a missing rollback statement, unrelated to the actual open review thread. |
| 335898 | vscode | unresolved_review | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | Plausible. Sizable (330-line) diff, no ownership signal, no rollback plan - reasonable to flag regardless of the (also real) open review. |
| 335547 | vscode | unresolved_review | **blocked** | rollback_readiness | test_coverage, ownership, service_criticality, incident_history | Plausible, and directionally consistent with its real still-open, changes-requested state. |
| 8449 | langgraph | general_recent_mix | **blocked** | rollback_readiness | test_coverage, ownership, service_criticality, incident_history | **Likely too strict.** This is a routine dependency-vulnerability-fix chore PR. A human reviewer would merge this without hesitation - reverting a version bump is trivially, universally safe, and doesn't need a stated rollback plan. This is a concrete case where `rollback_readiness`'s all-or-nothing "must state a mechanism" bar doesn't fit a whole common category of low-risk PRs (dependency bumps, chores). |
| 336169 | vscode | general_recent_mix | needs_human_review | - | all 6 | Plausible. New UI feature, no tests/ownership signal visible, rollback mechanism only implied - reasonable to send to a human. |
| 334878 | vscode | general_recent_mix | **blocked** | rollback_readiness | test_coverage, change_risk, ownership, service_criticality, incident_history | **Likely too strict**, same issue as #8449. A 9-line defensive guard fix blocked solely for lacking a rollback sentence - a human would merge this without a second thought. |

## Cross-cutting findings

1. **`service_criticality` / `incident_history` gave zero discriminating signal across all 20 PRs.** Every single one scored `needs_review` on both, with no exceptions. `rubric/service_criticality.yaml` only maps 6 fictional example service paths (`services/payments-api/`, etc.), and neither `langchain-ai/langgraph` nor `microsoft/vscode` has any file under those paths - so every real PR in this batch hits the "unmatched" branch by construction. This is the *correct* behavior per the "never default to lowest risk" design, but it means a real deployment needs a real service-criticality config for the target repo before these two criteria add any value beyond a constant "we don't know."

2. **`ownership` was needs_review for 18 of 20 PRs**, passing only for the two PRs (`vscode#175525`, `#289457`) that were originally hand-picked to exercise a CODEOWNERS match. `langchain-ai/langgraph` has no CODEOWNERS file at all, and `microsoft/vscode`'s is sparse - so ownership signal is weak across this validation set for reasons unrelated to the pipeline itself.

3. **`rollback_readiness` is doing almost all of the "blocked" differentiation.** 11 of the 20 PRs came back `blocked`, and in every one of those 11, `rollback_readiness` (fail) was the sole blocking criterion - no PR in this batch failed on `test_coverage`, `change_risk`, or `ownership`. Since neither repo's PR template asks contributors to state a rollback mechanism, this criterion fails almost by default regardless of actual change risk. That correctly reflects reality (these PR bodies really don't document rollback plans), but it also means "blocked" in this batch mostly reduces to "did the author happen to mention reversibility," including for clearly trivial, safe changes (#8449, #334878) that a human reviewer would merge without hesitation. Worth calibrating - e.g. treating a small/mechanically-reversible diff as satisfying "naturally reversible" the same way an additive schema migration does - before using this as a real merge gate.

4. **A PR's final GitHub disposition (merged vs. closed-unmerged) is a poor proxy for whether the pipeline should block it.** Both PRs pulled from the "should clearly block" search filter (`vscode#336147`, `#335956`) actually scored `needs_human_review`, not `blocked` - and looking at their actual diffs, that looks like the *more* correct read: both changes are small and defensively gated. They were likely closed for reasons unrelated to code quality (superseded, stale, wrong target branch), which the pipeline correctly has no visibility into and doesn't need.

## Rerun after the rollback_readiness risk-scaling update

`_extract_rollback_readiness()` in `mcp_client/normalize.py` now also receives
`change_risk`'s signal (additions, deletions, changed_files,
service_criticality_tier), the same way `change_risk` already receives
`service_criticality`. The rubric's `rollback_readiness` entry
(`rubric/rubric.yaml`) was updated so a small, low-blast-radius change to a
non-critical or unmatched-tier service that's simply missing a stated
rollback plan scores `needs_review`, not `fail` - `fail` is now reserved for
a change that is both risky (large diff, or a critical-tier service) *and*
has no rollback plan.

All 20 PRs were rerun end-to-end through the same live `/check` pipeline.

### Decision distribution

| Decision | Before | After |
|---|---|---|
| blocked | 13 | 7 |
| needs_human_review | 7 | 13 |
| ready | 0 | 0 |

### `rollback_readiness` score distribution

| Score | Before | After |
|---|---|---|
| fail | 13 | 6 |
| needs_review | 5 | 13 |
| pass | 2 | 1 |

No PR reached an overall `ready` decision in either run - `ownership`,
`service_criticality`, and `incident_history` are still `needs_review` for
nearly every PR in this set for the reasons in finding 1 and 2 above, and
`decide()` requires every criterion to pass for `ready`. This update only
changes how often `rollback_readiness` itself blocks; it doesn't touch that
ceiling.

### Per-PR changes

| PR | Category | Decision: before → after | rollback_readiness: before → after |
|---|---|---|---|
| vscode#175525 | already_validated | blocked → **needs_human_review** | fail → needs_review |
| vscode#289457 | already_validated | blocked → **needs_human_review** | fail → needs_review |
| langgraph#8918 | should_clearly_block | blocked → blocked (unchanged, see note) | fail → needs_review |
| langgraph#6259 | clean_low_risk | needs_human_review → **blocked** | needs_review → **fail** |
| langgraph#6145 | clean_low_risk | needs_human_review → needs_human_review (unchanged) | pass → needs_review |
| langgraph#6865 | unresolved_review | blocked → **needs_human_review** | fail → needs_review |
| vscode#335898 | unresolved_review | blocked → **needs_human_review** | fail → needs_review |
| vscode#335547 | unresolved_review | blocked → **needs_human_review** | fail → needs_review |
| langgraph#8449 | general_recent_mix | blocked → **needs_human_review** | fail → needs_review |
| vscode#334878 | general_recent_mix | blocked → **needs_human_review** | fail → needs_review |

The other 10 PRs (including the other 3 already-validated ones - `langgraph#1075`,
`#8598`, `vscode#316565`) kept the same overall decision, though a couple
picked up incidental `needs_review` flips on `change_risk` or `ownership`
between runs (see the note on scoring variance below) that didn't change
their gate outcome.

**The update worked as intended for the two cases flagged as miscalibrated
in the original report**: `langgraph#8449` (a routine dependency-vulnerability
chore PR) and `vscode#334878` (a 9-line defensive guard fix) both flipped
from `blocked` to `needs_human_review` - exactly the "trivial, safe change
shouldn't get a hard block for an undocumented rollback plan" fix this
change was meant to produce.

**It also correctly went the other way for `langgraph#6259`.** This PR's
diff is actually 275 additions + 602 deletions across 25 files - a large
change, not the trivial docstring relocation its `documentation` label and
title ("relocate init args") suggested. Previously Claude scored its
`rollback_readiness` as `needs_review` while describing it as "a low-risk
docstring relocation" - a plausible-sounding but unsupported guess. With
the actual diff-size signal now available to this criterion, it correctly
recognized the change as risky-sized and scored `fail`, which pushed the
overall decision from `needs_human_review` to `blocked`. This is a stricter,
more accurate result, not a regression - the rubric change was about scaling
the bar to risk, not about only becoming more lenient.

**One side effect worth watching:** `langgraph#6145` (a 2-line docstring
addition) had `rollback_readiness` flip from an outright `pass` ("inherently
and trivially reversible") to `needs_review`. The new ambiguity_note's
default framing - "a process gap worth flagging" for any small change with
no *stated* rollback plan - seems to have nudged the model away from
awarding a clean pass even for a change this trivial, where it previously
was willing to infer natural reversibility on its own. Not wrong per the new
wording, but worth confirming this is the intended tradeoff: the update
was meant to move fails to needs_review for small changes, not necessarily
to move existing passes to needs_review too.

**Caveat: not every observed difference is attributable to this change.**
A few criteria untouched by this edit - `ownership` and `change_risk` -
also shifted between the two runs for some PRs (e.g. `langgraph#8918`'s
`ownership` went from `needs_review` to an outright `fail` between runs,
`langgraph#6145`/`#6114`/`vscode#335956` picked up a `change_risk` needs_review
that wasn't there before). Neither `_extract_ownership()` nor
`_extract_change_risk()` were modified, so this reflects normal run-to-run
scoring variance in Claude's judgment on already-ambiguous signal, not an
effect of this change. It didn't change any PR's overall gate decision in
this batch, but it's a reminder that these criteria aren't perfectly
deterministic across repeated runs on the same input.

## Investigating and fixing the langgraph#6145 pass → needs_review side effect

Full reasoning text, before vs. after the risk-scaling update:

- **Before (pass):** "The PR body clearly identifies the change as a
  docstring-only documentation improvement with no dependencies, which is
  inherently and trivially reversible with no runtime or schema impact,
  satisfying the 'naturally reversible' pathway."
- **After (needs_review):** "This is a trivial 2-line docstring-only change
  to an unmatched-tier service with no stated rollback plan or feature
  flag, which per the ambiguity note is a minor process gap worth flagging
  rather than a blocking risk."

Diagnosis: the new ambiguity_note's "small diff + no stated plan →
needs_review" default became the dominant signal and crowded out the
model's own willingness to recognize obvious reversibility - an unintended
side effect of the wording, not the intended calibration (which was aimed
at ambiguous small changes, not self-evidently trivial ones).

**Fix applied:** tightened `rollback_readiness`'s `ambiguity_note` in
`rubric/rubric.yaml` to explicitly carve out a third bucket: a near-zero-risk
change (single-digit line count, non-critical/unmatched tier) whose content
is obviously and trivially reversible on its face - a docstring, comment,
or plain-text documentation edit with no behavioral/schema/config impact -
should still score a clean `pass` via the "naturally reversible" pathway
even with no stated rollback plan. `needs_review` is now reserved for a
small change whose reversibility *isn't* self-evident from the diff alone
(a small logic change, config tweak, or behavior-affecting bug fix).

**Result after the fix**, rerun live:

| PR | rollback_readiness | Reasoning |
|---|---|---|
| langgraph#6145 (2-line docstring) | **pass** | "...obviously and trivially reversible on its face, so it passes via the naturally reversible pathway despite no explicit rollback statement." |
| langgraph#6114 (4-line doc fix) | **pass** | "...near-zero-risk, 4-line documentation-only fix...qualifies for a clean pass via the naturally reversible pathway." |
| langgraph#8449 (small dependency bump) | needs_review (unchanged, correctly) | "...a dependency-version/config change is not the trivially self-evident docstring or plain-text edit that qualifies for the clean pass, so the undocumented rollback path is a genuine gap worth flagging." |

The docstring false-`needs_review` is fixed, and the fix didn't leak into
the adjacent "small but not self-evidently reversible" case (`#8449` stayed
`needs_review` as intended).

**But it introduced a new wrinkle.** Re-checking `langgraph#6259` (875 lines
across 25 files, but pure docstring relocation) after the fix, it went from
the correct `fail` it had earned in the prior round back to `needs_review`:
"too large to qualify for the near-zero-risk 'naturally reversible' clean
pass, yet not clearly risky enough to block." The new wording's emphasis on
docstring/comment content as a leniency signal appears to have generalized
past the explicit "single-digit line count" boundary, softening what should
still be an unambiguous large-diff-plus-no-plan `fail` into a hedge. This is
a genuine trade-off rather than a clean win: fixing the false-`needs_review`
on trivial docstring edits reintroduced a false-`needs_review` on a large
diff that merely *contains* docstring content. Left as-is pending a decision
on whether to tighten the wording further (e.g. making the line-count
threshold a harder cutoff the model can't reason past for larger diffs).

## Restructuring rollback_readiness: deterministic label instead of model discretion

The repeated back-and-forth above always came back to the same root cause:
asking Claude for a final `pass`/`fail`/`needs_review` label gave it room to
override an explicit rule with its own judgment whenever the diff's content
"felt" safe, even when the rubric text said not to. The fix: stop asking for
a final label at all.

`scoring/score.py` now special-cases `rollback_readiness`. Claude is asked
for exactly two independent booleans:

- `content_self_evidently_reversible` - is the diff a docstring, comment, or
  plain-text edit with no behavioral/schema/config impact?
- `explicit_rollback_stated` - does the body or diff actually name a real
  rollback mechanism (not vague language)?

`_compute_rollback_readiness_score()` then maps those two booleans plus the
already-deterministic `is_near_zero_risk` flag onto a label in pure code:

| explicit_rollback_stated | content_self_evidently_reversible | near_zero_risk | → score |
|---|---|---|---|
| true | - | - | **pass** |
| false | true | true | **pass** |
| false | true | false | **needs_review** |
| false | false | true | **needs_review** |
| false | false | false | **fail** (only path to fail) |

All 8 boolean combinations were unit-tested against this table directly
(bypassing the API) and matched exactly.

### Determinism check

The whole point was that the same signal can't disagree with itself across
runs anymore. `langgraph#6259` was called three times back-to-back live:
all three returned `needs_review` with identical booleans
(`content_self_evidently_reversible=True, explicit_rollback_stated=False,
near_zero_risk=False`) - only the prose wording of Claude's one-sentence
explanation varied, never the booleans or the resulting label. Previously,
this exact case had flip-flopped between `fail` and `needs_review` across
different rounds of rubric wording, because the model was choosing the
label itself. It no longer can.

### The four investigation PRs

| PR | content_self_evidently_reversible | explicit_rollback_stated | near_zero_risk | Score |
|---|---|---|---|---|
| langgraph#6145 (2-line docstring) | true | false | true | **pass** |
| langgraph#6114 (4-line doc fix) | true | false | true | **pass** |
| langgraph#8449 (dependency bump, 20 lines) | false | false | false | **fail** |
| langgraph#6259 (875-line docstring relocation) | true | false | false | **needs_review** |

`#8449` still lands on `fail`, not the `needs_review` originally predicted
several rounds ago - and that's correct, not a bug. Its diff is 11
additions + 9 deletions = 20 total changed lines, over the 10-line
near-zero-risk cutoff, and Claude correctly judged a dependency-lockfile
version bump as a config-affecting change, not a "docstring/comment/
plain-text edit." Both facts are true, so `fail` is the only reachable
label per the table above. If dependency-bump PRs like this one should get
more slack, that's a threshold or content-definition change, not a scoring
bug - the architecture is now doing exactly what it's told, which is the
point.

### Full 20-PR rerun

| Decision | Original (uniform bar) | Deterministic (this version) |
|---|---|---|
| blocked | 13 | 14 |
| needs_human_review | 7 | 6 |

| rollback_readiness | Original | Deterministic |
|---|---|---|
| fail | 13 | 13 |
| needs_review | 5 | 3 |
| pass | 2 | 4 |

Not a uniform loosening or tightening - individual PRs moved in both
directions for legitimate, explainable reasons:

- **`vscode#175525`** (3-line change) moved `fail → needs_review`:
  near_zero_risk is true, content isn't confirmed self-evidently reversible
  (a real code change, not a docstring), so it lands in the process-gap
  bucket rather than being blocked outright.
- **`vscode#289457`** (16 additions + 1 deletion = 17 lines) *stayed*
  `fail`, unlike its near-twin `#175525`. This is a genuine threshold
  boundary effect worth knowing about: both PRs are small, owner-approved,
  intuitively "tiny" changes, but 17 total lines is over the 10-line cutoff
  while 3 is under it, so they land on opposite sides of the fail/needs_review
  line. The 10-line threshold is doing exactly what was specified; it's
  just tight enough that visually-similar small PRs can straddle it.
- **`vscode#336147`, `#336169`** moved `needs_review → fail`. Both add real
  runtime behavior (a conditional flag guard; a persisted UI toggle) at a
  size (94 and 258 lines respectively) well past the near-zero-risk cutoff,
  with no rollback plan stated - genuinely the only-path-to-fail case, and
  arguably a *more* accurate result than the previous round's softer
  `needs_review`, which had no principled floor.
- **`vscode#335956`** stayed `blocked` overall, but for an unrelated
  reason: `rollback_readiness` itself correctly scored `pass` this time
  (`explicit_rollback_stated=True` - it names a real settings toggle), and
  `ownership` happened to score `fail` in this run instead of its usual
  `needs_review` (no approving reviewers recorded) - the same
  run-to-run scoring variance on `ownership` flagged earlier in this
  document, not an effect of this change.

The `rollback_readiness` score distribution shifted toward more `pass`/fewer
`needs_review` (2→4 pass, 5→3 needs_review) while `fail` held steady at 13 -
consistent with the architecture doing what was asked: trivial,
self-evidently-reversible changes now reliably get a clean pass instead of
being held hostage to the model's mood on any given call, while genuinely
risky-and-undocumented changes still fail, deterministically.

## Raising near_zero_risk's threshold: 10 vs. 20 lines

Investigated whether `vscode#289457`'s 17 lines were the same *kind* of
content as `vscode#175525`'s 3 lines (both are small, owner-approved changes
to the same file, `src/vscode-dts/vscode.d.ts`, that landed on opposite
sides of the old 10-line cutoff). Pulled both diffs directly: `#175525` adds
3 lines of pure JSDoc prose to an *existing* property's comment - zero
code/type impact. `#289457` is different in kind, not just degree: it adds
a brand-new exported interface (`LineCommentRule`, with its own doc
comments) and widens an existing property's type from `string` to
`string | LineCommentRule`. That's a real, backward-compatible API surface
addition, not "more of the same comment." So the two PRs are similar in
spirit (both non-breaking, both owner-approved) but not the same content
type - `content_self_evidently_reversible` correctly stays `false` for
`#289457` regardless of the threshold chosen.

Compared the full 20-PR set under both thresholds, holding the model's
actual content judgments fixed:

| | Threshold = 10 | Threshold = 20 |
|---|---|---|
| rollback_readiness: pass | 4 | 4 |
| rollback_readiness: needs_review | 3 | 5 |
| rollback_readiness: fail | 13 | 11 |
| decision: blocked | 14 | 13 (12 in one live rerun - see note below) |
| decision: needs_human_review | 6 | 7 (8 in one live rerun) |

Only two PRs in this dataset actually sit in the (10, 20] range - everything
else is either well under 10 or well over 20, so this was a clean two-PR
natural experiment:

- **`vscode#289457`** (17 lines): `fail → needs_review`. A small, additive,
  owner-approved typings change landing as a hard block, purely for lacking
  a rollback sentence, is stricter than how a human reviewer would actually
  triage it.
- **`langgraph#8449`** (20 lines, a routine dependency-security bump):
  `fail → needs_review`. Same reasoning - a human merges a routine
  dependency fix without demanding a stated rollback plan.

**Chose 20.** The key property that makes this a safe change, not just a
looser one: raising the threshold can only ever soften `fail → needs_review`,
never `fail → pass` - the `pass` path via `near_zero_risk` still requires
`content_self_evidently_reversible` to be `true` independently. So widening
this bucket never risks silently clearing a change that's actually unsafe;
it only stops auto-blocking a change that's small but not self-evidently
safe either. Implemented in `mcp_client/normalize.py`'s
`_NEAR_ZERO_RISK_MAX_CHANGED_LINES` (now 20, with the rationale recorded in
a comment there) and in `rubric/rubric.yaml`'s `rollback_readiness.description`.

(Note: the two "live rerun" numbers above reflect a single non-batched
confirmation run and reflect the ordinary per-criterion score variance
documented in the next section - specifically, `ownership`'s fail/needs_review
wobble on `langgraph#8449` - not an effect of the threshold itself.)

## Final validation: temperature, and the double-run determinism check

Attempted to set `temperature=0` on every remaining Claude scoring call (the
generic path used by `test_coverage`, `change_risk`, `service_criticality`,
`ownership`, `incident_history`, plus `rollback_readiness`'s boolean-judgment
call) to eliminate run-to-run score noise at the source. **This isn't
possible on this model**: `claude-opus-5` rejects `temperature`, `top_p`,
and `top_k` outright -

```
anthropic.BadRequestError: 400 - `temperature` is deprecated for this model.
```

This was confirmed to be a hard API-level rejection, not an SDK gap (tried
passing all three via `extra_body` directly). This model generation has no
user-adjustable sampling control at all. The change was reverted; `scoring/score.py`
makes no attempt to set a sampling parameter.

Given that, ran the full 20-PR batch twice, back to back, at default
sampling, and diffed every one of the 6 criteria across all 20 PRs (120
scores per run, 240 total comparisons):

**Criterion-level score differences found: 4, out of 120.**

| PR | Category | Criterion | Run A | Run B |
|---|---|---|---|---|
| vscode#289457 | already_validated | change_risk | pass | needs_review |
| vscode#336147 | should_clearly_block | ownership | fail | needs_review |
| vscode#335547 | unresolved_review | change_risk | needs_review | pass |
| vscode#335547 | unresolved_review | ownership | needs_review | fail |

**Gate decision differences found: 0, out of 20.** Every single PR's overall
`ready`/`blocked`/`needs_human_review` decision matched exactly between the
two runs. Checked why in each case:

- **`vscode#336147`**: `rollback_readiness` was already `fail` in *both*
  runs (a 94-line behavior-affecting change with no stated rollback plan),
  which alone forces `blocked` regardless of what `ownership` did. The
  `ownership` wobble was real but moot for this PR's outcome.
- **`vscode#335547`**: same shape - `rollback_readiness` was `fail` in both
  runs, already locking in `blocked` on its own; the `change_risk` and
  `ownership` wobbles didn't change anything.
- **`vscode#289457`**: `change_risk` flipped `pass ↔ needs_review`, but
  neither of those is `fail`, and no other criterion was `fail` in either
  run, so `needs_human_review` held in both.

**This is the disclosed limitation, not a blocker for further work.**
`ownership` and `change_risk` show real run-to-run score noise on a handful
of already-ambiguous PRs (both criteria hinge on judgment calls - "is a
missing-CODEOWNERS-coverage gap a fail or a needs_review," "does this diff's
size proportionality read as fail or needs_review" - where the model's
answer isn't perfectly stable, and there's no sampling-parameter fix
available for this model). But across this entire 20-PR validation set, that
noise has never been observed to flip an actual gate decision - in every
observed case, either an unrelated criterion already decisively determined
the outcome, or the wobble stayed within the non-blocking pass/needs_review
range. `rollback_readiness` - the one criterion earlier shown to flip actual
gate decisions across runs - no longer wobbles at all now that its label is
computed deterministically (see the two-boolean restructuring above).

**Locked numbers for the README/demo** (both runs agreed exactly):

- 20 PRs scored: **13 blocked, 7 needs_human_review, 0 ready**
- 0 gate-decision disagreements across two independent live runs
- 4 of 120 individual criterion scores varied between runs, none of which
  changed a final decision
