# Error-return path inventory

Every site in the MCP server (and the hub code it delegates to) that returns an
error as a **response body** instead of raising, with a classification per site.

This document is the input to:

- **US-PM-2-3** — raise genuine failures as real MCP errors (`is_error`)
- **US-PM-2-4** — keep expected negatives as successful, structured responses
- **US-PM-2-5 / US-PM-2-6** — the tests for both

It described the code **as it was** at v0.8.9. Nothing here changes
behaviour; US-PM-2-2 is inventory only. The counts below have since been
adjusted downward for the code US-PM-27 deleted — the sites in that removed
machinery are simply gone, and none of them had ever been reached in the
observed corpus.

**US-PM-35 (2026-09-06)** then deleted the whole cross-repo git family: the
hub-wide push, the hub-recovery tool and the branch-alignment check, together
with the `hub/registry.py` helpers behind them. Their rows are kept below as
*history* — the counts and the observed corpus are a 2026 measurement and are
not restated — but every one of them is now dead code that no tool can reach,
and each is marked **removed in US-PM-35**. Nothing in section 4 describes live
code any more. The surviving git surface is `pm_commit` / `pm_push` on one
store named by prefix, plus `projectman sync`.

---

## 1. How the inventory was built

The `grep -c 'return f"error' src/projectman/server.py` figure quoted in the
story finds **52** sites. It misses ten. Four passes were used:

| # | Method | Purpose |
|---|---|---|
| 1 | `grep -n 'return f"error\|return "error'` over `src/projectman/` | the literal-prefix baseline (52 + 4 non-f-string) |
| 2 | **AST walk** of every `ast.Return` in every `.py` under `src/projectman/`, resolving each return to its enclosing function, then regex-filtering the *rendered source segment* for `error / not found / failed / invalid / must be / required / cannot / unable` | catches multi-line returns, `dict` returns, `_yaml_dump({...})` returns and returns of a variable — grep on a single line cannot see these |
| 3 | **AST enumeration of every return inside every `@mcp.tool` function** (123 returns across 46 tools at v0.8.9), then manual read of every return that was *not* a plain success payload | proves the error set is complete by elimination rather than by pattern — an error return that used no error-ish word at all would still be caught here |
| 4 | Call-graph check: which `hub/registry.py` functions are reachable from an `@mcp.tool` | separates error strings that reach an MCP caller from ones that only reach the CLI |

Scripts used are throwaway; both are reproducible from the description above.
Pass 3 is the completeness argument: every tool, every return, every one read.

### What the extra ten are

Pass 1 finds 52. The ten it misses:

- 3 × `return "error: ..."` — a plain string, not an f-string
  (`server.py:1345, 1498, 1730`)
- 6 × structured error payloads that never contain the literal token
  `return f"error` — `pm_grab`'s not-ready early return and the five
  `{"status": "error", ...}` returns in `pm_web_start` / `pm_web_stop`
  (`server.py:1164, 2339, 2352, 2363, 2396, 2424`)

Those six matter disproportionately: **they are invisible even to the telemetry
scanner**. `tools/usage_telemetry/classify.py` anchors its soft-error patterns
at the start of the body (`^\s*\{\s*"result"\s*:\s*"error:` and `^\s*error:`).
A `_yaml_dump` of `{"status": "error", ...}` renders as `status: error\nerror:
...`, which matches neither. `pm_grab`'s not-ready payload renders as
`error: task is not ready to grab` and *does* match — by luck of dict ordering,
not by design.

### Totals

| Location | Sites | Reaches an MCP caller |
|---|---:|---|
| `server.py` — generic `except Exception as e: return f"error: {e}"` | 40 | yes |
| `server.py` — parameterised `return f"error: ..."` inside the `try` | 7 | yes |
| `server.py` — `return "error: ..."` (plain string) | 3 | yes |
| `server.py` — structured error payloads (no `error:` prefix token) | 6 | yes |
| **`server.py` subtotal** | **56** | |
| `hub/registry.py` — reachable from a tool (the cross-repo push, hub-recovery and branch-alignment helpers; all **removed in US-PM-35**) | 27 | yes, as a nested `error` key, at the time of measurement |
| `hub/registry.py` — CLI/hub-internal only (`set_branch`, `add_project`, `sync`) | 11 | no |
| `cli.py:26`, `orchestrator_api.py:95`, `web/app.py:31` | 3 | no (CLI / HTTP) |
| **Total error-return sites found** | **97** | **83** |

**56 in `server.py`, still more than the grep finds.** 83 sites can reach an MCP
caller once the hub delegation path is counted.

---

## 2. Observed frequency (real corpus)

`python -m tools.usage_telemetry.classify` over the live transcript corpus:

```
calls                 3444
  hard errors             47    1.36%  (is_error)
  soft errors            171    4.97%  (error body, is_error false)
  malformed inputs        27    0.78%
  COMBINED (distinct)    218    6.33%  true failure rate
```

Every distinct soft-error message in the corpus, joined to its source site:

| Count | Tool | Message | Source site | Class |
|---:|---|---|---|---|
| 147 | `pm_update` | `Run-log note must be 1024 characters or fewer` | `server.py:1112` (generic) ← `store.py` ValueError | **already fixed** — see below |
| 12 | `pm_grab` | `task is not ready to grab` | `server.py:1164` | EXPECTED NEGATIVE |
| 4 | `pm_status` | `No .project/config.yaml found in any parent directory` | `server.py:203` (generic) ← `config.py:19` | GENUINE FAILURE |
| 2 | `pm_docs` | `No .project/config.yaml found in any parent directory` | `server.py:312` (generic) ← `config.py:19` | GENUINE FAILURE |
| 1 | the hub-recovery tool (**removed in US-PM-35**) | `No .project/config.yaml found in any parent directory` | `server.py:1350` (generic) ← `config.py:19` | GENUINE FAILURE, now unreachable |
| 1 | `pm_list_sprints` | `No .project/config.yaml found in any parent directory` | `server.py:2202` (generic) ← `config.py:19` | GENUINE FAILURE |
| 1 | `pm_docs` | `VISION.md not found` | `server.py:280` | EXPECTED NEGATIVE (ambiguous — see §5.1) |
| 1 | `pm_done_next` | `Run-log note must be 1024 characters or fewer` | **upstream only** — not in this checkout | already fixed upstream-equivalent |
| 2 | `pm_batch_get` | `result (N characters) exceeds maximum allowed tokens...` | **not ours** — Claude Code harness truncation | out of scope (see §6) |

### The 1024-char note cap is already gone in this checkout

**148 of the 171 observed soft errors (86.5%) come from a code path that no
longer exists here.** US-PM-1 replaced the reject-with-ValueError behaviour with
server-side truncation: `store.py:42 truncate_run_log_note()` truncates and
records the fact in `Store.last_note_truncation`, which `server.py:69
_note_truncation_fields()` folds into the response as `note_truncated: true`.
The oversized note is never rejected.

This changes the priority ordering for US-PM-2-3/2-4 substantially. The live
soft-error volume in this checkout is **23 calls, not 171**:

| Rank | Live volume | Source | Class |
|---:|---:|---|---|
| 1 | 12 | `pm_grab` not ready (`server.py:1164`) | EXPECTED NEGATIVE |
| 2 | 8 | `No .project/config.yaml` via 4 generic handlers | GENUINE FAILURE |
| 3 | 1 | `pm_docs` `VISION.md not found` (`server.py:280`) | EXPECTED NEGATIVE |
| — | 2 | `pm_batch_get` harness truncation | out of scope |

So the single highest-volume *remaining* soft error is the one that must **not**
become an error, and the second is the one that clearly must. Both tasks have
real traffic behind them; neither is speculative.

**71 of the 97 sites have zero observed traffic** — mostly the hub and web
families. They still need converting for consistency (US-PM-2's fourth AC is
"no tool returns a body beginning with the error prefix"), but they carry no
measured impact and should be done in bulk, last.

---

## 3. Site inventory — `server.py`

### 3.1 Generic `except Exception as e: return f"error: {e}"` — 40 sites

All 40 wrap an entire tool body. Every one is **GENUINE FAILURE**: the tool did
not do what it was asked and the caller has no structured way to learn that.
US-PM-2-3 should convert all 45 to raise (`ToolError`/re-raise) so `is_error` is
set.

| Line | Tool | What can reach it |
|---:|---|---|
| 203 | `pm_status` | `find_project_root` FileNotFoundError (**observed ×4**); store read errors |
| 226 | `pm_get` | config missing; `store.get` FileNotFoundError (`Item not found: <id>`) |
| 248 | `pm_batch_get` | config missing; `store.list_all` ValueError (`Unknown item type`) |
| 312 | `pm_docs` | `find_project_root` FileNotFoundError (**observed ×2**); read errors |
| 353 | `pm_update_doc` | config missing; write errors |
| 407 | `pm_active` | config missing; index read errors |
| 476 | `pm_search` | config missing; embeddings/index errors |
| 630 | `pm_board` | config missing; index read errors |
| 670 | `pm_burndown` | config missing; sprint read errors |
| 733 | `pm_create_story` | config missing; pydantic `ValidationError`; write errors |
| 768 | `pm_create_epic` | config missing; `ValidationError`; write errors |
| 850 | `pm_epic` | `store.get_epic` FileNotFoundError (`Epic not found`) |
| 926 | `pm_context` | config missing; item lookup failures |
| 966 | `pm_create_task` | `store` FileNotFoundError (`Story not found`); `ValidationError`; dependency `ValueError` |
| 1004 | `pm_create_tasks` | as above, plus partial-batch failures |
| 1112 | `pm_update` | `Item not found`; `ValidationError`; dependency-cycle `ValueError` (`store.py:877`). **Historically also the 1024-note cap — now fixed** |
| 1134 | `pm_archive` | `Item not found` |
| 1259 | `pm_grab` | `store.get_task` FileNotFoundError (`Task not found`); readiness/store failures. *Distinct from the not-ready path at 1164* |
| 1282 | `pm_estimate` | `Item not found`; estimator failures |
| 1302 | `pm_scope` | `Item not found`; scoper failures |
| 1328 | `pm_audit` | config missing; audit failures |
| 1350 | hub-recovery tool (**removed in US-PM-35**) | `find_project_root` FileNotFoundError (**observed ×1**) |
| 1370 | branch-alignment check (**removed in US-PM-35**) | config missing; git failures in the branch validator |
| 1437 | `pm_malformed` | config missing; directory read errors |
| 1537 | `pm_fix_malformed` | `ValidationError`; write errors |
| 1589 | `pm_restore` | parse/write errors |
| 1618 | `pm_reindex` | config missing; index write errors |
| 1648 | `pm_auto_scope` | config missing; scoper failures |
| 1690 | `pm_git_status` | config missing; `git_status_all` failures |
| 1733 | `pm_commit` | `RuntimeError/ValueError/FileNotFoundError` — **includes `store.py:1420 RuntimeError("No .project/ changes to commit")`, an expected negative (§5.2)** |
| 1735 | `pm_commit` | catch-all `Exception` |
| 1770 | `pm_push` | `RuntimeError` — `store.py:1546 Push failed: <stderr>` |
| 1772 | `pm_push` | catch-all `Exception` |
| 1811 | hub-wide push (**removed in US-PM-35**) | config missing; cross-repo push failures |
| 2082 | `pm_create_sprint` | `ValidationError`; write errors |
| 2175 | `pm_get_sprint` | `Sprint not found: <id>` (`store.py:1313`) |
| 2202 | `pm_list_sprints` | `find_project_root` FileNotFoundError (**observed ×1**) |
| 2287 | `pm_update_sprint` | `Sprint not found`; `ValidationError` |
| 2571 | `pm_activity` | config missing; JSONL parse errors |
| 2600 | `pm_run_log` | config missing; `Item not found` |

**Note for US-PM-2-3:** line 1733 is the one generic handler that a legitimate
expected negative currently flows through. US-PM-2-4 must intercept
`nothing_to_commit` *before* 2-3's re-raise, or that path regresses.

### 3.2 Parameterised `return f"error: ..."` inside the `try` — 7 sites

| Line | Tool | Message | Trigger | Class |
|---:|---|---|---|---|
| 277 | `pm_docs` | `unknown doc '<doc>'. Use: project, infrastructure, ...` | caller passed a value outside the enum | **GENUINE FAILURE** — argument validation |
| 280 | `pm_docs` | `<FILENAME> not found` | the requested doc has not been created in this project (**observed ×1: `VISION.md`**) | **EXPECTED NEGATIVE** — see §5.1 |
| 347 | `pm_update_doc` | `unknown doc '<doc>'. Use: ...` | same as 277 | **GENUINE FAILURE** — argument validation |
| 1324 | `pm_audit` | `project '<p>' not found in hub` | caller named a hub project that is not registered | **GENUINE FAILURE** — asserted identifier |
| 1482 | `pm_fix_malformed` | `<filename> not found in malformed/` | caller named a malformed file that is not there | **GENUINE FAILURE** — see §5.3 |
| 1562 | `pm_restore` | `<filename> not found in malformed/` | same | **GENUINE FAILURE** — see §5.3 |
| 1677 | `pm_git_status` | `project '<p>' not found in hub status` | caller named an unregistered project | **GENUINE FAILURE** — asserted identifier |

### 3.3 `return "error: ..."` (plain string) — 3 sites

| Line | Tool | Message | Trigger | Class |
|---:|---|---|---|---|
| 1345 | hub-recovery tool (**removed in US-PM-35**) | `not a hub project` | hub-only tool called in a non-hub repo | **GENUINE FAILURE** — same class as "wrong directory" |
| 1498 | `pm_fix_malformed` | `story_id is required for tasks` | required conditional argument omitted | **GENUINE FAILURE** — argument validation |
| 1730 | `pm_commit` | `No .project/ changes to commit` | working tree clean | **EXPECTED NEGATIVE** — see §5.2 |

### 3.4 Structured error payloads the grep cannot see — 6 sites

| Line | Tool | Payload | Trigger | Class |
|---:|---|---|---|---|
| 1164 | `pm_grab` | `{"error": "task is not ready to grab", "blockers": [...]}` | readiness check failed (**observed ×12**) | **EXPECTED NEGATIVE** — story AC names this explicitly |
| 2339 | `pm_web_start` | `{"status": "error", "error": "Port N is already in use", "suggestion": ...}` | port bind check failed | **GENUINE FAILURE** — see §5.4 |
| 2352 | `pm_web_start` | `{"status": "error", "error": "Web dependencies not installed..."}` | `import uvicorn/fastapi` ImportError | **GENUINE FAILURE** — environment |
| 2363 | `pm_web_start` | `{"status": "error", "error": "No project found: <e>"}` | `find_project_root` failed | **GENUINE FAILURE** — same class as the 8 observed config-missing errors |
| 2396 | `pm_web_start` | `{"status": "error", "error": "<e>"}` | `subprocess.Popen` failed | **GENUINE FAILURE** |
| 2424 | `pm_web_stop` | `{"status": "error", "error": "<e>"}` | `terminate()`/`kill()` failed | **GENUINE FAILURE** |

### 3.5 Already-correct expected negatives — no change required

These are the *shape* US-PM-2-4 should copy: a success response carrying a
structured reason, with no `error:` token anywhere.

| Line | Tool | Payload | Meaning |
|---:|---|---|---|
| 1418 | `pm_malformed` | `"no malformed files"` | the search legitimately found nothing |
| 1616 | `pm_reindex` | `"reindexed: index.yaml (embeddings not available)"` | degraded but successful |
| 2329 | `pm_web_start` | `{"status": "already_running", ...}` | the desired end-state already holds |
| 2413 | `pm_web_stop` | `{"status": "not_running"}` | idempotent no-op |
| 2442 | `pm_web_status` | `{"running": false}` | a valid answer to a status question |
| 2450 | `pm_web_status` | `{"running": false, "exited_with": N}` | as above, with the reason |

US-PM-2-6 should assert none of these acquire `is_error`.

---

## 4. Site inventory — `hub/registry.py` (all removed in US-PM-35)

**This entire section is history.** At the time of measurement these 27 sites
returned a `dict` with an `error` key (or an `error:`-prefixed string) that a
tool then `_yaml_dump`ed into a **successful** response body, satisfying
US-PM-2's fourth AC only if the tool inspected the result first — and none did.

US-PM-35 deleted the cross-repo git family outright: the hub-wide push, the
hub-recovery tool, the branch-alignment check and every `hub/registry.py`
helper they reached. All 27 sites below are gone, none had ever been reached in
the observed corpus, and no recommendation here is still actionable. The rows
are kept only so the 97-site total above stays reconcilable.

| Lines | Family | Sites | Class (as measured) |
|---|---|---:|---|
| 265 | hub-recovery — `error: not a hub project` | 1 | **GENUINE FAILURE** |
| 2987, 2998, 3005, 3011, 3030, 3040, 3050, 3062 | per-project push — not-a-hub, project not registered / dir missing, invalid scope, branch-validation failures | 8 | **GENUINE FAILURE** |
| 2293, 2317, 2355, 2388 | hub push — not-a-hub, staging failed, commit failed, push failed | 4 | **GENUINE FAILURE** |
| 2090, 2109, 2123, 2209, 2213, 2225, 2238, 2242 | hub push with rebase — not-a-hub, push/fetch failed, submodule-ref conflict, rebase conflict, diverged | 8 | **GENUINE FAILURE** |
| 2247 | hub push with rebase — `push rejected after max retries` | 1 | **GENUINE FAILURE** |
| 2921, 2938, 2941, 2943 | subproject push — detached HEAD, push failed, git missing, generic | 4 | **GENUINE FAILURE** |
| 2547 | hub-wide push — `report: "error: not a hub project"` | 1 | **GENUINE FAILURE** |

What replaced it: `pm_commit` and `pm_push` act on exactly one store, named by
its prefix, running git inside that store's own repo; `projectman sync` is the
one hub-wide git verb and only pulls and re-attaches. Both raise through
`_failed` like every other tool, so the nested-`error`-key problem this section
described no longer has a code path.

### Not reachable from MCP — no action, listed for completeness

11 sites across `set_branch` (5), `add_project` (4) and `sync` (2). Plus `cli.py:26`
(template not found), `orchestrator_api.py:95` (HTTP 404 — already correct) and
`web/app.py:31` (HTTP 422 — already correct).

---

## 5. Ambiguous calls, with recommendations

These four are the judgement calls. Each has a decision so US-PM-2-3 and
US-PM-2-4 do not have to relitigate them.

### 5.1 `pm_docs` — `VISION.md not found` (`server.py:280`) → **EXPECTED NEGATIVE**

The argument for "failure": the caller asked for a specific document and did not
get it.

The argument for "expected negative", which wins: the six ProjectMan documents
are **optional by design**. `pm_docs()` with no argument returns a summary of
which ones exist precisely because a project is not required to have all of
them. Asking "show me the vision" in a project that has not written one is a
reasonable question with a valid, informative negative answer — it is a lookup
over an optional set, not an assertion that the file exists. Compare
`pm_malformed`'s `"no malformed files"` (§3.5), which is already handled this
way.

**Recommendation:** success response, e.g.
`{doc: vision, exists: false, path: .project/VISION.md, reason: not_created}`.
Note the contrast with line 277 (`unknown doc 'foo'`), which *is* a failure —
`foo` is not a member of the document set at all, so the caller passed a bad
argument rather than asking about an absent-but-valid document.

Observed ×1.

### 5.2 `pm_commit` — `No .project/ changes to commit` (`server.py:1730`, and via `store.py:1420` → `server.py:1733`) → **EXPECTED NEGATIVE**

The caller asked for `.project/` to be committed. It already is. The requested
end-state holds; nothing is broken; there is nothing for the caller to fix or
retry. This is structurally identical to `pm_web_stop`'s `not_running` (§3.5),
which is already a success.

Raising here would also be actively harmful: an orchestrator that runs
`pm_commit` after every task would log a failure on every clean loop.

**Recommendation:** success response,
`{committed: false, reason: nothing_to_commit}`.

**Implementation warning:** there are *two* routes to this message. The hub
route sets `result["nothing_to_commit"]` and hits line 1730; the non-hub route
raises `RuntimeError` from `store.py:1420` and is caught at line 1733. US-PM-2-4
must handle both, and must land before or together with US-PM-2-3's conversion
of 1733, or the non-hub route becomes a spurious error.

Observed ×0 (1 `pm_commit` soft error in the Study A study, message not
recorded).

### 5.3 `pm_fix_malformed` / `pm_restore` — `<filename> not found in malformed/` (`server.py:1482`, `1562`) → **GENUINE FAILURE**

The caller supplied a filename it must have obtained from a prior `pm_malformed`
call, and asserted that the file exists by asking for it to be fixed or
restored. Unlike §5.1 this is not a lookup over an optional set — it is a
**mutation** whose target does not exist, so the mutation did not happen and the
caller's model of the world is wrong. Silently returning success would let an
orchestrator believe it had drained the malformed queue when it had not.

**Recommendation:** raise. Include the current `malformed/` listing in the error
message so the caller can recover in one turn.

### 5.4 `pm_web_start` — `Port N is already in use` (`server.py:2339`) → **GENUINE FAILURE**

Tempting to call this an expected negative because the payload carries a helpful
`suggestion`. But the requested action — start a server — did not happen, and
the caller must do something different. Contrast with `already_running` (§3.5),
where the server *is* up and the caller's goal is met.

**Recommendation:** raise, keeping the suggestion text inside the error message.

### 5.5 Settled, non-ambiguous, restated for the record

- **`task is not ready to grab`** (`server.py:1164`) — EXPECTED NEGATIVE. The
  caller asked whether it could take a task and got a valid, informative no with
  a `blockers` list. Named explicitly in the story AC. Observed ×12 — the
  highest live volume of any remaining soft error. US-PM-2-4 should also drop
  the `error` key so the body no longer begins with `error:`; suggested shape
  `{grabbed: false, reason: not_ready, blockers: [...]}`.
- **`No .project/config.yaml found in any parent directory`** — GENUINE
  FAILURE, per the story guidance. Observed ×8 across `pm_status` (4),
  `pm_docs` (2), the hub-recovery tool removed in US-PM-35 (1),
  `pm_list_sprints` (1). It reaches the caller
  through the generic handlers, so US-PM-2-3's blanket conversion covers it with
  no per-site work.
- **`Item/Task/Story/Epic/Sprint not found: <id>`** — GENUINE FAILURE
  at every single-id site (`pm_get`, `pm_update`, `pm_archive`, `pm_grab`,
  `pm_estimate`, `pm_scope`, `pm_epic`, `pm_get_sprint`, `pm_update_sprint`,
  `pm_run_log`). The caller asserted the id. See §7 for the
  multi-id variant, which is different.
- **`<id> already exists: <path>`** — GENUINE FAILURE. Added by US-PM-24: every
  `Store.create_*` refuses rather than overwriting a file that is already
  there, raising `FileExistsError`. Every create tool (`pm_create_story`,
  `pm_create_epic`, `pm_create_task`, `pm_create_tasks`, `pm_create_sprint`)
  reaches the caller through its generic `except Exception` handler, so
  US-PM-2-3's blanket conversion already covers it — the class is exercised as
  `create_target_exists` in `tests/test_failure_classes_set_is_error.py`.
  US-PM-24-8 extended the rule to the two creates that do not go through the
  store: `pm_fix_malformed` (writes `<stories|tasks>/<id>.md` at a
  caller-supplied id) and `pm_restore` (moves the quarantined file onto its own
  name). Both raise `ToolError` themselves rather than a `FileExistsError` from
  the store, with the same `<id> already exists: <path>` text, and both leave
  the quarantined source in `malformed/` when they refuse.

---

## 6. Out of scope

**`pm_batch_get` — `result (191,164 characters) exceeds maximum allowed tokens.
Output has been saved to ...`** (2 occurrences). This is emitted by the Claude
Code harness after a successful tool return, not by ProjectMan. It matches the
soft-error pattern only because the harness writes its notice in the same
envelope. Neither US-PM-2-3 nor US-PM-2-4 can change it; the fix is a `brief` /
`fields` parameter on `pm_batch_get` (a separate concern, raised in
`an internal usage study` §5.3). US-PM-2-5/2-6 should exclude it from any
assertion over the corpus.

**`hub/rollup.py:70` — `{"name": <project>, "status": f"error: {e}"}`.** Found
by US-PM-2-3, outside the four passes above (which covered `server.py`,
`hub/registry.py`, `cli.py`, `orchestrator_api.py` and `web/app.py`).
Reachable from `pm_status` in hub mode via `server.py:809`. It is a **per-project
entry in a list**, so the response body never begins with `error:` and AC 4 is
not at stake; and a rollup over N projects where one index fails to load is a
genuine **partial success** — raising would discard the other N-1 projects'
data, the same reasoning §7.2 applies to multi-id results. Left as a body
deliberately. US-PM-2-6 should assert it stays one.

---

## 7. Port-forward notes

Written when this checkout was v0.8.9 and 12 commits behind `origin/main`: two
error paths existed upstream but not here, and needed the same treatment when
these changes were ported forward. §7.1 has since been ported in full — see its
status list.

### 7.1 `pm_done_next` — **ported, complete**

The tool has since landed in this checkout. It is the highest-traffic
note-bearing entry point (426 calls in the corpus; 338 calls / 25.1% soft-error
rate in the Study A study — the worst rate of any tool). It has its own copy
of the `except Exception as e: return f"error: {e}"` handler and its own run-log
note path.

Status of the three items this section called for:

- ✅ it calls `_note_truncation_fields()` and merges the result into its
  response, exactly as `pm_update` does (US-PM-1-3). The record is consumed
  immediately after the completion write, before the story-close and next-task
  updates that would otherwise reset it, so the flag survives the busy path —
  pinned by `TestDoneNext` in `tests/test_note_truncated_flag.py`.
- ✅ its generic handler raises through `_failed()`, US-PM-2-3's treatment.
- ✅ its "nothing ready follows" path is an **EXPECTED NEGATIVE** carrying
  `status: no_next_task`, US-PM-2-4's treatment — the shape §7.1 predicted, and
  the one `test_the_shape_pm_done_next_must_adopt_is_already_valid` pinned before
  the port.

### 7.2 Multi-id `pm_get` per-item `error` key

Upstream `pm_get` accepts comma-separated ids and returns a list where missing
items render as:

```yaml
- id: US-SK-8-1
  error: 'Task not found: US-SK-8-1'
- id: US-SK-8-5
  story_id: US-SK-8
  ...
```

Four such calls appear in the corpus, carrying 13 not-found items between them
(every one of those four calls also returned real data for other ids — i.e.
every observed occurrence is a *partial* success). This body does **not** begin with
`error:`, so it is correctly *not* counted as a soft error — but it still
violates US-PM-2's fourth AC in spirit, and the `error` key is what
`classify.py`'s docstring warns loose matching against.

**Recommendation:** rename the per-item key from `error` to `not_found: true`
(keeping a human-readable `message`), and set `is_error` only when **every**
requested id failed. A partial result is a genuine partial success and must stay
a success response — a caller batching 40 ids should not lose 39 good results
because one id was stale.

---

## 8. Summary

### Counts by classification

| Classification | Sites | Observed calls (corpus) | Live calls (this checkout) |
|---|---:|---:|---:|
| **GENUINE FAILURE** — should raise, set `is_error` (US-PM-2-3) | **86** | 156 | 8 |
| — `server.py` generic `except` handlers (§3.1) | 45 | 156 | 8 |
| — `server.py` explicit sites (§3.2 ×6, §3.3 ×3, §3.4 ×5) | 14 | 0 | 0 |
| — `hub/registry.py` reachable from a tool (§4) | 27 | 0 | 0 |
| **EXPECTED NEGATIVE** — must stay a success with a structured reason (US-PM-2-4) | **3** | 13 | 13 |
| — `pm_grab` not ready (`server.py:1164`) | 1 | 12 | 12 |
| — `pm_docs` doc not created (`server.py:280`) | 1 | 1 | 1 |
| — `pm_commit` nothing to commit (`server.py:1730`, plus the `1733` route) | 1 | 0 | 0 |
| **Error-return sites reaching an MCP caller** | **89** | **169** | **21** |
| **ALREADY CORRECT** — expected negatives with no `error:` token (§3.5) | 6 | 0 | 0 |
| **NOT MCP-REACHABLE** — `hub/registry.py` CLI-only | 49 | 0 | 0 |
| **OUT OF SCOPE** — `cli.py`, `orchestrator_api.py`, `web/app.py` | 3 | 0 | 0 |
| **OUT OF SCOPE** — Claude Code harness truncation (`pm_batch_get`) | — | 2 | 2 |
| **Total catalogued** | **147** | **171** | **23** |

Reading of the arithmetic: **141 error-return sites** exist (§1), of which
**89 reach an MCP caller** and need work — 86 genuine failures and 3 expected
negatives. Adding the 6 already-correct expected negatives of §3.5 (which are
not error returns, but which US-PM-2-6 must assert stay non-error) gives the
147 catalogued rows. Within `server.py`: 62 error-return sites = 59 genuine +
3 expected negative.

### Top sites by observed frequency

| Rank | Count | Site | Tool | Class | Still live here? |
|---:|---:|---|---|---|---|
| 1 | 147 | `server.py:1112` (generic) | `pm_update` | GENUINE FAILURE | **no** — fixed by US-PM-1 |
| 2 | 12 | `server.py:1164` | `pm_grab` | **EXPECTED NEGATIVE** | yes |
| 3 | 4 | `server.py:203` (generic) | `pm_status` | GENUINE FAILURE | yes |
| 4 | 2 | `server.py:312` (generic) | `pm_docs` | GENUINE FAILURE | yes |
| 4= | 2 | harness truncation | `pm_batch_get` | out of scope | n/a |
| 6 | 1 | `server.py:280` | `pm_docs` | **EXPECTED NEGATIVE** | yes |
| 6= | 1 | `server.py:1350` (generic) | hub-recovery tool | GENUINE FAILURE | **no** — removed in US-PM-35 |
| 6= | 1 | `server.py:2202` (generic) | `pm_list_sprints` | GENUINE FAILURE | yes |
| 6= | 1 | `pm_done_next` generic handler | `pm_done_next` | GENUINE FAILURE | **no** — routes through `_failed` (§7.1) |

### Recommended order of work

1. **US-PM-2-4 first, not second.** The single highest-volume live soft error
   (`pm_grab` not ready, ×12) must *not* become an error. Landing 2-3 first
   would briefly make 12 valid answers look like failures, and the `pm_commit`
   route at `server.py:1733` would regress outright.
2. **US-PM-2-3 on the 45 generic handlers.** One mechanical change, covers all 8
   live genuine failures and the entire `No .project/config.yaml` class.
3. **US-PM-2-3 on the 12 explicit `server.py` sites** (§3.2–3.4).
4. ~~**US-PM-2-3 on the hub path** — 3 call-site guards covering 27 registry
   sites.~~ **Moot.** US-PM-35 deleted the cross-repo git family and its
   registry helpers; those 27 sites no longer exist (§4).

## 9. Error codes

US-PM-2 made a genuine failure *visible* (`is_error`); US-PRJ-48 makes it
*classifiable*. Every failure raised through `_failed` carries a code from
`src/projectman/errors.py`, appended to the unchanged message as a trailing
` [code: <code>]` token.

### The taxonomy

`errors.ERROR_CODES` is the closed set. Each class also inherits the builtin
callers already catch, so no existing `except` clause changes behaviour.

| Code | Class (builtin) | Meaning | Raised by | Example wire text |
|---|---|---|---|---|
| `not_found` | `NotFoundError` (`FileNotFoundError`) | A requested epic/story/task/sprint/doc/path does not exist | `Store.get_*`, `Store.update`, `Store.create_task` under a missing story; reaches the wire from `pm_get`, `pm_update`, `pm_grab`, `pm_archive`, … | `Task not found: US-TST-9-9 [code: not_found]` |
| `invalid` | `ValidationError` (`ValueError`) | Caller input malformed, out of range or self-contradictory; includes `deps.CycleError` | `Store.update` (bad `depends_on`, unknown `clear` field), `Store.unarchive`, `deps.topo_sort` | `Task cannot depend on itself: US-TST-1-1 [code: invalid]` |
| `conflict` | `ConflictError` (`RuntimeError`) | The request clashes with the current state; includes `store.NothingToCommit` | `Store.commit_project_changes` — but `pm_commit` intercepts it and answers with the expected-negative shape (§5.2), so `conflict` is not seen on the wire today | `No .project/ changes to commit [code: conflict]` |
| `store` | `StoreError` (`RuntimeError`) | The on-disk store or a git operation against it failed; includes `worktree.MigrationError` | `Store.push` (detached HEAD, unknown remote, push failure), worktree migration | `Remote 'origin' not configured (available: none) [code: store]` |
| `permission` | `PermissionDeniedError` (`PermissionError`) | The filesystem refused the access the operation needed | No deliberate raise site — mapped from an OS `PermissionError` reaching any tool body | `[Errno 13] Permission denied: '.project/index.yaml' [code: permission]` |
| `internal` | `InternalError` | Unclassified — a bug, or an exception from a dependency | The generic `except Exception` every tool body still ends with (§3.1) | `<original message> [code: internal]` |
| `error` | `ProjectManError` | The base class's own default | Nothing raises the bare base class, so this does not appear on the wire; it is `code_for`'s answer for an exception outside the taxonomy | — |

`wire_code_for` also maps the builtins pre-taxonomy code still raises
(`FileNotFoundError` → `not_found`, `PermissionError` → `permission`,
`ValueError` → `invalid`) and falls back to `internal`, so the code on the
wire is always a member of `ERROR_CODES`.

### Backwards compatibility

* **Message text is unchanged.** The code is *appended*, never substituted;
  `str(exc)` still starts with exactly the prose it always was.
* **`is_error` is still set for every failure.** `CodedToolError` subclasses
  `ToolError`, so every `except ToolError` keeps matching and FastMCP still
  renders `isError=True`.
* **Builtin handlers keep working** — each class inherits the builtin it replaced.

### Reading the code

* **In-process** (`orchestrator_api`, the web routes, tests): read
  `CodedToolError.code` and `.message` — no text parsing at all.
* **Over the transport**: FastMCP re-wraps the raised error and prefixes
  `Error executing tool <name>: `, so a remote client sees the prefix, the
  original message, and the trailing ` [code: <code>]` token it can parse.
* **A `ToolError` raised directly by a tool passes through unsuffixed.** Its
  text is that tool's own contract — `pm_get`'s unknown-field message ends in
  a machine-parsed `valid names:` list a trailing token would corrupt — and
  `_failed` must not double-suffix an already-coded error caught by a nested
  call.

Asserted in `tests/test_errors.py`, `tests/test_store_error_codes.py` and the
"code on the wire" section of `tests/test_genuine_failures_raise.py`.
