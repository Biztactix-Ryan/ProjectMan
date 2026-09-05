# Usage-telemetry baseline -- post-subtraction

**This is the POST-SUBTRACTION baseline for the ProjectMan tool-usage epic (US-PM-30).** It was captured *after* Sprints 1-8, and it is the artifact that finally measures the claims those sprints asserted -- fewer calls per task, less context per worker -- against the pre-fix capture in [`baseline-pre-fix.md`](baseline-pre-fix.md). Do not overwrite either file.

The generated sections below (provenance, headline numbers, busiest tools) come straight from `tools.usage_telemetry.baseline capture` -- the same extractor that produced the pre-fix baseline. The [comparison](#comparison-against-the-pre-fix-baseline) is the output of `baseline compare`, transcribed.

## Provenance

| field | value |
| --- | --- |
| captured at (UTC) | `2026-09-05T11:15:47.554499+00:00` |
| code at commit | `10610849baf0f8fe3edcd41a19dd800c752ad5f1` (working tree **dirty** at capture -- the analysis code was not fully committed, so re-running at this commit alone may not reproduce it) |
| branch | `main` |
| corpus root | `/home/user/.claude/projects` |
| tool prefix | `mcp__projectman__` |
| transcript files | 835 |
| sessions | 780 |
| calls | 6,053 |
| call->result match rate | 100.00% (0 unmatched) |
| schema | `projectman.usage-telemetry.baseline/1` |

> Post-subtraction baseline for the ProjectMan tool-usage epic (US-PM-30). HEAD is 1061084 (Pin mcp<2: mcp 2.x renamed FastMCP and breaks projectman serve); the Sprint 8 subtraction is present as uncommitted working-tree changes on top of it, so git.dirty is true and this capture reflects the post-subtraction tool surface rather than the surface at commit 1061084 alone.

## Provenance caveat

`git.dirty` is **true** in this capture, and that is the honest value, not an
oversight. The Sprint 8 subtraction had not been committed when the baseline was
taken: `HEAD` was `1061084` ("Pin mcp<2: mcp 2.x renamed FastMCP and breaks
`projectman serve`") and the whole subtraction sat on top of it as uncommitted
working-tree changes. The capture therefore describes the **post-subtraction tool
surface**, which is what the story asks for -- but it is *not* reproducible from
commit `1061084` alone, because that commit does not contain the subtraction.

Two things this does and does not affect:

- The corpus numbers (calls, bytes, failures, runs) are read from the transcript
  tree and do not depend on the working tree at all. They are unaffected.
- `tools/list` schema bytes (88,441 for 42 tools) *are* a property of the working
  tree, so that row measures the uncommitted post-subtraction server surface. Once
  the subtraction is committed, re-read it at that commit if you need a citable
  number.

The task originally called for a clean-tree capture; the orchestrator run that
executed it was stage-only and could not commit, so this caveat stands in place of
`dirty: false`. Nothing was stashed, reverted or faked to make the flag read
otherwise.

## The corpus is live, not a fixed dataset

The corpus is the local Claude transcript tree, and it is still being written to.
**It includes the ProjectMan calls made by the orchestration session that captured this baseline**, and it grew while that session worked -- a capture taken minutes later would already have more calls. The numbers below are a snapshot as of `2026-09-05T11:15:47.554499+00:00`, not a static dataset.

Two consequences for anyone comparing against this file:

1. Compare **rates**, not absolute counts. The denominator moves.
2. A later capture includes these transcripts plus everything since, so it is a superset, not an independent sample. Improvements are diluted by the history still in the corpus; the true post-fix rate is better than a whole-corpus re-capture will show.

> **Point 2 did not hold between the pre-fix capture and this one.** Transcripts
> age out of `~/.claude/projects`, and the entire pre-fix corpus had rolled off
> before this capture was taken, so the two are disjoint rather than nested. See
> [These two captures measure disjoint corpora](#these-two-captures-measure-disjoint-corpora).
> Point 2 still applies to any capture taken shortly after this one.

## Headline numbers

| metric | value |
| --- | --- |
| calls | 6,053 |
| total response bytes | 7,445,600 (7.45 MB, ~1,853,783 tokens) |
| median bytes per call | 202 |
| failing calls (distinct) | 980 (16.19%) |
| hard errors (`is_error`) | 39 (0.64%) |
| soft errors (error body) | 941 (15.55%) |
| malformed inputs (`__unparsedToolInput`) | 34 (0.56%) |
| longest consecutive run | 30x `pm_update` |
| consecutive runs total | 4,027 |
| completions with no run-log entry | 0 of 2,236 (0.00%) |
| run-log note length | median 971, p90 1,355, p95 1,678 chars (gate: median <= 300, p90 <= 800 -- FAIL) |
| guidance tool usage | `pm_context` 5 calls in 0.51% of sessions, `pm_estimate` 13 calls in 1.28% of sessions |
| `tools/list` schema bytes | 88,441 for 42 tools by default, 94,809 with every gated family on (6,368 saved, 6.72%) |

The three failure classes overlap (one call can be both malformed and a hard error), so they do not sum to the distinct failure count.

## Busiest tools by call count

| tool | calls | % calls | response bytes | % bytes |
| --- | --- | --- | --- | --- |
| `pm_update` | 2,411 | 39.8% | 202,109 | 2.7% |
| `pm_grab` | 808 | 13.3% | 2,251,878 | 30.2% |
| `pm_get` | 802 | 13.2% | 2,087,448 | 28.0% |
| `pm_done_next` | 648 | 10.7% | 912,986 | 12.3% |
| `pm_audit` | 306 | 5.1% | 84,352 | 1.1% |
| `pm_list_sprints` | 108 | 1.8% | 269,518 | 3.6% |
| `pm_create_tasks` | 105 | 1.7% | 52,048 | 0.7% |
| `pm_create_story` | 98 | 1.6% | 76,142 | 1.0% |
| `pm_board` | 82 | 1.4% | 395,095 | 5.3% |
| `pm_active` | 75 | 1.2% | 28,329 | 0.4% |

## Comparison against the pre-fix baseline

Produced by:

```sh
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-pre-fix.json \
    docs/telemetry/baseline-post-subtraction.json
```

```
baseline  pre-fix  2026-07-29T00:10:28.479453+00:00  commit fca9f189a85c
current   post-subtraction  2026-09-05T11:15:47.554499+00:00  commit 10610849baf0
```

| metric | before | after | delta | |
| --- | ---: | ---: | ---: | --- |
| transcript_files | 515 | 835 | +320 | |
| sessions | 484 | 780 | +296 | |
| calls | 3,416 | 6,053 | +2,637 | |
| match_rate_pct | 100.00 | 100.00 | +0.00 | |
| response_bytes | 4,066,642 | 7,445,600 | +3,378,958 | worse |
| estimated_tokens | 1,012,318 | 1,853,783 | +841,465 | worse |
| median_bytes_per_call | 341 | 202 | -139 | **better** |
| failures | 214 | 980 | +766 | worse |
| failure_rate_pct | 6.26 | 16.19 | +9.93 | worse |
| hard_errors | 47 | 39 | -8 | **better** |
| hard_error_rate_pct | 1.38 | 0.64 | -0.73 | **better** |
| soft_errors | 167 | 941 | +774 | worse |
| soft_error_rate_pct | 4.89 | 15.55 | +10.66 | worse |
| malformed_inputs | 27 | 34 | +7 | worse |
| malformed_input_rate_pct | 0.79 | 0.56 | -0.23 | **better** |
| completions | - | 2,236 | - | metric postdates the pre-fix capture |
| completions_without_run_log | - | 0 | - | metric postdates the pre-fix capture |
| completions_without_run_log_rate_pct | - | 0.00 | - | metric postdates the pre-fix capture |
| note_length_median | - | 971 | - | metric postdates the pre-fix capture |
| note_length_p90 | - | 1,355 | - | metric postdates the pre-fix capture |
| note_length_p95 | - | 1,678 | - | metric postdates the pre-fix capture |
| note_length_gate_passed | - | 0 | - | gate FAILS |
| pm_context_calls | - | 5 | - | metric postdates the pre-fix capture |
| pm_estimate_calls | - | 13 | - | metric postdates the pre-fix capture |
| pm_context_sessions_pct | - | 0.51 | - | metric postdates the pre-fix capture |
| pm_estimate_sessions_pct | - | 1.28 | - | metric postdates the pre-fix capture |
| runs_total | 2,431 | 4,027 | +1,596 | |
| longest_run | 45 | 30 | -15 | **better** |
| longest_run_tool | pm_update | pm_update | - | |
| tool_list_bytes_all | - | 94,809 | - | metric postdates the pre-fix capture |
| tool_list_bytes_default | - | 88,441 | - | metric postdates the pre-fix capture |
| tool_list_tools_default | - | 42 | - | metric postdates the pre-fix capture |
| `pm_update_longest_run` | 45 | 30 | -15 | **better** |
| `pm_archive_longest_run` | 15 | 26 | +11 | worse |

> The corpus is live and grows between captures, so absolute counts are not
> comparable on their own -- read the `*_rate_pct` rows for the real movement.

### Calls per task

One transcript session is the closest thing the corpus has to "one worker
working one task", so calls per session is the measurable form of *calls per
task*. It comes from `report.totals.calls_per_session`, which both captures
carry.

| calls per session | pre-fix | post-subtraction | delta |
| --- | ---: | ---: | ---: |
| sessions (n) | 484 | 780 | +296 |
| mean | 7.06 | 7.76 | +0.70 (+9.9%) |
| median | 2 | 3 | +1 |
| p90 | 6 | 8 | +2 |
| p95 | 40 | 42 | +2 |
| p99 | 104 | 83 | -21 |
| max | 256 | 277 | +21 |

**The claim does not hold on this measurement.** Calls per task went *up*, not
down: the median session makes 3 ProjectMan calls where it used to make 2, and
the mean rose ~10%. Only the tail moved the right way (p99 104 -> 83), which is
consistent with the bulk verbs cutting the worst runs while doing nothing for
the typical session.

Read this alongside the failure rate: 906 `pm_update` calls in this corpus were
rejected for an over-long run-log note and retried. Retries are calls, so a large
part of the +0.70 mean is a defect being paid for twice rather than workers doing
more work. See [Headline verdict](#headline-verdict).

### Context per worker

Response bytes returned into a session's context is the measurable form of
*context per worker*: it is exactly the payload a worker has to read.

| context per session | pre-fix | post-subtraction | delta |
| --- | ---: | ---: | ---: |
| total response bytes | 4,066,642 | 7,445,600 | +3,378,958 |
| bytes per session (mean) | 8,402 | 9,546 | +1,143 (+13.6%) |
| estimated tokens per session (mean) | 2,092 | 2,377 | +285 (+13.6%) |
| median bytes per call | 341 | 202 | -139 (-40.8%) |
| p90 bytes per call | 3,099 | 3,234 | +135 |
| p95 bytes per call | 4,486 | 4,684 | +198 |

**Split verdict.** The *per-call* payload got substantially leaner -- the median
response is 40.8% smaller, which is the field-trimming and terse-default work
landing. But the *per-session* total rose 13.6%, because sessions now make more
calls (see above) and the three biggest byte consumers (`pm_grab`, `pm_get`,
`pm_done_next`) still account for ~70% of all bytes. Fewer bytes per call times
more calls per task nets out worse, not better -- and, as above, a share of those
extra calls are rejected-note retries rather than useful work.

### Bulk-verb longest runs (`BULK_RUN_TOOLS`)

These are the numbers US-PM-12 exists to move, and `pm_update_longest_run` is
the one US-PM-12-5 consumes.

| metric | pre-fix | post-subtraction | delta | reading |
| --- | ---: | ---: | ---: | --- |
| `pm_update_longest_run` | 45 | 30 | -15 (-33%) | better |
| `pm_archive_longest_run` | 15 | 26 | +11 (+73%) | worse |

Supporting per-tool detail from `report.by_tool[].runs`:

| | `pm_update` pre | `pm_update` post | `pm_archive` pre | `pm_archive` post |
| --- | ---: | ---: | ---: | ---: |
| calls | 1,199 | 2,411 | 29 | 57 |
| runs | 588 | 866 | 6 | 13 |
| runs >= 3 | 67 | 304 | 3 | 6 |
| removable calls | 611 | 1,545 | 23 | 44 |
| longest run | 45 | 30 | 15 | 26 |

[README.md](README.md) warns that a longest run is a **maximum over a corpus that
only grows**, so a whole-corpus re-capture can never show the maximum fall. That
warning does not apply to this pair -- see the next section: the two corpora are
disjoint, so `pm_update` 45 -> 30 is a real fall and `pm_archive` 15 -> 26 is a
real rise, both measured on work that actually happened in each window.

`pm_archive`'s single 26-run is one session; with only 13 `pm_archive` runs in
the whole corpus the metric is thin, and `removable_calls` (23 -> 44) is the
steadier read. Neither bulk verb is being used at anything like its opportunity:
`pm_update` still leaves 1,545 removable calls on the table.

### These two captures measure disjoint corpora

`README.md` assumes a later capture is a **superset** of an earlier one, diluted
by the history still inside it. **That is not true of this pair**, and it changes
the reading in the baseline's favour:

- The oldest transcript in the post-subtraction corpus was last written on
  **2026-08-03**, five days *after* the pre-fix capture (2026-07-29).
- Of the 18 sessions named in the pre-fix `runs.longest` sample, **0 are still on
  disk**. The overlap between the two captures' sampled sessions is empty.

Older transcripts age out of `~/.claude/projects`, so the pre-fix corpus has
rolled off entirely. The consequence is the good kind: this is an **independent
before/after**, not a diluted superset. No dilution correction is needed, the
rates above are directly comparable, and the regressions are not artefacts of
old history being counted twice.

The one thing it costs is reproducibility -- the pre-fix corpus no longer exists,
so `baseline-pre-fix.json` is the *only* surviving record of it. That is the
reason the file must never be overwritten.

### Headline verdict

The Sprints 1-8 claims, measured:

| claim | verdict | evidence |
| --- | --- | --- |
| fewer calls per task | **not supported** | mean 7.06 -> 7.76 per session; median 2 -> 3 |
| less context per worker | **not supported per session**, supported per call | 8,402 -> 9,546 bytes/session; median 341 -> 202 bytes/call |
| shorter `pm_update` runs | **supported** | longest run 45 -> 30 |
| shorter `pm_archive` runs | **not supported** | longest run 15 -> 26 |
| fewer failures | **not supported** | 6.26% -> 16.19% combined |

One defect dominates every "not supported" row above. Of the 941 soft errors,
**906 (96%) are a single message**: `pm_update` rejecting a run-log note with
*"Run-log note must be 1024 characters or fewer"*. The note-length metric agrees
-- median 971, p90 1,355, p95 1,678 chars, against a gate of median <= 300 and
p90 <= 800, which it **fails**. `pm_update`'s own failure rate is 38.9% (939 of
2,411 calls).

That single cause plausibly accounts for the other two regressions as well: every
rejected note is retried, which inflates calls per session, and both the rejected
call and its retry add bytes to the worker's context. Fixing the note-length
behaviour is the highest-value item this baseline identifies, and until it is
fixed the per-task and per-worker numbers cannot be read as a verdict on the
subtraction work itself.

The genuine wins are real but narrower: hard errors 1.38% -> 0.64%, malformed
inputs 0.79% -> 0.56%, median response 341 -> 202 bytes (-40.8%), longest
`pm_update` run 45 -> 30, and run-log coverage at 0 missing entries in 2,236
completions.

## Re-capture and compare

```sh
# take a fresh capture next to this one
python -m tools.usage_telemetry.baseline capture \
    --out-dir docs/telemetry --name baseline-YYYY-MM-DD --label post-fix

# compare this baseline against a live capture
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-post-subtraction.json
```

See [README.md](README.md) for the full procedure. The full machine-readable record is `baseline-post-subtraction.json`; this file is only its summary.
