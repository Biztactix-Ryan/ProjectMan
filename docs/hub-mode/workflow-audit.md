# Hub Git Workflow Audit

Comprehensive audit of the current hub git workflow, its pain points, failure
modes, and recommendations for resolution. Compiled from detailed investigations
in [workflow-pain-points.md](workflow-pain-points.md),
[hub-workflow-audit.md](hub-workflow-audit.md),
[submodule-drift.md](submodule-drift.md), and
[multi-developer-conflicts.md](multi-developer-conflicts.md).

**Epic:** EPIC-PRJ-1 — Hub Push Workflow: Fix Submodule Commit & Push Alignment
**Story:** US-PRJ-1 — Audit & document current hub git workflow pain points

---

## 1. Current Workflow: End-to-End Steps

### Architecture

ProjectMan has **zero git integration** in its core layers:

- **Store layer** (`store.py`) — writes PM data to `.project/` via filesystem
  only. No git operations.
- **Server layer** (`server.py`) — exposes MCP tools that delegate to the store.
  No git operations.
- **Hub registry** (`hub/registry.py`) — the only file with git subprocess
  calls, limited to `add_project()`, `set_branch()`, and `sync()`. These manage
  submodules but never commit or push.

Every PM mutation leaves dirty files that the developer must manually stage,
commit, and push.

### Manual Step Counts

| Scenario                          | Automated | Manual | Total | Formula |
|-----------------------------------|-----------|--------|-------|---------|
| Single project update (hub mode)  | 2         | 7      | 9     | --      |
| 5-project simultaneous update     | 2         | 18     | 20    | 3N + 3  |
| 10-project simultaneous update    | 2         | 33     | 35    | 3N + 3  |
| Add new project to hub            | 1         | 4      | 5     | --      |
| Change submodule branch           | 1         | 4      | 5     | --      |
| PM-only update (no code changes)  | 1         | 3      | 4     | --      |
| Daily sync + work cycle           | 2         | 7      | 9     | --      |

The manual step count scales linearly: **3N + 3** for N subprojects. A
10-project hub requires 33 manual git operations for a full update cycle.

---

## 2. Pain Points Catalogue

### HIGH Severity

**PP-1: No Atomic Multi-Repo Commits**
PM data lives in the hub (`.project/`), source code lives in submodule repos.
A failure between the submodule push and the hub push (e.g., network drop)
leaves inconsistent state: pushed code with stale hub refs and PM data.

**PP-2: Submodule Branch Tracking Drift**
When Dev A changes a submodule's tracked branch via `set-branch`, Dev B (who
hasn't pulled the hub) still syncs from the old branch. Dev B can silently
overwrite the branch tracking change by pushing stale `.gitmodules` and
submodule refs. No warning at any point.

**PP-7: Conflicting Submodule Refs on Push**
Two developers advancing the same submodule produce different commit SHAs. Git
cannot auto-merge submodule refs — one developer's work becomes unreachable
from the hub. With `git add -A`, a developer can silently revert another's
submodule ref to an older commit.

### MEDIUM Severity

**PP-3: Dirty Working Trees Silently Skipped**
During `sync()`, submodules with uncommitted changes are skipped with only a
summary line. No prominent warning. Developers work against stale code without
realizing it.

**PP-4: Diverged Branches Have No Recovery Path**
`sync()` uses `git pull --ff-only`. When branches have diverged, the pull fails
with no guided recovery — the developer must leave ProjectMan and resolve
manually.

**PP-5: Detached HEAD State Not Detected**
After `git submodule update` (standard after clone), submodules are in detached
HEAD state. `sync()` fails with unhelpful errors. Developers may commit on a
detached HEAD, creating dangling commits that are easily lost.

**PP-6: Hub-on-Main vs. Subproject Branching Tension**
The hub stays on `main` (PM data should never branch), but subprojects need
independent feature branches. All submodule ref updates compete on one branch.
There is no isolation between concurrent work streams.

### LOW Severity

**PP-8: No Post-Sync Validation**
After `sync()`, there is no verification that submodules are on expected
branches, that refs match `.gitmodules`, or that working trees are clean.

**PP-9: Deleted Remote Branches Not Handled**
If a tracked branch is deleted on the remote, `sync()` reports a generic error
with no guidance about the deleted branch or which branch to switch to.

**PP-10: Repair is All-or-Nothing**
`repair()` rebuilds indexes and embeddings for every project. No option to
repair a single project. Discourages frequent use on large hubs.

---

## 3. Failure Mode Scenarios

### Submodule Branch Drift (4 scenarios)

| # | Scenario                                     | Severity | Data Risk            | Recovery   |
|---|----------------------------------------------|----------|----------------------|------------|
| D1 | Stale `.gitmodules` after `set-branch`       | HIGH     | Silent ref overwrite | Medium     |
| D2 | `.gitmodules` / local HEAD branch mismatch   | MEDIUM   | Confusing state      | Low        |
| D3 | `submodule update --remote` overwrites local | HIGH     | Dangling commits     | Medium     |
| D4 | Detached HEAD after hub clone                | MEDIUM   | Trap for new commits | Low        |

**Common root cause:** Git submodule branch tracking is a loosely coupled
system with no validation layer. `.gitmodules` branch, local branch, HEAD
commit, and hub submodule ref are four independent pieces of state that drift
apart silently. Neither `sync()` nor `set_branch()` cross-validates them.

### Multi-Developer Conflicts (4 scenarios)

| # | Scenario                               | Auto-Resolves? | Data Loss Risk | Recovery      |
|---|----------------------------------------|----------------|----------------|---------------|
| C1 | Different submodule refs (clean merge) | Yes            | None           | Trivial       |
| C2 | Same submodule ref (SHA conflict)      | No             | Medium         | Medium        |
| C3a | Stale hub, selective staging           | Yes            | None           | Trivial       |
| C3b | Stale hub, `git add -A`               | No             | **High**       | Medium        |
| C4a | Cron sync, no auto-commit             | N/A            | None           | Trivial       |
| C4b | Cron sync, auto-commit                | No             | Medium         | High          |

**Common root cause:** The hub is a single-branch, multi-writer repository
where submodule refs are opaque commit SHAs with no semantic merge strategy.
Combined with the hub-on-main constraint, every concurrent push is a potential
conflict.

**Highest-risk pattern:** `git add -A` in the hub, which silently stages stale
submodule refs and can revert other developers' work without warning.

---

## 4. Summary Table

| #    | Pain Point                           | Severity | Frequency    | Addressing Story |
|------|--------------------------------------|----------|--------------|------------------|
| PP-1 | No atomic multi-repo commits         | HIGH     | Every push   | US-PRJ-4, US-PRJ-10 |
| PP-2 | Submodule branch tracking drift      | HIGH     | On branch change | US-PRJ-2     |
| PP-7 | Conflicting submodule refs on push   | HIGH     | Concurrent devs | US-PRJ-11    |
| PP-3 | Dirty working trees silently skipped | MEDIUM   | Common       | US-PRJ-8         |
| PP-4 | Diverged branches — no recovery      | MEDIUM   | Occasional   | US-PRJ-4, US-PRJ-8 |
| PP-5 | Detached HEAD not detected           | MEDIUM   | After clone  | US-PRJ-2, US-PRJ-8 |
| PP-6 | Hub-on-main vs. subproject branching | MEDIUM   | Structural   | US-PRJ-7         |
| PP-8 | No post-sync validation              | LOW      | Every sync   | US-PRJ-2, US-PRJ-8 |
| PP-9 | Deleted remote branches not handled  | LOW      | Rare         | US-PRJ-2         |
| PP-10| Repair is all-or-nothing             | LOW      | On corruption| --               |
| --   | Manual git for all PM mutations      | HIGH     | Every mutation | US-PRJ-3, US-PRJ-5 |
| --   | Multi-project push friction (3N+3)   | HIGH     | Every push   | US-PRJ-4         |

---

## 5. Recommendations

Each recommendation maps to one or more stories in EPIC-PRJ-1 that address it.

### R1: Pre-Push Branch Validation (US-PRJ-2)

Add `validate_branches()` to cross-check every submodule's current branch
against `.gitmodules` tracking config before any push. Block pushes when
mismatches are detected. This directly prevents PP-2, PP-5, PP-8, and PP-9.

### R2: Hub-Aware Git Tools (US-PRJ-3)

Add `pm_commit` and `pm_push` MCP tools that understand hub structure. Auto-
generate commit messages from PM operations, auto-stage `.project/` files.
Eliminates 3 manual steps (add/commit/push) from every PM mutation.

### R3: Coordinated Multi-Project Push (US-PRJ-4)

A single command that validates all branches, pushes submodules in order, then
updates and pushes the hub. Reduces multi-project push from 3N+3 manual steps
to 1. Addresses PP-1 and PP-4 by ensuring consistent ordering and providing
clear failure reports.

### R4: Auto-Commit for PM Mutations (US-PRJ-5)

Optional config flag to auto-commit `.project/` changes after every PM
mutation. Eliminates the "fire-and-forget" gap where PM writes leave dirty
files. Does not auto-push — that remains explicit.

### R5: PR-Based Workflow for Subprojects (US-PRJ-7)

Route subproject changes through feature branches and PRs instead of direct
commits to deploy branches. Hub refs update only after PRs merge. Addresses
PP-6 by giving each subproject independent branching while the hub stays on
main. Adds review gates that prevent accidental pushes to wrong branches.

### R6: Git Status Dashboard (US-PRJ-8)

Single command showing git state of all submodules: branch, dirty/clean,
ahead/behind, PR status, mismatches with `.gitmodules`. Makes PP-3 (dirty
trees), PP-5 (detached HEAD), and PP-8 (no post-sync validation) immediately
visible instead of silently ignored.

### R7: Cross-Repo Changesets (US-PRJ-10)

Group related changes across N repos into a named changeset. Create PRs
together with cross-references. Gate hub ref updates on all PRs merging.
Addresses PP-1 at the workflow level by providing atomic-like semantics across
repos without requiring actual cross-repo transactions.

### R8: Hub Ref Conflict Resolution (US-PRJ-11)

Auto-rebase hub push conflicts when submodule refs are fast-forwardable. Flag
non-fast-forward conflicts for manual resolution. Log ref update history for
audit. Directly addresses PP-7.

### R9: Updated Workflow Documentation (US-PRJ-6)

Once the above tools exist, update all workflow documentation and the `/pm`
skill to route git operations through the new commands. Ensures the documented
workflow matches the tooling.

### Priority Order

| Priority | Story     | Addresses          | Rationale                              |
|----------|-----------|--------------------|----------------------------------------|
| 1        | US-PRJ-2  | PP-2, PP-5, PP-8, PP-9 | Prevents the most dangerous silent failures |
| 2        | US-PRJ-3  | Manual git gap     | Eliminates daily friction for every user |
| 3        | US-PRJ-4  | PP-1, PP-4         | Reduces multi-project push to one step  |
| 4        | US-PRJ-5  | Manual git gap     | Makes PM mutations self-contained       |
| 5        | US-PRJ-8  | PP-3, PP-5, PP-8   | Visibility into problems before they escalate |
| 6        | US-PRJ-7  | PP-6               | Structural fix for branching tension    |
| 7        | US-PRJ-11 | PP-7               | Requires coordinated push (US-PRJ-4) first |
| 8        | US-PRJ-10 | PP-1               | High-value but complex; builds on US-PRJ-4 and US-PRJ-7 |
| 9        | US-PRJ-6  | Documentation      | Update docs after tooling stabilizes    |

---

## 6. Acceptance Criteria Verification

- **Pain points documented with concrete scenarios** — 10 pain points
  catalogued with named developer scenarios, exact git command sequences, and
  impact descriptions. Submodule drift has 4 detailed scenarios; multi-developer
  conflicts have 4 detailed scenarios with git trace timelines.

- **Current workflow steps listed end-to-end** — 5 workflow scenarios mapped
  step-by-step with step counts, showing which steps are automated vs manual.
  Formula derived: 3N + 3 manual steps for N subprojects.

- **Failure modes catalogued with severity** — 10 failure modes rated HIGH
  (3), MEDIUM (4), or LOW (3). Each includes concrete trigger, consequences,
  recovery difficulty, and root cause. Summary tables provided for both drift
  and conflict categories.

---

## Detailed Source Documents

For full scenario details, git command traces, and code references:

- [workflow-pain-points.md](workflow-pain-points.md) — Pain point catalogue
  with all 10 items, workflow step tables, and code references
- [hub-workflow-audit.md](hub-workflow-audit.md) — End-to-end step mapping with
  5 scenarios and architecture analysis
- [submodule-drift.md](submodule-drift.md) — 4 detailed branch drift scenarios
  with state component cross-reference table
- [multi-developer-conflicts.md](multi-developer-conflicts.md) — 4 multi-
  developer conflict scenarios with conflict resolution matrix

---

*Compiled: 2026-02-17 as part of EPIC-PRJ-1 / US-PRJ-1 / US-PRJ-1-7*
