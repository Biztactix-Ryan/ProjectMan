# Readiness Warnings: Check or Template?

**Task:** US-PM-4-5 · **Story:** US-PM-4 — Remove the always-on readiness warnings
**Date:** 2026-07-29 · **Version:** v0.8.9
**Status:** DECIDED — the **CHECK** is at fault. `US-PM-4-6` should delete the three
warnings, not fix the templates.

This document is a determination, not an implementation. `readiness.py` behaviour is
unchanged by this task.

---

## Verdict in one line

The three warnings demand a document structure that **no code path in ProjectMan has ever
produced**, that the scoper actively guides agents *away* from, and whose only definition
lives in a Jinja template (`task.md.j2`) that is **dead code — referenced by nothing**.
The check tests for the output of a generator that does not exist.

---

## A. What exactly does `readiness.py` check?

`src/projectman/readiness.py:53-59`:

```python
body_lower = task_body.lower()
if "## implementation" not in body_lower:
    warnings.append("no Implementation section in description")
if "## testing" not in body_lower:
    warnings.append("no Testing section in description")
if "- [ ]" not in task_body:
    warnings.append("no Definition of Done checklist")
```

Character-by-character semantics, verified empirically:

| Check | Test | Case | Notes |
|---|---|---|---|
| Implementation | substring `"## implementation"` | **insensitive** (body lowered) | exactly two `#` + **one** space |
| Testing | substring `"## testing"` | **insensitive** | exactly two `#` + **one** space |
| DoD | substring `"- [ ]"` | **sensitive** (raw body) | hyphen, space, `[`, **one** space, `]` |

Observed pass/fail behaviour:

- `## Implementation`, `## implementation`, `## Implementation Plan` → pass.
- `### Implementation`, `#### Implementation` → **pass** (the `## ` substring is embedded
  in `### `). The check cannot actually enforce heading level.
- `##  Implementation` (two spaces), `**Implementation**`, `Implementation:`, `#Implementation` → **fail**.
- `## Tests`, `## Test Plan` → **fail**. Only the literal word "testing" satisfies it.
- `- [x] done`, `- [X] done`, `* [ ] item`, `-[ ] item` → **fail**.

That last row is a defect in its own right: **a task whose Definition of Done checklist is
fully completed (`- [x]`) is reported as having no Definition of Done checklist.** The
check is a raw substring match with no notion of markdown.

Nothing in the three warnings consults project config, the story, or any template. They are
unconditional string tests against a free-text body.

---

## B. What do ProjectMan's own generators produce?

Every producer of a task body was traced. **None emits any of the three structures.**

| Producer | Location | Emits `## Implementation` / `## Testing` / `- [ ]`? |
|---|---|---|
| `Store.create_task` | `src/projectman/store.py:744-792` | **No.** Writes the caller's `description` verbatim into `frontmatter.Post(content=description)`. No template, no wrapper, no default body. |
| `Store.create_tasks` (batch) | `src/projectman/store.py:794+` | **No.** Same verbatim path per entry. |
| `pm_create_story` auto test tasks | `src/projectman/store.py:410-418` | **No.** Body is hardcoded: `f"Verify acceptance criterion for story {story_id}:\n\n> {criterion}"`. Three lines, zero headings, zero checkboxes. This generator is *structurally incapable* of satisfying the check. |
| `pm_scope` guidance | `src/projectman/scoper.py:27-31, 216-220` | **No.** `task_template.description` is `"Include: what to implement, acceptance criteria, files to touch"` — prose guidance, no headings prescribed. |
| `pm_auto_scope` guidance | `src/projectman/scoper.py:125-137` | **No.** Same prose form. |
| `pm_create_task` / `pm_create_tasks` MCP tools | `src/projectman/server.py:1232+, 1272+` | **No.** Docstring says only "Task description with implementation details". No format contract. |
| `/pm-scope` skill | `templates/skill_pm_scope.md.j2` | **No.** Instructs on ordering and `depends_on`; says nothing about body structure. |
| `/pm-autoscope` skill | `templates/skill_pm_autoscope.md.j2` | **No.** Same. |
| `story.md.j2`, `epic.md.j2` | templates | Contain `- [ ]`, but for **stories and epics** — the readiness check only ever runs on **tasks**. |
| **`task.md.j2`** | `templates/task.md.j2:12-24` | **Yes — and it is dead code.** |

### The smoking gun: `task.md.j2` is orphaned

`src/projectman/templates/task.md.j2` is the *only* artifact in the repository defining the
demanded structure:

```markdown
## Implementation
<!-- Describe what needs to be done -->
## Testing
<!-- Describe how to verify this task -->
## Definition of Done
- [ ] Implementation complete
- [ ] Tests pass
- [ ] Code reviewed
```

A repo-wide search for the string `task.md.j2` across `*.py`, `*.md`, `*.j2`, `*.toml`,
`*.txt` (excluding `.venv`) returns **zero hits**. The two Jinja `Environment` sites —
`cli.py:18-24` and `hub/registry.py:210-217, 391-401` — enumerate their templates by name
(`config.yaml.j2`, `project.md.j2`, `epic.md.j2`, the six `skill_*.j2`, …) and `task.md.j2`
is not among them. It is never loaded, never rendered, never written.

So the readiness check is asserting conformance to a template that was disconnected from
(or never wired into) the task-creation path. `create_task` bypasses templating entirely.

### Corroboration: 118 real task files, 0 hits

`.project/tasks/*.md` in this repo are genuine artifacts of ProjectMan's own scoper:

```
task files:              118
containing "## Implementation":   0
containing "## Testing":          0
containing "- [ ]":               0
```

Not a low rate. **Zero.**

---

## C. Determination — the CHECK is wrong

The check is wrong on three independent grounds:

1. **It has no producer.** Every live generator writes free prose. The one template that
   would satisfy it is unreachable code. A conformance check with no conforming producer
   is not a quality gate; it is an assertion that the system is always broken.
2. **The design deliberately went the other way.** The scoper's `task_template` prescribes
   *semantic* content — "what to implement, acceptance criteria, files to touch" — not
   *structural* headings. `pm_create_story`'s auto-generated test tasks hardcode a
   three-line body. These are considered choices, made repeatedly, across `scoper.py`,
   `store.py`, and both scoping skills. The check is the outlier.
3. **It carries zero information.** A signal present in 100% of samples has zero entropy.
   Measured below.

The templates are not at fault because *there is no template in the path to be at fault*.
`task.md.j2` is not a broken template — it is an artifact of an abandoned design, and
`readiness.py:54-59` is the last code still referring to it.

---

## D. Would fixing the templates be desirable? No.

Suppose 4-6 instead wired `task.md.j2` into `create_task`. Consequences:

- **Every task body gains ~110 bytes of fixed boilerplate** (three headings plus three
  generic checkbox lines: "Implementation complete / Tests pass / Code reviewed"), on top
  of the real content the scoper already writes.
- That boilerplate is **identical on every task**, so it satisfies the check by
  construction and the warning becomes 100% *silent* — equally uninformative, just with
  the cost moved from the warnings block into every task body, and paid on *more*
  surfaces (`pm_get`, `pm_board`, `pm_scope`, story context blocks, the cache).
- **The corpus shows nobody wants it.** Across 3,527 calls the agents wrote bodies
  in exactly the prose form the scoper asked for. Only 45 `pm_update` calls in the Study B
  sample ever set `body`/`acceptance_criteria` — the warnings drove no remediation in
  either direction.
- The generic DoD ("Tests pass", "Code reviewed") duplicates what ProjectMan already
  models properly: auto-generated `Test:` tasks per acceptance criterion, and story-level
  acceptance criteria. Restating it as unchecked boilerplate in every task adds no gate.

Fixing the templates converts a noisy warning into silent per-task bloat and makes the
payload situation worse. Rejected.

---

## E. Recommendation for US-PM-4-6

**Delete the three warnings** — remove `readiness.py:54-59` (the `## implementation`,
`## testing`, and `- [ ]` blocks) outright.

Specifics:

1. In `check_readiness`, delete the three `warnings.append(...)` branches and the now-unused
   `body_lower = task_body.lower()` binding on line 53. **Keep** the `high points (N) —
   consider decomposing` warning at lines 51-52: it is genuinely conditional (fires only
   when `points > 5`) and does not appear in the always-on block.
2. **Do not touch `blockers`.** All hard gates — archived, status, assignee, points,
   `<50 chars`, parent story state, dependencies — stay exactly as they are. They are
   conditional and load-bearing; `pm_grab`'s `not_ready` path depends on them.
3. **Leave `compute_hints` alone** (`readiness.py:68-88`). It reads the same three
   structures but as *positive* hints (`has-impl-plan`, `has-test-plan`, `has-dod`) that
   are simply absent rather than emitted as noise, and it is consumed by `pm_board`
   (`server.py:861-866`) for ranking, not printed per-task. It costs nothing when the
   structures are missing. Optional cleanup, out of scope for 4-6.
4. **Delete `src/projectman/templates/task.md.j2`** as dead code, or leave it — either is
   defensible, but it must not be wired up. Note it in the commit so the next reader does
   not resurrect the check.
5. When `warnings` is empty, **omit the key entirely** from the `grabbed` payload
   (`server.py:1567`) rather than emitting `warnings: []`. An empty list still costs ~15
   bytes/call and reads as a meaningful signal.

Why not the alternatives:

- *Conditional on project default* — computing "would this fire on every item?" requires
  scanning all tasks on every grab. Real cost, and the answer is provably always "yes"
  because no generator emits the structures. Complexity for a constant.
- *Fold into a readiness score* — a score component that is 0 for every task in the corpus
  is a constant offset. It changes nothing and adds a number to explain.
- *Fix the templates* — rejected in section D.

For US-PM-4-4's test ("no warning has a 100% hit rate across a sample project"): the
natural implementation is to create N tasks via the normal `create_task`/`create_tasks`
path, run `check_readiness` on each, and assert no warning string appears in all N. That
test would fail today on all three and pass after the deletion.

---

## F. Measured cost on the real corpus

Source: `tools/usage_telemetry` over `~/.claude/projects` — **3,527 matched calls, 510
transcripts, 4,175,465 response bytes**, spanning **four independent projects**
(AzureDreamsV2, SolidKey-ESPSoftware, ProjectMan, SitRep).

### Hit rate — 100%, no exceptions

| Tool | Calls | Payloads carrying a task | Carrying all three warnings | Hit rate |
|---|---|---|---|---|
| `pm_grab` | 542 | 512 (30 were argument-validation errors) | 512 | **100.0%** |
| `pm_done_next` | 445 | 348 (97 returned `next: null`) | 348 | **100.0%** |
| `pm_get` | 427 | — | 1 | n/a (see below) |

- **864 payloads** in the corpus carry a warnings block. In **864 of 864 (100.00%)** all
  three warnings are present together.
- **Payloads carrying a warnings block but not all three: 0.** The three are perfectly
  correlated — they are effectively one 131-byte constant.
- The single `pm_grab`/`pm_done_next` payload that handed out work without the warnings
  turned out to be an error response (`"Run-log note must be 1024 characters or fewer"`),
  not a conforming task body. **No task body anywhere in the corpus satisfies any of the
  three checks.**
- Per-project rates are 100% in all four, so this is not a ProjectMan-repo artifact.

### Byte cost

- **131 bytes per affected payload** (`  warnings:\n` + three `  - <text>\n` lines).
- **113,303 bytes total ≈ 28,300 tokens** across the measured corpus.
- **2.71% of all ProjectMan response bytes** in the sample.
- Against `pm_grab`'s 1,404,894 bytes: 67,584 bytes, **4.8% of all `pm_grab` payload**.
- Against `pm_done_next`'s 516,076 bytes: 45,588 bytes, **8.8% of all `pm_done_next`
  payload** — the highest-density surface.

This is a real measurement, and it runs *ahead* of Study B's 758/98,500-char estimate
(864 occurrences, 113,303 bytes) because the corpus has grown.

### Correction to the story's framing

The story and acceptance criterion 3 say "payload size for `pm_grab` and `pm_get` drops".
**`pm_get` does not emit these warnings.** In v0.8.9 `check_readiness` has exactly two
call sites (`server.py:861` and `server.py:1473`), and only the `pm_grab` path at
`server.py:1567` puts `readiness["warnings"]` into a payload; `pm_board` uses the result
only for a `ready` boolean and emits `hints` instead. The corpus agrees: 1 of 427 `pm_get`
calls contains the string, and that is a nested quotation.

The affected surfaces are **`pm_grab` and `pm_done_next`**. (`pm_done_next` does not exist
in this checkout — `server.py:87` flags it as a port-forward — but it is present in the
builds that produced the corpus and calls the same helper.) US-PM-4-3 should measure
`pm_grab` and `pm_done_next`, not `pm_get`, or it will assert a drop that cannot occur.

### Live corroboration

The `pm_grab("US-PM-4-5")` response that opened this very task carried all three warnings —
on a task whose body is a fully-scoped two-paragraph description well over the 50-char
gate. Roughly 35 consecutive task payloads in this sprint session did the same.

---

## Evidence index

| Claim | Where to verify |
|---|---|
| Check source and semantics | `src/projectman/readiness.py:50-59` |
| Sole warning emission site | `src/projectman/server.py:1567` (`pm_grab`) |
| `check_readiness` call sites | `src/projectman/server.py:861`, `:1473` |
| `create_task` writes body verbatim | `src/projectman/store.py:780-784` |
| Auto test-task body is hardcoded | `src/projectman/store.py:414-416` |
| Scoper prescribes prose, not headings | `src/projectman/scoper.py:29`, `:137`, `:218` |
| Dead template | `src/projectman/templates/task.md.j2:12-24`; zero repo references |
| Jinja loaders that never list it | `src/projectman/cli.py:18-24`, `src/projectman/hub/registry.py:210-217, 391-401` |
| 0/118 real task files conform | `grep -li "## implementation" .project/tasks/*.md \| wc -l` |
| Corpus figures | `python -m tools.usage_telemetry.report` over `~/.claude/projects` |
