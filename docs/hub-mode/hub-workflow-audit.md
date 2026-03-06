# Hub Git Workflow Audit: End-to-End Step Mapping

This document traces the exact manual steps a developer currently takes from a
ProjectMan operation to a fully pushed remote state, and counts the steps for
common scenarios.

---

## Architecture: Where Git Lives (and Doesn't)

### Store layer — zero git integration

`store.py` handles all PM data mutations (create/update/archive stories, tasks,
epics). Every method is a pure filesystem write via `pathlib.Path.write_text()`.
There are **no subprocess calls, no git imports, and no git operations** in the
store layer. Mutations write to `.project/stories/`, `.project/tasks/`,
`.project/epics/`, and `.project/config.yaml`.

### Server layer — zero git integration

`server.py` exposes MCP tools (`pm_create_story`, `pm_update`, `pm_grab`, etc.)
that delegate to the store. After each mutation it calls `write_index()` to
rebuild `.project/index.yaml` and summary markdown files. **No git operations.**

### Hub registry — submodule management only

`hub/registry.py` is the **only file** with git subprocess calls. These are
limited to three functions that manage submodules — they never touch PM data
versioning:

| Function       | Git operations                                      | PM data ops |
|----------------|-----------------------------------------------------|-------------|
| `add_project`  | `git submodule add [--branch] URL projects/NAME`    | Initializes `.project/projects/{name}/` |
| `set_branch`   | `git config -f .gitmodules ...` + `git submodule update --remote` | None |
| `sync`         | `git status --porcelain` + `git pull --ff-only` (per submodule) | None |

**Bottom line:** PM data is never auto-committed. The developer is fully
responsible for staging, committing, and pushing all `.project/` changes.

---

## End-to-End Workflow: PM Operation to Remote Push

### The complete sequence

```
PM Operation (e.g. pm_create_story, pm_update, pm_grab)
    |
    v
store.py writes .project/stories/*.md, .project/tasks/*.md, etc.
    |
    v
indexer.py rebuilds .project/index.yaml, INDEX-STORIES.md, etc.
    |
    v
*** FILES ON DISK — NOT IN GIT ***
    |
    v
Developer: git add .project/          (manual)
    |
    v
Developer: git commit -m "..."        (manual)
    |
    v
Developer: git push                   (manual)
```

For hub mode with submodules, the developer must also handle each subproject's
git lifecycle independently.

---

## Step Counts by Scenario

### Scenario 1: Update 1 task in a single-project setup

A developer marks a task as done and pushes.

| # | Step                              | Who       | Automated? |
|---|-----------------------------------|-----------|------------|
| 1 | `pm_update(task_id, status=done)` | Developer | Yes (MCP)  |
| 2 | `git add .project/`              | Developer | **No**     |
| 3 | `git commit -m "close task X"`   | Developer | **No**     |
| 4 | `git push`                       | Developer | **No**     |

**Manual steps: 3** (git add, commit, push)

---

### Scenario 2: Update 1 project in hub mode (PM data + code changes)

A developer finishes a task that involved code changes in a submodule.

| #  | Step                                          | Location    | Automated? |
|----|-----------------------------------------------|-------------|------------|
| 1  | `pm_update(task_id, status=done)`             | Hub         | Yes (MCP)  |
| 2  | Edit source code in `projects/my-api/`        | Submodule   | Yes (editor)|
| 3  | `cd projects/my-api && git add .`             | Submodule   | **No**     |
| 4  | `cd projects/my-api && git commit -m "..."`   | Submodule   | **No**     |
| 5  | `cd projects/my-api && git push`              | Submodule   | **No**     |
| 6  | `cd hub-root && git add projects/my-api`      | Hub         | **No**     |
| 7  | `cd hub-root && git add .project/`            | Hub         | **No**     |
| 8  | `cd hub-root && git commit -m "..."`          | Hub         | **No**     |
| 9  | `cd hub-root && git push`                     | Hub         | **No**     |

**Manual steps: 7** (steps 3-9)

Note: Steps 6-7 could be combined (`git add projects/my-api .project/`), but
they are logically distinct operations — one updates the submodule ref, the
other updates PM data. Forgetting either produces inconsistent state.

---

### Scenario 3: Update 5 projects simultaneously in hub mode

A developer closes tasks across 5 submodules (code changes in each).

| #     | Step                                           | Count | Automated? |
|-------|------------------------------------------------|-------|------------|
| 1-5   | `pm_update(task_id, status=done)` x5           | 5     | Yes (MCP)  |
| 6-10  | `cd projects/{name} && git add .` x5           | 5     | **No**     |
| 11-15 | `cd projects/{name} && git commit` x5          | 5     | **No**     |
| 16-20 | `cd projects/{name} && git push` x5            | 5     | **No**     |
| 21-25 | `cd hub && git add projects/{name}` x5         | 5     | **No**     |
| 26    | `cd hub && git add .project/`                  | 1     | **No**     |
| 27    | `cd hub && git commit -m "..."`                | 1     | **No**     |
| 28    | `cd hub && git push`                           | 1     | **No**     |

**Manual steps: 22** (steps 6-28)

Formula for N projects: **3N + 3** manual steps
(N adds + N commits + N pushes in submodules, plus N submodule ref adds +
1 `.project/` add + 1 hub commit + 1 hub push)

| Projects | Manual steps |
|----------|-------------|
| 1        | 6           |
| 2        | 9           |
| 5        | 18          |
| 10       | 33          |

---

### Scenario 4: PM-only update in hub mode (no code changes)

A developer reorganizes stories/tasks without touching any submodule code.

| # | Step                              | Location | Automated? |
|---|-----------------------------------|----------|------------|
| 1 | PM operations (create, update)    | Hub      | Yes (MCP)  |
| 2 | `git add .project/`              | Hub      | **No**     |
| 3 | `git commit -m "..."`            | Hub      | **No**     |
| 4 | `git push`                       | Hub      | **No**     |

**Manual steps: 3**

---

### Scenario 5: Sync + update cycle

A developer starts their day by syncing, then works on a task.

| #  | Step                                          | Automated? |
|----|-----------------------------------------------|------------|
| 1  | `projectman sync`                             | Yes (CLI)  |
| 2  | Verify sync results (check for skipped/failed)| **No**     |
| 3  | `pm_grab(task_id)`                            | Yes (MCP)  |
| 4  | Edit code in submodule                        | Yes (editor)|
| 5  | `cd projects/X && git add .`                  | **No**     |
| 6  | `cd projects/X && git commit`                 | **No**     |
| 7  | `cd projects/X && git push`                   | **No**     |
| 8  | `cd hub && git add projects/X .project/`      | **No**     |
| 9  | `cd hub && git commit`                        | **No**     |
| 10 | `cd hub && git push`                          | **No**     |

**Manual steps: 7** (steps 2, 5-10)

---

## Key Observations

1. **PM writes are fire-and-forget.** The store writes files and returns. No
   git staging, no commit, no push. The developer must remember to do all three.

2. **Hub mode multiplies the pain.** Every submodule is an independent git repo
   requiring its own add/commit/push cycle. The hub then needs its own cycle to
   update submodule refs and PM data.

3. **No transactional boundary.** A failure at any point in the chain (network
   drop during push, forgotten `git add`, typo in commit) leaves the system in
   an inconsistent state with no rollback mechanism.

4. **Directory switching is error-prone.** Developers must `cd` between
   submodule directories and the hub root. Working in the wrong directory
   silently commits to the wrong repo.

5. **The step count scales linearly.** At 3N + 3 manual steps for N projects,
   a 10-project hub requires 33 manual git operations for a full update cycle.

---

## Code References

- **Store mutations (no git):** `src/projectman/store.py` — all `create_*`,
  `update`, `archive` methods
- **Server MCP tools (no git):** `src/projectman/server.py` — all `pm_*` tools
- **Hub git operations:** `src/projectman/hub/registry.py`
  - `add_project()`: lines 32-81
  - `set_branch()`: lines 376-415
  - `sync()`: lines 418-481

---

*Document created: 2026-02-17 as part of EPIC-PRJ-1 / US-PRJ-1 / US-PRJ-1-4*
