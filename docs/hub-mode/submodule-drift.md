# Submodule Branch Tracking Drift: Failure Scenarios

This document catalogues concrete scenarios where submodule branch tracking
breaks in hub mode, with triggers, consequences, severity ratings, and recovery
difficulty for each.

**Related:** [workflow-pain-points.md](workflow-pain-points.md) (pain point #2),
[hub-workflow-audit.md](hub-workflow-audit.md)

---

## Scenario 1: Stale `.gitmodules` After `set-branch` — Wrong Branch Sync

### Trigger

1. Dev A runs `projectman set-branch auth feature/oauth2`
2. Dev A commits and pushes the hub (including updated `.gitmodules` and new
   submodule ref)
3. Dev B has **not pulled the hub** — their `.gitmodules` still says
   `projects/auth` tracks `main`
4. Dev B runs `projectman sync`

### What Goes Wrong

`sync()` calls `git pull --ff-only` inside each submodule directory
(`registry.py:463-464`). It does **not** read `.gitmodules` to determine the
expected branch — it simply fast-forwards whatever branch the local submodule is
currently on. Since Dev B's submodule is still on `main`, the pull updates
`main`, not `feature/oauth2`.

If Dev B then stages and pushes the hub:

```
cd hub-root
git add projects/auth .project/
git commit -m "sync updates"
git push
```

The hub's submodule ref now points at a `main` commit. Dev A's branch tracking
change is **silently overwritten**. The next person who pulls the hub and runs
`git submodule update` gets the `main` commit, not `feature/oauth2`.

### Severity: HIGH — Silent Data Loss

- No warning is displayed at any point
- Dev A's `set-branch` change is undone without anyone noticing
- Work on `feature/oauth2` becomes unreachable from the hub
- The `.gitmodules` file will also conflict when Dev B eventually pulls

### Recovery Difficulty: MEDIUM

1. Dev A must notice the regression (no automated detection exists)
2. Identify from `git log` when the submodule ref was overwritten
3. Re-run `projectman set-branch auth feature/oauth2`
4. Commit and push the hub again
5. Notify all team members to pull the hub before their next sync

### Root Cause

`sync()` has no pre-flight check comparing the local submodule branch against
`.gitmodules`. It trusts that the local checkout is already on the correct
branch. The `set-branch` change propagates only through `.gitmodules` in the hub
repo, which requires a hub pull to take effect.

---

## Scenario 2: `.gitmodules` / Local HEAD Branch Mismatch

### Trigger

1. Hub `.gitmodules` says `projects/payments` tracks `main`
2. A developer checks out `feature/refund-flow` locally inside the submodule:
   ```
   cd projects/payments
   git checkout -b feature/refund-flow
   # ... work, commit locally ...
   ```
3. The developer does NOT run `projectman set-branch` to update `.gitmodules`
4. The developer pushes the submodule (`git push -u origin feature/refund-flow`)
5. The developer stages and pushes the hub:
   ```
   cd hub-root
   git add projects/payments
   git commit -m "payments: refund flow WIP"
   git push
   ```

### What Goes Wrong

The hub's submodule ref now points at a commit on `feature/refund-flow`, but
`.gitmodules` still says `branch = main`. This creates a **silent inconsistency**:

- **Another developer cloning the hub** runs `git submodule update --init` and
  gets a detached HEAD at the `feature/refund-flow` commit — but has no context
  about which branch it belongs to
- **`projectman sync`** on another machine pulls `main` (because `.gitmodules`
  says `main`), which may be behind the hub's recorded ref — the fast-forward
  succeeds but the submodule HEAD no longer matches the hub's expected commit
- **`git submodule update --remote`** fetches from `main` (per `.gitmodules`),
  potentially jumping the submodule backward to an older commit

### Severity: MEDIUM — Confusing State

- No data is lost (commits exist on both branches in the remote)
- But the hub's recorded ref and `.gitmodules` disagree about which branch the
  submodule should be on
- Different team members may end up on different branches depending on which
  git command they use to update
- Debugging requires understanding the difference between the submodule ref
  (a commit SHA) and the tracked branch (a `.gitmodules` setting)

### Recovery Difficulty: LOW

1. The original developer runs
   `projectman set-branch payments feature/refund-flow`
2. Commits and pushes `.gitmodules` to the hub
3. Other developers pull the hub and re-sync

**Or**, if the feature branch is done, merge it to `main` and update the hub
ref to the merged commit.

### Root Cause

Nothing in ProjectMan validates that the submodule's current branch matches the
branch specified in `.gitmodules`. The `set-branch` step is entirely manual and
easy to forget. `sync()` and `set_branch()` are independent operations with no
cross-validation.

---

## Scenario 3: `git submodule update --remote` Overwrites Local Work

### Trigger

1. A developer has uncommitted or committed-but-not-pushed changes in
   `projects/api/` on branch `main`
2. Someone (or a script) runs:
   ```
   git submodule update --remote projects/api
   ```
   This is what `set_branch()` runs internally (`registry.py:403-408`).

### What Goes Wrong

`git submodule update --remote` fetches the latest commit from the tracked
branch on the remote and **checks it out in the submodule**. This has different
effects depending on the submodule's state:

**Case A: Uncommitted changes (dirty working tree)**

```
$ git submodule update --remote projects/api
error: Your local changes to the following files would be overwritten by checkout:
        src/api/handler.py
Please commit your changes or stash them before you switch branches.
```

Git refuses the update. This is the **safe** case — but the error message is
cryptic when triggered by `projectman set-branch`, because the developer didn't
ask to switch branches.

**Case B: Committed but not pushed changes**

The local `main` has commits that the remote doesn't. `git submodule update
--remote` checks out the remote's `main` HEAD, which is **behind** the local
`main`. The submodule enters **detached HEAD state** at the remote commit. The
local commits still exist but are no longer reachable from HEAD:

```
$ git submodule update --remote projects/api
Submodule path 'projects/api': checked out 'abc123...'
$ cd projects/api
$ git status
HEAD detached at abc123
```

The developer's unpushed commits are now dangling. They exist in the local
reflog but are not on any branch. If the developer doesn't notice and continues
working, they create commits on a detached HEAD that are easy to lose.

**Case C: Local branch diverged from remote**

Same result as Case B — the remote commit is checked out, detaching HEAD. The
local divergent commits become dangling.

### Severity: HIGH — Potential Data Loss

- Case A: Safe (git refuses), but confusing error message
- Case B: Unpushed commits become dangling — recoverable via `git reflog` but
  easy to miss, especially if the developer doesn't check `git status`
- Case C: Same as B, with the added confusion that a merge may be needed

### Recovery Difficulty: MEDIUM (Case B/C)

1. Notice that HEAD is detached (`git status` in the submodule)
2. Find the lost commits: `git reflog` in the submodule
3. Re-create the branch: `git checkout -b main <lost-commit-sha>`
4. Push the branch: `git push --force-with-lease origin main`
5. Update the hub's submodule ref

If the developer does NOT notice the detached HEAD:
- They may commit on the detached HEAD, creating more dangling commits
- Eventually `git gc` may prune the unreachable commits (default: 90 days)
- Recovery then requires `git fsck --unreachable` or backup restoration

### Root Cause

`git submodule update --remote` is a **checkout** operation, not a **merge** or
**pull**. It moves HEAD to the remote's latest commit without incorporating
local changes. The `set_branch()` function uses this command without checking
whether the submodule has local commits that would be orphaned.

---

## Scenario 4: Detached HEAD After Hub Clone

### Trigger

1. A new developer (or CI) clones the hub:
   ```
   git clone --recurse-submodules https://github.com/org/hub.git
   ```
   Or clones and initializes separately:
   ```
   git clone https://github.com/org/hub.git
   cd hub
   git submodule update --init
   ```

### What Goes Wrong

By default, `git submodule update --init` checks out the **exact commit** the
hub references for each submodule. It does NOT check out the branch specified in
`.gitmodules`. The result is that every submodule is in **detached HEAD state**:

```
$ cd projects/api
$ git status
HEAD detached at 7f3a2c1
$ git branch
* (HEAD detached at 7f3a2c1)
  main
```

This is standard git behavior, but it creates several problems in the
ProjectMan workflow:

**Problem 1: `projectman sync` fails or behaves unexpectedly**

`sync()` runs `git pull --ff-only` in each submodule. In detached HEAD state,
there is no upstream branch to pull from:

```
fatal: You are not currently on a branch.
To push the history leading to the current (detached HEAD)
state now, use

    git push origin HEAD:<name-of-remote-branch>
```

The sync reports this as an error but provides no guidance specific to the
detached HEAD problem.

**Problem 2: Developer commits on detached HEAD without realizing**

If the developer starts editing code without checking `git status`, their
commits are made on a detached HEAD. These commits are dangling and will be lost
if the developer checks out a named branch.

**Problem 3: Branch tracking is invisible**

`.gitmodules` says `projects/api` tracks `main`, but the submodule is not on
`main` — it's on a detached commit that happens to be on `main`. The developer
must know to run `git checkout main` in each submodule before starting work.
For a hub with 10+ projects, this is tedious and error-prone.

### Severity: MEDIUM — Confusing State

- No data is lost during the clone itself
- But the default state (detached HEAD) is a trap for developers who don't
  run `git checkout <branch>` before starting work
- Commits made on a detached HEAD are easily lost
- `projectman sync` fails with unhelpful error messages

### Recovery Difficulty: LOW (if caught early)

**Before any work is done:**
```bash
# Attach all submodules to their tracked branches
git submodule foreach 'git checkout $(git config -f $toplevel/.gitmodules submodule.$name.branch || echo main)'
```

**After commits on detached HEAD:**
1. `git reflog` in the affected submodule to find dangling commits
2. `git checkout main` (or the correct branch)
3. `git cherry-pick <detached-commits>` to apply them to the branch
4. Push and update the hub

### Root Cause

Git's default `submodule update` behavior is to check out a specific commit
(the one recorded in the superproject), not to check out the tracked branch.
This is by design — git prioritizes reproducibility over convenience. But
ProjectMan does not account for this: there is no post-clone setup step, no
`sync` pre-check for detached HEAD, and no warning when a developer runs
commands in a submodule with detached HEAD.

---

## Severity Summary

| #  | Scenario                                       | Severity | Data Risk             | Recovery   |
|----|------------------------------------------------|----------|-----------------------|------------|
| 1  | Stale `.gitmodules` after `set-branch`         | HIGH     | Silent ref overwrite  | Medium     |
| 2  | `.gitmodules` / local HEAD branch mismatch     | MEDIUM   | Confusing state       | Low        |
| 3  | `submodule update --remote` overwrites local   | HIGH     | Dangling commits      | Medium     |
| 4  | Detached HEAD after hub clone                  | MEDIUM   | Trap for new commits  | Low        |

## Common Thread

All four scenarios share the same root cause: **git submodule branch tracking is
a loosely coupled system with no validation layer.** The `.gitmodules` file, the
submodule's local branch, the submodule's HEAD commit, and the hub's recorded
submodule ref are four independent pieces of state that can drift apart silently.

ProjectMan's `sync()` and `set_branch()` each touch a subset of these without
verifying the others:

| State component        | `set_branch` touches? | `sync` touches? | Validated? |
|------------------------|-----------------------|-----------------|------------|
| `.gitmodules` branch   | Yes                   | No              | Never      |
| Submodule local branch | Indirectly            | Yes (pull)      | Never      |
| Submodule HEAD commit  | Yes (checkout)        | Yes (ff)        | Never      |
| Hub submodule ref      | No (manual git add)   | No (manual)     | Never      |

Until ProjectMan adds a validation layer that cross-checks these four state
components, branch tracking drift will remain a source of silent failures.

---

## Code References

- **`set_branch()`:** `src/projectman/hub/registry.py:376-415` — updates
  `.gitmodules` and runs `git submodule update --remote`
- **`sync()`:** `src/projectman/hub/registry.py:418-481` — runs
  `git pull --ff-only` per submodule, no branch validation
- **Dirty tree check:** `src/projectman/hub/registry.py:443-455` — skips
  submodules with uncommitted changes during sync

---

*Document created: 2026-02-17 as part of EPIC-PRJ-1 / US-PRJ-1 / US-PRJ-1-5*
