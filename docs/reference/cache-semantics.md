# Cache Semantics — What a Cached Read Hands You

**Tasks:** US-PRJ-37-5 (audit), US-PRJ-37-6 (decision + regression suite)
**Story:** US-PRJ-37 — Eliminate deep copy overhead on cached reads
**Date:** 2026-08-22 · **Status:** AUDITED and PINNED — no call-site changes were required.

Commit `03a1674` (0.8.4) removed the blanket `deepcopy` that every cached read used
to pay. This document records what the reader now actually receives, and the one
rule that keeps that safe.

---

## The rule

> **Treat every model and every list returned by a `get_*` / `list_*` call as
> read-only.** To change an item, either go through `Store.update()` /
> `Store.update_sprint()`, or take your own copy first:
> `meta.model_copy(update={"status": ...})`.

Mutating a returned model in place is not a local action. Without the deep copy,
the object you hold for a cached type *is the cache's object*: the next
`get_task()` in the same process hands the same instance to someone else, and your
edit is now their data — and it is not on disk, so it also disagrees with the file.
This applies to nested mutable fields too: `meta.tags.append(...)` and
`meta.depends_on.append(...)` mutate lists the cache shares.

The models are **not** `frozen`. None of the classes in `models.py` declare a
`model_config`, so Pydantic permits attribute assignment and nothing enforces the
rule above at runtime — "effectively immutable" is a convention here, not a
guarantee. Freezing them is feasible in principle but not free: `Store.update_sprint`
assigns via `setattr` and the changeset writers below assign attributes directly, so
all of those would have to move to `model_copy` first. That is a larger change than
this audit, and is left deliberately undone.

---

## What each cached-return site hands out

Three item types are cached: **stories**, **tasks**, **epics** (the module-level
`_cache`, keyed by `(project_dir, item_type)`). Sprints and changesets are **not
cached** — every read re-parses the file.

| Site | Returns | List identity |
| --- | --- | --- |
| `get_story` (store.py:1361) | cached `(meta, body)` | n/a — scalar |
| `list_stories` (store.py:1490) | cached models | fresh list comprehension |
| `get_epic` (store.py:1568) | cached `(meta, body)` | n/a — scalar |
| `list_epics` (store.py:1602) | cached models | fresh list comprehension |
| `get_task` (store.py:1827) | cached `(meta, body)` | n/a — scalar |
| `list_tasks` (store.py:1843) | cached models | fresh list comprehension |
| `list_tasks_with_bodies` (store.py:1865) | cached `(meta, body)` pairs | `list(result)` — fresh, even on the unfiltered path |
| `list_all` (store.py:1907) | fresh `model_dump()` dicts | fresh list; nothing cached escapes |
| `get` (store.py:2397) | dispatches to `get_epic`/`get_story`/`get_task`/`get_sprint` | inherits |
| `get_changeset` (store.py:2456) | fresh parse from disk | n/a — uncached |
| `list_changesets` (store.py:2465) | fresh parses from disk | fresh list — uncached |
| `get_sprint` / `list_sprints` (store.py:2559/2568) | fresh parses from disk | fresh list — uncached |
| `_read_stories_from_disk` / `_read_epics_from_disk` / `_read_tasks_from_disk` | fresh parses | fresh list — cache bypassed |

**No site returns `_cache[key]` itself.** A caller that does `.sort()` or
`.append()` on a returned list therefore cannot corrupt the cache — this is the
copy-on-write the story asked for, and it already holds. It is cheap and must stay:
if a future edit makes a list path return `all_entries` directly, wrap it in
`list(...)`.

The **models inside** those fresh lists are still the cache's own objects. The list
is copied; the elements are shared. That is the whole point of dropping the deep
copy, and it is why the rule above is about models, not lists.

---

## Audit of mutation sites

Every in-place attribute assignment on a fetched model in the codebase:

| Site | Object | Verdict |
| --- | --- | --- |
| `changesets.py:73-74` (`update_changeset_status`) | `ChangesetFrontmatter` from `get_changeset` | **Safe — uncached.** Freshly parsed per call, mutated, then immediately written back to the changeset file. |
| `changesets.py:229-233` (`check_pr_status`) | `ChangesetEntry` nested in the above | **Safe — uncached**, same object, written back at `changesets.py:266`. |
| `changesets.py:264-265` | `ChangesetFrontmatter` from `get_changeset` | **Safe — uncached**, written back on the next line. |
| `store.py:2487-2488` (`add_changeset_entry`) | `ChangesetFrontmatter` from `get_changeset` | **Safe — uncached**, written back immediately. |
| `store.py:2609/2641` (`update_sprint`) | `SprintFrontmatter` from `get_sprint` | **Safe — uncached**, written back immediately. |
| `server.py:4235-4236`, `server.py:4253-4254` | `ChangesetFrontmatter` from `get_changeset` | **Safe — uncached**, written back immediately in each branch. |

No mutation site touches a story, task, or epic — the three cached types. Nothing
needed converting to `model_copy`.

The write paths are clean for the same reason: `Store.update`,
`_write_test_task_sync` and `_write_test_task_archived` each re-`frontmatter.load`
the file, mutate the plain `post.metadata` dict, construct a **brand-new** model,
write it, and only then hand that new model to `_cache_update_entry`. They never
mutate the cached instance. `_cache_append` stores the freshly built model that
`create_story` / `create_epic` / `create_task` also return to the caller — so that
returned object is likewise under the read-only rule.

---

## The decision: shared instances, not per-item copies (US-PRJ-37-6)

US-PRJ-37's DoD asked that "mutating a returned model does not corrupt subsequent
reads". US-PRJ-37-3 proved it currently does. Three ways out were considered:

* **A — keep zero-copy, keep the read-only rule.** The hazard stays; the contract
  is the mitigation, and the suite instead pins that every *store write path*
  leaves the cache agreeing with disk.
* **B — return `model_copy()` per item** from `get_*`/`list_*`, with the two
  inner lists (`tags`, `depends_on`, plus `acceptance_criteria` on stories)
  copied too. Every frontmatter model is flat — scalars and `list[str]` — so
  this would give genuine isolation, not partial isolation.
* **C — freeze the models.** Rejected as out of scope: `update_sprint` and the
  changeset writers all assign attributes in place.

**A was chosen, on measurement.** On a 1000-task store (400-char bodies, mean of
20 runs, isolating the copy step from `_is_cache_stale`'s directory scan):

| Strategy | copy step, 1000 entries | vs. A | vs. old `deepcopy` |
| --- | --- | --- | --- |
| **A** — `list(entries)` | **0.003 ms** | 1× | **6380× faster** |
| B — per-item `model_copy` + inner lists | 4.38 ms | 1381× slower | 4.6× faster |
| old — `deepcopy(entries)` | 20.24 ms | 6380× slower | — |

End to end, `list_tasks()` on 1000 tasks costs **6.4 ms** under A and **11.6 ms**
under B (+5.2 ms, +82 % per call; the residue is the staleness `glob`+`stat`
sweep, not copying).

B is disqualified on the story's own accepted criterion: measured against the
`deepcopy` behaviour US-PRJ-37 removed, A is 6380× faster on the copy step while
B is only **4.6×** — below the "10x+ improvement for 1000-item lists" the story
requires. Adding back a copy that costs 82 % of a large list read, in a story
whose entire purpose is removing copy overhead, is not a trade worth making when
the audit above shows **no production caller mutates a cached story, task or
epic**. The hazard is real but unexercised; the rule at the top of this document
is what keeps it that way.

What makes A safe in practice is that the hazard is *bounded*, and both bounds
are now tested:

* a caller's in-place edit **never reaches disk** — the files stay the ground truth;
* the poisoned entry is healed by `clear_all_caches()` **and** by the item's next
  `Store.update`, because `update` re-reads the file and builds a brand-new model
  before touching the cache.

## Regression coverage

`tests/test_cache_integrity.py::test_mutating_returned_list_does_not_affect_cache`
pins the list-identity half of this contract for `list_tasks`, `list_stories`,
`list_epics` and `list_tasks_with_bodies`.
`tests/test_cache_integrity.py::test_mutating_a_returned_model_leaks_into_the_cache`
pins the other half as a **known limitation** (US-PRJ-37-3): a model returned by
`get_task`/`list_tasks` *is* the cache's instance, so `meta.tags.append(...)` and
`meta.status = ...` are both visible to the next reader and absent from disk. The
test asserts the hazard, not a guarantee — the read-only rule above is what keeps
callers safe.

The broad suite (US-PRJ-37-6) sits in the same file, running against a corpus of
3 epics / 10 stories / 50 tasks built through the Store API in a tmp directory
(module-scoped build, per-test copy, so a write test cannot leak into a read
test). It pins, in order:

| Test | Invariant |
| --- | --- |
| `test_repeated_reads_return_equal_data` | a read with no intervening write is idempotent |
| `test_repeated_reads_return_the_same_instances` | option A itself — reads share the cache's objects, including through `get()` dispatch. Fails the day someone reintroduces a per-read copy |
| `test_every_list_return_is_independent_of_the_cache` | 13 list-returning calls (every filter combination of `list_tasks`, `list_tasks_with_bodies`, `list_stories`, `list_epics`, plus all three `list_all` kinds) hand back the caller's own list |
| `test_write_paths_leave_the_cache_consistent_with_disk` | 20 write paths — `update` (status/fields/body/`clear`) on each kind, `create_task`/`create_story`/`create_epic`, `claim_task`, `archive` of each kind, `unarchive`, and bulk-shaped loops of 10 updates / 10 task archives / 3 story archives — each leave a cached read **equal to a cache-cleared disk read** |
| `test_a_write_is_visible_to_get_and_list_alike` | invalidation is not per-method: `get_task`, `get`, `list_tasks`, `list_tasks_with_bodies`, `list_all` and the status filter all see the write |
| `test_an_external_file_edit_invalidates_the_cache` | the `_is_cache_stale` mtime path, for tasks, stories and epics (mtime pinned with `os.utime`, so the test does not depend on filesystem timestamp granularity) |
| `test_an_external_file_deletion_invalidates_the_cache` | the file-count half of `_is_cache_stale`, which an mtime comparison alone misses |
| `test_a_leaked_model_edit_never_reaches_disk` | first bound on the hazard: ground truth is safe |
| `test_a_leaked_model_edit_is_healed_by_clearing_the_cache` | second bound: recovery is one `clear_all_caches()` away |
| `test_a_leaked_model_edit_is_healed_by_the_next_write` | third bound: `Store.update` rebuilds the entry from disk, so a stray edit cannot survive the item's next legitimate write |

The suite was checked against two deliberate mutants of `store.py` (reverted):
forcing `_is_cache_stale` to return `False` fails the 4 external-edit tests, and
adding a no-op `_cache_update_entry` on top of it fails 20 tests including every
`update`-based write path. The assertions bite.
