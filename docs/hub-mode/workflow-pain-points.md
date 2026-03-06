# Hub Git Workflow: Pain Points & Failure Modes

This document catalogues the current pain points, concrete failure scenarios, and
severity of issues in the hub's git workflow for managing submodules and project
management data.

---

## Current End-to-End Workflow

### What ProjectMan Automates vs. What Is Manual

**Automated by ProjectMan (registry.py):**
- `add_project()` — runs `git submodule add`, initializes PM data (`registry.py:32-81`)
- `set_branch()` — updates `.gitmodules` config, runs `git submodule update --remote` (`registry.py:376-416`)
- `sync()` — runs `git pull --ff-only` per submodule (`registry.py:418-482`)
- `repair()` — rebuilds indexes, embeddings, dashboards (`registry.py:141-373`)

**Entirely manual (no automation exists):**
- `git add` — staging any changed files (submodule refs, `.project/` data, `.gitmodules`)
- `git commit` — committing staged changes (in submodules or hub)
- `git push` — pushing commits to remote (in submodules or hub)

**Key gap:** `store.py` performs all PM mutations (create/update stories, tasks,
epics) by writing markdown files to `.project/`. It contains **zero git
operations** — no add, no commit, no push. Every PM write leaves dirty files
that the developer must manually commit.

### Scenario 1: Single Project Update (8 manual steps)

```
Step  Who         Action                                      Git state after
───── ─────────── ─────────────────────────────────────────── ─────────────────────
 1    ProjectMan  projectman sync                              Submodules updated
 2    Developer   Edit code in projects/my-api/                Dirty submodule
 3    Developer   cd projects/my-api && git add -A             Submodule staged
 4    Developer   cd projects/my-api && git commit -m "..."    Submodule committed
 5    Developer   cd projects/my-api && git push               Submodule pushed
 6    Developer   cd hub-root && git add projects/my-api       Hub ref staged
 7    MCP tools   pm_update(task, status="done")               .project/ dirty
 8    Developer   git add .project/ && git commit -m "..."     Hub committed
 9    Developer   git push                                     Hub pushed
```

**Manual steps: 6** (steps 3-6, 8-9). Steps 1 and 7 are automated.

### Scenario 2: Multi-Project Update — 5 Projects (22 manual steps)

```
 1    ProjectMan  projectman sync                              All submodules updated
 2-6  Developer   Edit code across 5 projects                  5 dirty submodules
───── Per submodule (×5): ──────────────────────────────────── ──────────────────────
 7    Developer   cd projects/{name} && git add -A             Submodule staged
 8    Developer   cd projects/{name} && git commit -m "..."    Submodule committed
 9    Developer   cd projects/{name} && git push               Submodule pushed
10    Developer   cd hub-root && git add projects/{name}       Hub ref staged
───── Hub finalization: ──────────────────────────────────────  ──────────────────────
27    MCP tools   pm_update(tasks/stories)                     .project/ dirty
28    Developer   git add .project/ .gitmodules                Hub data staged
29    Developer   git commit -m "..."                          Hub committed
30    Developer   git push                                     Hub pushed
```

**Manual steps: 22** — (4 per submodule × 5) + 3 hub steps.
Formula: **4N + 3** manual steps for N projects.

### Scenario 3: Add New Project to Hub (5 manual steps)

```
 1    ProjectMan  pm_add_project("billing", url, branch)       Submodule added
                  → git submodule add runs automatically       .gitmodules modified
                  → PM data initialized in .project/projects/  .project/ dirty
 2    Developer   git add .gitmodules projects/billing          Staged
 3    Developer   git add .project/                             PM data staged
 4    Developer   git commit -m "Add billing project"           Committed
 5    Developer   git push                                      Pushed
```

**Manual steps: 4** (steps 2-5). `add_project()` handles `git submodule add`
but does not commit or push the result.

### Scenario 4: Change Submodule Branch (4 manual steps)

```
 1    ProjectMan  pm_set_branch("auth", "feature/oauth2")      .gitmodules updated
                  → git config -f .gitmodules runs              Submodule updated
                  → git submodule update --remote runs
 2    Developer   git add .gitmodules                           Staged
 3    Developer   git add projects/auth                         New ref staged
 4    Developer   git commit -m "Track feature/oauth2"          Committed
 5    Developer   git push                                      Pushed
```

**Manual steps: 4** (steps 2-5). `set_branch()` updates the tracking config and
checks out the new branch, but does not commit or push.

### Scenario 5: PM-Only Update — No Code Changes (3 manual steps)

```
 1    MCP tools   pm_create_story(...), pm_update(task, ...)   .project/ dirty
 2    Developer   git add .project/                             Staged
 3    Developer   git commit -m "Update PM data"                Committed
 4    Developer   git push                                      Pushed
```

**Manual steps: 3** (steps 2-4). Even purely PM operations require manual git.

### Step Count Summary

| Scenario                     | Automated | Manual | Total | Formula   |
|------------------------------|-----------|--------|-------|-----------|
| Single project update        | 2         | 6      | 8     | —         |
| 5-project simultaneous update| 2         | 22     | 24    | 4N + 3    |
| Add new project              | 1         | 4      | 5     | —         |
| Change submodule branch      | 1         | 4      | 5     | —         |
| PM-only update (no code)     | 1         | 3      | 4     | —         |

---

## Pain Points

### 1. No Atomic Multi-Repo Commits — HIGH

**Problem:** PM data lives in the hub repo (`.project/`), while source code
lives in submodule repos (`projects/<name>/`). These are independent git
repositories. There is no mechanism to commit across both atomically.

**Concrete Scenario:**
> Alice updates 3 stories to "done" and modifies code in `projects/billing/`.
> She commits and pushes the billing submodule, then commits the hub with the
> updated `.project/` data and the new submodule ref. Between her submodule push
> and her hub push, her network drops. The billing code is pushed but the hub
> still references the old submodule commit and the old PM state. Anyone who
> pulls the hub now sees stale submodule refs and story statuses that don't
> reflect the pushed code.

**Impact:** Inconsistent state between hub and submodules that requires manual
investigation to resolve.

---

### 2. Submodule Branch Tracking Drift — HIGH

**Problem:** `set_branch()` updates `.gitmodules` to change which branch a
submodule tracks (`registry.py:392-409`). But if Person A changes the tracked
branch while Person B has the old `.gitmodules`, Person B's next `sync` pulls
from the **old** branch. The `.gitmodules` change only propagates when Person B
pulls the hub itself.

**Concrete Scenario:**
> Bob sets `projects/auth` to track `feature/oauth2` via
> `projectman set-branch auth feature/oauth2`. He commits and pushes the hub.
> Carol, who hasn't pulled the hub, runs `projectman sync`. Her `.gitmodules`
> still says `projects/auth` tracks `main`. She pulls `main` into her auth
> submodule, overwriting Bob's `feature/oauth2` checkout with the `main` branch
> HEAD. When she commits and pushes the hub, the submodule ref now points at a
> `main` commit — Bob's branch tracking change is effectively undone.

**Impact:** Silent data loss — pushes go to the wrong branch with no warning.

---

### 3. Dirty Working Trees Silently Skipped — MEDIUM

**Problem:** During `sync()`, if a submodule has uncommitted changes, it is
silently skipped with only a summary line in the output (`registry.py:452-455`).
There is no prominent warning or user prompt.

**Concrete Scenario:**
> Dave runs `projectman sync` expecting all 8 projects to update. Three have
> uncommitted changes from yesterday's work session. The sync summary says
> "5 updated, 3 skipped" but Dave doesn't read the details. He assumes
> everything is current and starts working against stale code in those 3
> submodules.

**Impact:** Developer works against outdated code without realizing it,
potentially introducing merge conflicts later.

---

### 4. Diverged Branches Have No Recovery Path — MEDIUM

**Problem:** `sync()` uses `git pull --ff-only` (`registry.py:464`). When
branches have diverged (local and remote both have commits the other doesn't),
the pull fails and the submodule is logged as "diverged, skipped (merge needed)"
(`registry.py:474-475`). There is no guided recovery, no suggested command, and
no way to resolve from within ProjectMan.

**Concrete Scenario:**
> Eve makes a local commit in `projects/payments/` but doesn't push. Meanwhile,
> Frank pushes a commit to the same branch on the remote. Eve runs
> `projectman sync`. The payments submodule reports "diverged, skipped (merge
> needed)." Eve has to leave ProjectMan, navigate to the submodule, decide
> between merge/rebase, resolve it manually, and then re-run sync. If she
> doesn't know git well, she may not know what to do.

**Impact:** Workflow interruption; requires manual git knowledge to resolve.

---

### 5. Detached HEAD State Not Detected — MEDIUM

**Problem:** `sync()` does not verify that submodules are on the expected branch
before pulling. If a submodule is in a detached HEAD state (common after
`git submodule update`), the `git pull --ff-only` may behave unexpectedly or
fail without a clear explanation.

**Concrete Scenario:**
> Grace runs `git submodule update` (without `--remote`) which checks out the
> exact commit the hub references, leaving the submodule in detached HEAD state.
> She then runs `projectman sync`. The `git pull --ff-only` in the submodule
> either fails (no tracking branch in detached state) or pulls to a branch
> that's different from what the hub expects. The error message ("fatal: not
> currently on any branch") doesn't explain what went wrong in PM terms.

**Impact:** Confusing error messages; submodule may end up on an unexpected
branch.

---

### 6. Hub-on-Main vs. Subproject Branching Tension — MEDIUM

**Problem:** The hub repository stays on `main` because project management data
(docs, stories, epics) should never be branched. But subprojects need
independent feature branches. This creates a fundamental tension: the hub's
`.gitmodules` and submodule refs are committed on `main`, but the submodules
themselves may be on various branches.

**Concrete Scenario:**
> The hub is on `main`. `projects/api` is on `feature/v2`. `projects/frontend`
> is on `main`. `projects/auth` is on `hotfix/cve-2026`. The hub's single
> `.gitmodules` file must somehow track all three different branches. When the
> hub is committed, the submodule refs point at specific commits on these
> disparate branches. A new team member cloning the hub gets a confusing mix:
> the hub is on `main` but submodules are scattered across branches with no
> obvious explanation of why.

**Impact:** Confusion for new team members; no clear "which version is
deployed" answer from the hub alone.

---

### 7. Conflicting Submodule Refs on Push — HIGH

**Problem:** When two people both update the same submodule and push the hub,
the second push may overwrite the first person's submodule ref. Git treats the
submodule ref as a simple pointer (a commit SHA). The second pusher's hub commit
will update the ref to their local submodule state, discarding the first
person's update.

**Concrete Scenario:**
> Alice and Bob both clone the hub. Alice advances `projects/billing` by 5
> commits and pushes both the submodule and the hub. Bob, working independently,
> advances `projects/billing` by 3 different commits (branched from the same
> starting point as Alice). Bob pushes the billing submodule to a different
> branch, then does `git pull` on the hub (which updates his `.gitmodules` from
> Alice's push), but his local `projects/billing` still points at his 3 commits.
> He runs `git add projects/billing && git commit && git push`. The hub now
> points at Bob's billing commit, and Alice's 5 commits are "lost" from the
> hub's perspective — they exist in the billing remote but the hub no longer
> references them.

**Impact:** Lost work — submodule refs silently overwritten. Requires manual
investigation of the billing repo's reflog to find Alice's commits.

---

### 8. No Validation After sync — LOW

**Problem:** After `sync()` completes, there is no verification that submodules
are on their expected branches, that refs match `.gitmodules`, or that the
working trees are clean. The sync just reports counts.

**Concrete Scenario:**
> A `git pull --ff-only` succeeds but the submodule's HEAD ends up on a
> different branch than `.gitmodules` specifies (e.g., if the remote branch was
> force-pushed and the local ref was updated to a rebased history). The sync
> reports "updated" but the submodule is now in a state the developer didn't
> expect.

**Impact:** False sense of confidence that everything is in order.

---

### 9. Deleted Remote Branches Not Handled — LOW

**Problem:** If the branch a submodule tracks is deleted on the remote,
`sync()` records a generic error with no specific guidance about the deleted
branch.

**Concrete Scenario:**
> A feature branch `feature/payments-v2` is merged and deleted on the remote.
> The hub's `.gitmodules` still tracks this branch for `projects/payments`.
> Running `projectman sync` produces an error like "error — couldn't find
> remote ref refs/heads/feature/payments-v2". The developer must manually
> identify that the branch was deleted, decide which branch to switch to, and
> run `projectman set-branch`.

**Impact:** Minor — requires manual branch update, but the error is not
self-explanatory.

---

### 10. Repair is All-or-Nothing — LOW

**Problem:** `repair()` (`registry.py:141-373`) scans every project, rebuilds
every index, regenerates all embeddings, and recreates all dashboards. There is
no option to repair a single project.

**Concrete Scenario:**
> A hub with 15 projects has a corrupted index in one project. Running
> `projectman repair` takes several minutes because it rebuilds indexes and
> embeddings for all 15 projects. The developer only needed to fix the one
> broken project.

**Impact:** Wasted time on large hubs; discourages running repair frequently.

---

## Failure Severity Summary

| #  | Pain Point                            | Severity | Category         |
|----|---------------------------------------|----------|------------------|
| 1  | No atomic multi-repo commits          | HIGH     | Data consistency  |
| 2  | Submodule branch tracking drift       | HIGH     | Silent data loss  |
| 7  | Conflicting submodule refs on push    | HIGH     | Silent data loss  |
| 3  | Dirty working trees silently skipped  | MEDIUM   | Poor feedback     |
| 4  | Diverged branches — no recovery path  | MEDIUM   | Missing tooling   |
| 5  | Detached HEAD not detected            | MEDIUM   | Missing validation|
| 6  | Hub-on-main vs. subproject branching  | MEDIUM   | Architectural     |
| 8  | No post-sync validation               | LOW      | Missing validation|
| 9  | Deleted remote branches not handled   | LOW      | Missing handling  |
| 10 | Repair is all-or-nothing              | LOW      | Performance       |

---

## Code References

- **sync logic:** `src/projectman/hub/registry.py:418-482`
- **set_branch:** `src/projectman/hub/registry.py:376-416`
- **repair:** `src/projectman/hub/registry.py:141-373`
- **dirty tree check:** `src/projectman/hub/registry.py:443-455`
- **divergence handling:** `src/projectman/hub/registry.py:472-478`

---

*Document created: 2026-02-16 as part of EPIC-PRJ-1 / US-PRJ-1*
