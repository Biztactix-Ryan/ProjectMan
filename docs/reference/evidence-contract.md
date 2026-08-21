# The Evidence Contract

**Task:** US-PM-9-6 · **Story:** US-PM-9 — Structured evidence on run-log entries
**Date:** 2026-08-21 · **Version:** v0.8.9 (this checkout)
**Status:** DECIDED — binding on `US-PM-9-7` (store and return evidence), `US-PM-9-8`
(detect completions with no evidence), `US-PM-9-9` (rewrite `pm-orchestrate`), and the
tests `US-PM-9-1..5`.

This document is a contract, not an implementation. No behaviour changes with this task.

## Verdict in one line

`pm-orchestrate` SKILL.md steps 17–19 already make the orchestrator collect three
structured things — **which files changed, which test commands ran and passed, which DoD
criteria are evidenced** — and today it flattens them into prose, which is why notes cluster
at the cap. They become a bounded `evidence` object on the run-log entry, **alongside** an
unchanged, still-required `note` that returns to being the one-line human summary SKILL.md
already asks for.

> **The note says what happened; the evidence says what proves it. Prose is never the
> container for a list.**

## 1. The schema

New models in `src/projectman/models.py`, beside `RunLogEntry` (line 292):

```python
class EvidenceTest(BaseModel):
    command: str                      # clamped to 160 chars
    passed: bool
    summary: Optional[str] = None     # clamped to 160 chars

class Evidence(BaseModel):
    files: list[str] = []             # <= 40 items, each clamped to 160 chars
    tests: list[EvidenceTest] = []    # <= 10 items
    dod_met: list[str] = []           # <= 20 items, each clamped to 160 chars
    dod_unmet: list[str] = []         # <= 20 items, each clamped to 160 chars
```

`dod_unmet` earns its place: `pm_review` and `pm_park` exist to say *which* criteria are
outstanding, and without it that list goes back into the prose this story is emptying.
Nothing else is added — no commit sha, no durations, no free-form `extra` dict; an
open-ended field is how this becomes the next unbounded blob.

**Caps are clamped, never rejected**, following `truncate_run_log_note` (`store.py:87`) and
the reasoning at `store.py:1961` — raising on an oversized payload would take the
status/outcome write down with it, and a caller that only checks `is_error` would silently
lose the state change. Over-long lists keep their **first** N entries; over-long strings are
cut to 160 chars. When a clamp fires the response carries `evidence_clamped: true` and
`evidence_dropped: {"files": 12, ...}`, mirroring `note_truncated` / `note_dropped_chars`.
Worst case on the wire is ~16 KiB; the expected case is 300–600 bytes.

A line in `.project/logs/US-PM-9-7.jsonl` (wrapped here; written as one line):

```json
{"timestamp": "2026-08-21T04:11:09.412Z", "outcome": "success", "status": "done",
 "note": "evidence field lands on RunLogEntry; 12 store tests pass", "actor": "claude",
 "evidence": {"files": ["src/projectman/models.py", "tests/test_run_log_evidence.py"],
   "tests": [{"command": "uv run pytest tests/test_run_log_evidence.py",
              "passed": true, "summary": "12 passed"}],
   "dod_met": ["Evidence model with caps", "old entries still parse"], "dod_unmet": []}}
```

## 2. Where it lives

One optional field on `RunLogEntry`, after `note`: `evidence: Optional[Evidence] = None`.

**Backwards compatibility, exactly.** `Store.get_run_log` parses each line with
`RunLogEntry.model_validate_json` (`store.py:583`); a field with a default is simply absent
from old lines, so every existing `.jsonl` line parses to `evidence=None` with no
migration, no rewrite, and no version marker. The log is append-only and is never
rewritten. `_append_run_log` (`store.py:538`) switches its write to
`entry.model_dump_json(exclude_none=True)` so that entries without evidence do not each
gain a permanent `"evidence": null`; `status` is the only other nullable field and it also
has a default, so both directions round-trip.

## 3. How evidence gets in

**A typed object parameter, not a JSON string.** `pm_create_tasks(tasks: list[dict])`
(`server.py:1386`) is the existing proof that FastMCP renders a non-scalar annotation into
the tool schema and hands back the parsed structure. A JSON-*string* parameter would
double-encode, force the model to hand-escape, and give the client nothing to validate
against. *Tension flagged:* `pm_create_tasks` uses `list[dict]`, not a pydantic model, so a
model-annotated nested param is not yet exercised here; if US-PM-9-7 finds a client that
mangles it, the fallback is `evidence: Optional[dict] = None` validated server-side with
`Evidence.model_validate(...)` — identical wire shape and validation, declared loosely.
Never fall back to a string.

`evidence: Optional[Evidence] = None` is added as a trailing optional keyword to
**`pm_accept`, `pm_review`, `pm_retry`, `pm_park`, `pm_update` and `pm_done_next`** — every
tool that can append a run-log entry. Uniform beats a rule to memorise; in practice
`pm_accept` and `pm_review` are where evidence exists, and `pm_retry`/`pm_park` carry the
failing `tests` entries that justify the verdict. `_do_verdict` and `_do_accept`
(`server.py:1991`, `2030`) forward it to `Store.update`, which pops it beside `outcome` and
`note` (`store.py:1957`) and passes it to `_append_run_log`. The append condition widens to
`if outcome is not None or note is not None or evidence is not None`, so
`pm_update(id, evidence=...)` alone still lands an entry (`info`, empty note).

**`note` stays required and unchanged** on all four verdict verbs — same `ToolError` on
blank, same 4096-char truncation. Recommended length is now **one line, ≤ 200 characters**:
when evidence is present and the note exceeds `NOTE_SUMMARY_RECOMMENDED = 200`, the
response carries `note_long: true`, `note_length` and `note_recommended`. Advisory only —
never an error, never extra truncation. It is feedback the orchestrator reads and the
telemetry can count, not a new way to fail a write.

## 4. How evidence gets out

- **`pm_run_log`** returns it verbatim — it already dumps whole entries (`server.py:3868`),
  so `evidence` appears with no code change beyond the model. It also gains
  `has_evidence: Optional[bool] = None`, filtering to entries with (`true`) or without
  (`false`) evidence — making "did this completion prove anything" a one-call question.
- **`pm_get(include_log=True)`** shows a **compact marker, not the object**: `pm_get` is the
  high-frequency context call, and embedding evidence there spends the exact budget this
  story defends. Each `recent_run_log` entry (`server.py:547`) gains `has_evidence: bool`
  and a one-line `evidence_summary` — `"3 files, 1/1 tests passed, 2/2 DoD"`. Full detail is
  one `pm_run_log` away.
- **`pm_activity`** — unchanged, deliberately: it records frontmatter diffs, and
  `outcome`/`note` are popped before the `changes` dict is built (`store.py:1957` vs
  `2089`). Evidence is run-log payload, not frontmatter.

## 5. Detecting completion without evidence

> **A completion without evidence is a task with `status == done` whose run log contains no
> entry whose `evidence` is not `None`.** A task with no run log at all qualifies.

**Present-but-empty is evidence.** `Evidence()` with four empty lists explicitly says
"nothing to show" — exactly the genuinely non-code task (docs, config decisions) that
SKILL.md step 17 already carves out of the empty-diff rule. *Absent* evidence is the gap,
so the check tests `entry.evidence is not None`, never the truthiness of the lists.

US-PM-9-8 adds `check_completions_without_evidence(store)` to `src/projectman/audit.py`,
emitting **one aggregate finding**, code **`done-without-evidence`**, severity
**`warning`**, with the task ids in `items` — the shape of `done-story-incomplete-tasks`,
so DRIFT.md gets one line rather than one per task. Archived tasks are skipped.

Warning, not error, for the reason already written at `audit.py:341-350`: `/pm-orchestrate`
halts a sprint on any error-level finding, and error is reserved for structural
contradictions — a done story with open tasks, a dependency cycle. This is a coverage gap,
and decisively, every task completed before this ships has no evidence, so at error level
the first audit after release would brick the orchestrator on every existing project.
`pm_board` gets no hint; the finding and the `pm_run_log` filter are enough.

## 6. What step 19 becomes

Steps 17–18 already produce the lists; only the recording changes. US-PM-9-9's rewrite of
step 19's Accept line:

```
pm_accept(task_id, note="all DoD met; 47 tests pass",
          evidence={"files": ["src/projectman/store.py", "tests/test_store.py"],
                    "tests": [{"command": "uv run pytest tests/test_store.py",
                               "passed": true, "summary": "47 passed"}],
                    "dod_met": ["evidence stored on entry", "old lines still parse"]})
```

Retry carries the failure: `pm_retry(task_id, note="tests still red",
evidence={"tests": [{"command": "uv run pytest -q", "passed": false, "summary": "3 failed"}]})`.
The template must also stop telling the orchestrator to pack files and test results into
the note, and say instead: **note = one line, ≤ 200 chars; lists go in `evidence`**.

## 7. Backwards compatibility

Every existing `.jsonl` line parses unchanged (§2); no response key is renamed or removed;
every tool keeps its signature with `evidence` appended as an optional keyword, so every
existing call site is untouched; `note` keeps its required-ness, semantics and 4096-char
cap. `pm_update(id, status="done")` with no outcome, note or evidence still writes no
run-log entry — it stays the escape hatch, and it is what §5's finding flags rather than
blocks.

## 8. Tests the sibling tasks should cover

**US-PM-9-1 — evidence is separate from the note.** One verdict call carrying both writes
one entry with both; the note is byte-identical to what was passed and no part of the
evidence appears inside it; the entry round-trips through `Store.get_run_log`; a
hand-written old-format line with no `evidence` key parses with `evidence is None`; an
entry written without evidence has no `evidence` key on disk (`exclude_none`).

**US-PM-9-2 — files, tests and DoD.** All four lists round-trip with values intact,
including `passed: false` and a `summary` of `None`; caps clamp rather than reject — 100
files stores 40, a 500-char path stores 160, and the status/outcome write still lands, with
`evidence_clamped` and `evidence_dropped` in the response; `dod_unmet` survives a
`pm_review`.

**US-PM-9-3 — detection.** A `done` task with no run log, and a `done` task whose every
entry has `evidence is None`, both appear in one `done-without-evidence` finding at
severity `warning`; a `done` task whose entry carries `Evidence()` with all lists empty does
**not**; archived tasks do not; `pm_run_log(id, has_evidence=False)` returns only the
evidence-less entries.

**US-PM-9-4 — the skill records structurally.** In the manner of
`tests/test_skill_verdict_verbs.py`: the rendered `skill_pm_orchestrate.md.j2` step 19
shows `evidence=` on `pm_accept`, states the ≤ 200-char one-line note rule, and no longer
instructs the orchestrator to list files or test results inside the note.

**US-PM-9-5 — median note length.** Add `note_lengths(calls) -> Distribution` to
`tools/usage_telemetry/report.py` beside `completion_logging`, sampling
`len(call.input["note"])` over every call carrying a `note` argument (`ToolCall.input`,
`extract.py:98`, already holds it); surface `note_length_median` / `_p90` / `_p95` in
`baseline.py` next to `completions_without_run_log`. The unit test computes it over a
synthetic transcript fixture, as `tests/test_verdict_verbs_completion_logging.py` computes
its share. Proposed gate against the 4096 cap: **median ≤ 300 and p90 ≤ 800**. *Tension
flagged:* the live number cannot move until US-PM-9-9 ships and traffic accumulates, so the
test asserts the metric is correct on the fixture; the real-traffic gate is a `baseline.py`
report check, not a unit assertion.
