"""Field projection on `pm_get` and `pm_grab` (US-PM-10-6).

`pm_grab` and `pm_get` are ~50% of all context returned on ~25% of calls, and
the single worst case is a *verification* read: `pm-orchestrate` re-reads a
task after every worker to check its self-report, needs `status` and
`assignee`, and pays ~3,870 chars for them.  The read is correct — the skill's
core principle is that a worker's self-report is not trusted — so the fix is
to make it cheap, not to delete it.

The properties pinned here:

* **the default is byte-identical** — no `fields`, or an empty one, and the
  response is exactly what it was before this parameter existed;
* **projection is output-only** — `pm_grab` still claims the task on disk,
  whatever it returns;
* **`id` always survives** — a multi-ID result must stay addressable;
* **unknown names fail loudly** — a silent empty projection would make the
  orchestrator's verification read *vacuous* while still looking like it
  passed, which is worse than the cost it was meant to save;
* **it actually pays** — a status-only read is a small fraction of the full
  payload, measured, not asserted by construction.
"""

import anyio
import mcp.types as types
import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


@pytest.fixture(autouse=True)
def chdir_to_project(tmp_project, monkeypatch):
    monkeypatch.chdir(tmp_project)
    from projectman.server import _store_cache
    from projectman.store import clear_all_caches

    clear_all_caches()
    _store_cache.clear()


@pytest.fixture
def seeded(tmp_project):
    """One epic, one story with three ready tasks, one story with criteria.

    The criteria live on a *second* story on purpose: acceptance criteria
    auto-create their own verification tasks, which would otherwise take the
    ``US-TST-1-1`` … numbering the task tests here name.
    """
    from projectman.store import Store

    store = Store(tmp_project)
    store.create_epic("An Epic", "Epic body text that is long enough to matter.")
    store.create_story("Story", "Story body text long enough to matter.")
    store.update("US-TST-1", status="active", epic_id="EPIC-TST-1")
    for i in range(1, 4):
        store.create_task("US-TST-1", f"Task {i}", READY_BODY, points=1)
    store.create_story(
        "Story with criteria",
        "Second story.",
        acceptance_criteria=["It works", "It is fast"],
    )
    return store


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


def _on_disk(tmp_project, task_id: str):
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    return Store(tmp_project).get_task(task_id)[0]


# ═══ Default behaviour is unchanged ═════════════════════════════


def test_pm_get_default_is_byte_identical_without_and_with_fields_none(seeded):
    from projectman.server import pm_get

    assert pm_get("US-TST-1-1") == pm_get("US-TST-1-1", fields=None)


@pytest.mark.parametrize("empty", ["", "   ", ",", " , , "])
def test_pm_get_empty_fields_means_no_projection(seeded, empty):
    from projectman.server import pm_get

    assert pm_get("US-TST-1-1", fields=empty) == pm_get("US-TST-1-1")


def test_pm_get_multi_id_default_is_byte_identical(seeded):
    from projectman.server import pm_get

    ids = "US-TST-1-1,US-TST-1-2,US-TST-1"
    assert pm_get(ids) == pm_get(ids, fields=None)


def test_pm_get_default_with_include_log_is_byte_identical(seeded):
    from projectman.server import pm_get, pm_update

    pm_update("US-TST-1-1", outcome="partial", note="halfway there")
    with_log = pm_get("US-TST-1-1", include_log=True)
    assert "recent_run_log" in with_log
    assert with_log == pm_get("US-TST-1-1", include_log=True, fields=None)


def test_pm_grab_default_is_byte_identical(seeded, tmp_project):
    from projectman.server import pm_grab

    first = pm_grab("US-TST-1-1")
    again = pm_grab("US-TST-1-1", fields=None)
    assert first == again
    assert "story_context" in first


# ═══ pm_get projection ══════════════════════════════════════════


def test_pm_get_status_and_assignee_returns_exactly_those_plus_id(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("US-TST-1-1", fields="status,assignee"))
    assert set(data) == {"id", "status", "assignee"}
    assert data["id"] == "US-TST-1-1"
    assert data["status"] == "todo"


def test_pm_get_projection_keeps_id_even_when_unnamed(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("US-TST-1-1", fields="status"))
    assert set(data) == {"id", "status"}


def test_pm_get_projection_strips_whitespace_and_tolerates_duplicates(seeded):
    from projectman.server import pm_get

    spaced = pm_get("US-TST-1-1", fields="  status , assignee , status ")
    assert spaced == pm_get("US-TST-1-1", fields="status,assignee")


def test_pm_get_multi_id_projects_every_item_and_stays_addressable(seeded):
    from projectman.server import pm_get

    items = yaml.safe_load(
        pm_get("US-TST-1-1,US-TST-1-2,US-TST-1-3", fields="status")
    )
    assert [i["id"] for i in items] == ["US-TST-1-1", "US-TST-1-2", "US-TST-1-3"]
    assert all(set(i) == {"id", "status"} for i in items)


def test_pm_get_projects_a_story_by_its_own_keys(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("US-TST-2", fields="status,acceptance_criteria"))
    assert set(data) == {"id", "status", "acceptance_criteria"}
    assert data["acceptance_criteria"] == ["It works", "It is fast"]


def test_pm_get_projects_an_epic_by_its_own_keys(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("EPIC-TST-1", fields="status,title"))
    assert set(data) == {"id", "status", "title"}
    assert data["title"] == "An Epic"


def test_pm_get_projects_a_task_by_its_own_keys(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("US-TST-1-1", fields="story_id,points,body"))
    assert set(data) == {"id", "story_id", "points", "body"}
    assert data["story_id"] == "US-TST-1"


def test_pm_get_mixed_types_project_their_own_keys_in_one_call(seeded):
    from projectman.server import pm_get

    items = yaml.safe_load(pm_get("EPIC-TST-1,US-TST-1,US-TST-1-1", fields="status"))
    assert [set(i) for i in items] == [{"id", "status"}] * 3


# ═══ include_log interaction ════════════════════════════════════


def test_include_log_without_the_log_field_does_not_fetch_the_log(seeded, monkeypatch):
    """Don't pay for the run log and then project it away."""
    from projectman.server import pm_get, pm_update
    from projectman.store import Store

    pm_update("US-TST-1-1", outcome="partial", note="halfway there")

    calls = []
    real = Store.get_run_log

    def spy(self, *a, **kw):
        calls.append(a[0] if a else kw.get("item_id"))
        return real(self, *a, **kw)

    monkeypatch.setattr(Store, "get_run_log", spy)

    data = yaml.safe_load(pm_get("US-TST-1-1", include_log=True, fields="status"))
    assert set(data) == {"id", "status"}
    assert calls == [], f"run log was fetched and then discarded: {calls}"

    # …but naming it still fetches it.
    named = yaml.safe_load(
        pm_get("US-TST-1-1", include_log=True, fields="status,recent_run_log")
    )
    assert calls, "naming recent_run_log must still fetch it"
    assert set(named) == {"id", "status", "recent_run_log"}
    assert named["recent_run_log"][0]["note"] == "halfway there"


def test_recent_run_log_is_a_valid_name_even_without_include_log(seeded):
    from projectman.server import pm_get

    data = yaml.safe_load(pm_get("US-TST-1-1", fields="status,recent_run_log"))
    assert set(data) == {"id", "status"}


# ═══ pm_grab projection ═════════════════════════════════════════


def test_pm_grab_status_only_returns_just_the_task_keys(seeded):
    from projectman.server import pm_grab

    data = yaml.safe_load(pm_grab("US-TST-1-1", fields="status,assignee"))
    assert set(data) == {"grabbed"}
    assert set(data["grabbed"]) == {"task"}
    assert set(data["grabbed"]["task"]) == {"id", "status", "assignee"}
    assert data["grabbed"]["task"]["status"] == "in-progress"
    assert data["grabbed"]["task"]["assignee"] == "claude"


def test_pm_grab_still_claims_the_task_on_disk_when_projected(seeded, tmp_project):
    from projectman.server import pm_grab

    pm_grab("US-TST-1-1", assignee="bob", fields="status")
    meta = _on_disk(tmp_project, "US-TST-1-1")
    assert meta.assignee == "bob"
    assert meta.status.value == "in-progress"


def test_pm_grab_named_sections_come_back_whole(seeded):
    from projectman.server import pm_grab

    data = yaml.safe_load(
        pm_grab("US-TST-1-1", fields="status,story_context,sibling_tasks")
    )
    grabbed = data["grabbed"]
    assert set(grabbed) == {"task", "story_context", "sibling_tasks"}
    assert grabbed["story_context"]["body"] == "Story body text long enough to matter."
    assert [s["id"] for s in grabbed["sibling_tasks"]] == ["US-TST-1-2", "US-TST-1-3"]
    assert set(grabbed["task"]) == {"id", "status"}


def test_pm_grab_unnamed_sections_are_omitted(seeded):
    from projectman.server import pm_grab

    grabbed = yaml.safe_load(pm_grab("US-TST-1-1", fields="body"))["grabbed"]
    assert set(grabbed) == {"task", "body"}
    assert grabbed["body"].strip() == READY_BODY.strip()
    for absent in ("story_context", "sibling_tasks", "dependency_status"):
        assert absent not in grabbed


def test_pm_grab_task_section_by_name_comes_back_whole(seeded):
    from projectman.server import pm_grab

    full = yaml.safe_load(pm_grab("US-TST-1-1"))["grabbed"]["task"]
    named = yaml.safe_load(pm_grab("US-TST-1-1", fields="task"))["grabbed"]["task"]
    assert named == full


@pytest.fixture
def readiness_always_passes(monkeypatch):
    """Let a second worker reach the compare-and-swap, so it can lose it."""
    from projectman import readiness

    monkeypatch.setattr(
        readiness,
        "check_readiness",
        lambda *a, **k: {"ready": True, "blockers": [], "warnings": []},
    )


def test_pm_grab_expected_negatives_are_returned_unprojected(
    seeded, readiness_always_passes
):
    from projectman.server import pm_grab

    pm_grab("US-TST-1-1", assignee="worker-1")
    data = yaml.safe_load(pm_grab("US-TST-1-1", assignee="worker-2", fields="status"))
    assert data["outcome"] == "expected_negative"
    assert data["status"] == "already_claimed"
    assert data["holder"] == "worker-1"
    assert data["task_id"] == "US-TST-1-1"
    assert data["message"] == "task is already claimed"


def test_pm_grab_not_ready_negative_is_returned_unprojected(seeded, tmp_project):
    from projectman.server import pm_grab
    from projectman.store import Store

    store = Store(tmp_project)
    store.create_task("US-TST-1", "Unready", "no sections here")
    data = yaml.safe_load(pm_grab("US-TST-1-4", fields="status"))
    assert data["status"] == "not_ready"
    assert data["blockers"], "blockers are the recovery path and must survive"


# ═══ Unknown names fail loudly ══════════════════════════════════


def test_pm_get_unknown_field_raises_and_lists_the_valid_names(seeded):
    from projectman.server import pm_get

    with pytest.raises(ToolError) as exc:
        pm_get("US-TST-1-1", fields="status,stauts")
    message = str(exc.value)
    assert "stauts" in message
    assert "status" in message and "assignee" in message


def test_pm_get_unknown_field_names_the_item_type(seeded):
    from projectman.server import pm_get

    with pytest.raises(ToolError) as exc:
        pm_get("US-TST-2", fields="assignee")
    # assignee is a task-only field; the story's valid names are listed instead
    assert "acceptance_criteria" in str(exc.value)


def test_pm_get_unknown_field_is_not_buried_in_a_multi_id_item_error(seeded):
    from projectman.server import pm_get

    with pytest.raises(ToolError):
        pm_get("US-TST-1-1,US-TST-1-2", fields="nope")


def test_pm_grab_unknown_field_raises_and_lists_sections_and_task_keys(seeded):
    from projectman.server import pm_grab

    with pytest.raises(ToolError) as exc:
        pm_grab("US-TST-1-1", fields="siblings")
    message = str(exc.value)
    assert "siblings" in message
    assert "sibling_tasks" in message and "story_context" in message
    assert "status" in message


def test_warnings_is_a_valid_grab_field_even_when_absent(seeded):
    from projectman.server import pm_grab

    grabbed = yaml.safe_load(pm_grab("US-TST-1-1", fields="status,warnings"))["grabbed"]
    assert set(grabbed) == {"task"}


# ═══ Over the wire ══════════════════════════════════════════════


def test_pm_get_projection_over_the_wire(seeded):
    is_error, body = _call_over_the_wire(
        "pm_get", {"id": "US-TST-1-1", "fields": "status,assignee"}
    )
    assert not is_error, body
    assert set(yaml.safe_load(body)) == {"id", "status", "assignee"}


def test_pm_grab_projection_over_the_wire(seeded, tmp_project):
    is_error, body = _call_over_the_wire(
        "pm_grab", {"task_id": "US-TST-1-1", "fields": "status,assignee"}
    )
    assert not is_error, body
    assert set(yaml.safe_load(body)["grabbed"]["task"]) == {"id", "status", "assignee"}
    assert _on_disk(tmp_project, "US-TST-1-1").status.value == "in-progress"


def test_unknown_field_is_a_hard_error_over_the_wire(seeded):
    is_error, body = _call_over_the_wire(
        "pm_get", {"id": "US-TST-1-1", "fields": "nope"}
    )
    assert is_error, body
    assert "nope" in body


def test_fields_is_optional_in_both_published_schemas():
    from projectman.server import mcp as mcp_server

    tools = {t.name: t for t in anyio.run(mcp_server.list_tools)}
    for name in ("pm_get", "pm_grab"):
        schema = tools[name].inputSchema
        assert "fields" in schema["properties"], name
        assert "fields" not in schema.get("required", []), name
        # …and it is published as a *string* over the wire, not a list or an
        # enum: a client that only reads the schema must know to send
        # "status,assignee".
        published = schema["properties"]["fields"]
        types_ = {t.get("type") for t in published.get("anyOf", [published])}
        assert types_ == {"string", "null"}, (name, published)
        assert published.get("default") is None, (name, published)


# ═══ The point of the exercise: size ════════════════════════════


@pytest.fixture
def realistic(tmp_project):
    """A task shaped like the ones the orchestrator actually verifies."""
    from projectman.store import Store

    store = Store(tmp_project)
    store.create_story(
        "A realistic story",
        "As an orchestrator verifying a worker's claim, I want to fetch one "
        "field cheaply, so that distrusting the worker does not cost thousands "
        "of tokens.\n\n" + ("Background paragraph with real detail. " * 40),
    )
    store.update("US-TST-1", status="active")
    body = (
        "## Implementation\n\n"
        + ("Implement the projection carefully and completely. " * 30)
        + "\n\n## Testing\n\n"
        + ("Cover the default, the projection and the size claim. " * 20)
        + "\n\n## Definition of Done\n\n- [ ] Done\n"
    )
    for i in range(1, 8):
        store.create_task("US-TST-1", f"Realistic task {i}", body, points=3)
    # Criteria last: they auto-create verification tasks, and adding them
    # first would renumber the seven above.
    store.update(
        "US-TST-1",
        acceptance_criteria=[
            "pm_get and pm_grab accept a fields parameter selecting returned keys",
            "A status-only verification fetch costs a small fraction of the payload",
            "Default behaviour is unchanged when no projection is requested",
        ],
    )
    return store


def test_a_status_only_pm_get_is_a_small_fraction_of_the_full_item(realistic):
    from projectman.server import pm_get

    full = len(pm_get("US-TST-1-1"))
    projected = len(pm_get("US-TST-1-1", fields="status,assignee"))
    ratio = projected / full
    assert ratio <= 0.10, (
        f"status-only pm_get is {projected} of {full} chars = {ratio:.1%} "
        "of the full item; budget is 10%"
    )


def test_a_status_only_pm_grab_is_a_small_fraction_of_the_full_payload(realistic):
    from projectman.server import pm_grab

    full = len(pm_grab("US-TST-1-1"))
    projected = len(pm_grab("US-TST-1-1", fields="status,assignee"))
    ratio = projected / full
    assert ratio <= 0.10, (
        f"status-only pm_grab is {projected} of {full} chars = {ratio:.1%} "
        "of the full payload; budget is 10%"
    )


# ═══ Clauses the criterion names explicitly (US-PM-10-1) ════════


def test_pm_get_id_alone_returns_just_the_id(seeded):
    """`id` is a nameable key, not only an implicit survivor."""
    from projectman.server import pm_get

    assert yaml.safe_load(pm_get("US-TST-1-1", fields="id")) == {"id": "US-TST-1-1"}


def test_pm_get_mixed_types_project_two_keys_each_with_no_leakage(seeded):
    """An epic, a story and a task in one call, each projected to its own."""
    from projectman.server import pm_get

    items = yaml.safe_load(
        pm_get("EPIC-TST-1,US-TST-1,US-TST-1-1", fields="status,title")
    )
    assert [set(i) for i in items] == [{"id", "status", "title"}] * 3
    assert [i["id"] for i in items] == ["EPIC-TST-1", "US-TST-1", "US-TST-1-1"]
    assert [i["title"] for i in items] == ["An Epic", "Story", "Task 1"]


def test_pm_get_recent_run_log_alone_returns_the_id_and_the_entries(seeded):
    """The log can be the *whole* projection, and it carries real entries."""
    from projectman.server import pm_get, pm_update

    pm_update("US-TST-1-1", outcome="partial", note="halfway there")
    data = yaml.safe_load(
        pm_get("US-TST-1-1", include_log=True, fields="recent_run_log")
    )
    assert set(data) == {"id", "recent_run_log"}
    assert [e["note"] for e in data["recent_run_log"]] == ["halfway there"]


def test_pm_grab_projection_strips_whitespace_and_tolerates_duplicates(seeded):
    """Same tolerance as pm_get — a re-grab by the same assignee is idempotent."""
    from projectman.server import pm_grab

    spaced = pm_grab("US-TST-1-1", fields=" status , assignee ,status")
    assert spaced == pm_grab("US-TST-1-1", fields="status,assignee")


def test_grab_sections_and_task_keys_are_disjoint(seeded):
    """No name can mean both "a section" and "a task key".

    `_project_grabbed` resolves a name as a section first, so a collision
    would make that key unreachable *as a task key* — silently returning the
    section instead.  The two namespaces must therefore never overlap.
    """
    from projectman.server import GRAB_SECTIONS, pm_grab

    task = yaml.safe_load(pm_grab("US-TST-1-1"))["grabbed"]["task"]
    collisions = set(GRAB_SECTIONS) & set(task)
    assert not collisions, f"ambiguous grab field name(s): {sorted(collisions)}"


def test_pm_get_unknown_field_error_names_the_type_and_lists_every_valid_key(seeded):
    """Pin the message, not just the exception type.

    The valid names are listed in the *item's own key order* — the order the
    full response uses — not alphabetically.
    """
    from projectman.server import pm_get

    full = yaml.safe_load(pm_get("US-TST-1-1"))
    with pytest.raises(ToolError) as exc:
        pm_get("US-TST-1-1", fields="stauts")
    message = str(exc.value)
    assert message.startswith("unknown field name(s) for task: stauts")
    listed = message.split("valid names:")[1].strip().split(", ")
    assert listed == list(full) + ["recent_run_log"]


def test_pm_grab_unknown_field_error_names_the_tool_and_lists_every_valid_key(seeded):
    from projectman.server import GRAB_SECTIONS, pm_grab

    task = yaml.safe_load(pm_grab("US-TST-1-1"))["grabbed"]["task"]
    with pytest.raises(ToolError) as exc:
        pm_grab("US-TST-1-1", fields="siblings")
    message = str(exc.value)
    assert message.startswith("unknown field name(s) for pm_grab: siblings")
    listed = message.split("valid names:")[1].strip().split(", ")
    assert listed == list(GRAB_SECTIONS) + list(task)


# ── cost of the verification read (US-PM-10-2) ──────────────────
#
# The size tests above (``test_a_status_only_pm_get_is_a_small_fraction_of_
# the_full_item`` / ``…_pm_grab_…``) measure a *synthetic* fixture: 1.49% and
# 1.40% against a 10% budget.  A synthetic fixture can only prove that the
# projection code drops keys — it cannot prove the saving survives the shape
# of real data, where bodies are shorter and the frontmatter overhead is a
# bigger share of the payload.  So these run the orchestrator's exact
# verification read against a *copy of this repository's own* ``.project/``
# tree, on the tasks that cost the most: the longest-bodied done task, and a
# task with the most siblings (siblings are a whole section of a grab
# payload).  The live tree is never opened for writing — it is copied first.


@pytest.fixture
def live_project(tmp_path, monkeypatch, chdir_to_project):
    """A throwaway copy of this repo's real ``.project/``, bound to the Store.

    ``chdir_to_project`` is requested only for ordering: the autouse fixture
    chdirs to the synthetic project, and this must chdir *after* it.
    """
    import shutil
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / ".project"
    if not source.is_dir():
        pytest.skip("no live .project/ tree here (packaged install)")

    root = tmp_path / "live"
    root.mkdir()
    shutil.copytree(source, root / ".project")
    monkeypatch.chdir(root)

    from projectman.server import _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()

    store = Store(root)
    tasks = store.list_tasks()
    assert tasks, "the copied project has no tasks — fixture is not representative"

    def body_len(task):
        return len(store.get_task(task.id)[1])

    class Live:
        pass

    live = Live()
    live.root = root
    live.store = store
    # The read the orchestrator actually makes: pm_get on a task a worker has
    # just reported done.  Pick the most expensive one there is.
    live.longest_done = max(
        (t for t in tasks if t.status.value == "done"), key=body_len
    ).id
    # The most expensive grab: the longest-bodied task in the story with the
    # most siblings.
    from collections import Counter

    busiest_story = Counter(t.story_id for t in tasks).most_common(1)[0][0]
    live.crowded = max(
        (t for t in tasks if t.story_id == busiest_story), key=body_len
    ).id
    live.sibling_count = sum(1 for t in tasks if t.story_id == busiest_story)

    def make_grabbable(task_id):
        """Clear the readiness gates without touching the body — the payload."""
        meta, _ = store.get_task(task_id)
        store.update(meta.story_id, status="active")
        for dep in meta.depends_on or []:
            try:
                store.update(dep, status="done")
            except Exception:  # a dependency that no longer exists
                pass
        store.update(task_id, status="todo", clear="assignee")
        clear_all_caches()
        _store_cache.clear()

    live.make_grabbable = make_grabbable
    return live


def test_real_status_only_pm_get_is_a_small_fraction_of_the_full_item(live_project):
    """The orchestrator's step-16 verification read, on this repo's own data."""
    from projectman.server import pm_get

    task_id = live_project.longest_done
    full = len(pm_get(task_id))
    projected = len(pm_get(task_id, fields="status,assignee"))
    ratio = projected / full

    # If the real payload is trivially small the ratio proves nothing — the
    # study measured ~3,870 chars per verification read, so demand the same
    # order of magnitude before believing the saving.
    assert full >= 1000, (
        f"full pm_get({task_id}) is only {full} chars — not representative of "
        "the ~3,870-char reads the study measured; the ratio below is "
        "meaningless on a fixture this small"
    )
    assert ratio <= 0.10, (
        f"status-only pm_get({task_id}) is {projected} of {full} chars = "
        f"{ratio:.2%} of the full item; budget is 10%"
    )


def test_real_status_only_pm_grab_is_a_small_fraction_of_the_full_payload(
    live_project,
):
    """Same read as a re-claim, on the task with the most siblings."""
    from projectman.server import pm_grab

    task_id = live_project.crowded
    live_project.make_grabbable(task_id)

    full = pm_grab(task_id)
    assert "grabbed:" in full, f"fixture did not actually claim {task_id}: {full[:200]}"
    projected = pm_grab(task_id, fields="status,assignee")
    ratio = len(projected) / len(full)

    assert len(full) >= 1000, (
        f"full pm_grab({task_id}) is only {len(full)} chars across "
        f"{live_project.sibling_count} siblings — not representative"
    )
    assert ratio <= 0.10, (
        f"status-only pm_grab({task_id}) is {len(projected)} of {len(full)} "
        f"chars = {ratio:.2%} of the full payload; budget is 10%"
    )


def test_the_real_verification_read_is_three_keys_and_nearly_free(live_project):
    """What comes back is exactly the three bytes the skill reads, and no more."""
    from projectman.server import pm_get

    task_id = live_project.longest_done
    projected = pm_get(task_id, fields="status,assignee")

    assert set(yaml.safe_load(projected)) == {"id", "status", "assignee"}, (
        f"projected verification read of {task_id} carried keys the "
        f"orchestrator never reads: {projected!r}"
    )
    assert len(projected) <= 100, (
        f"verification read of {task_id} (a {len(task_id)}-char id) is "
        f"{len(projected)} chars — meant to be ~40 tokens, nearly free"
    )


def test_projection_does_not_cost_a_second_store_read(seeded, monkeypatch):
    """Projection is output-only: it drops keys, it never re-reads to get them.

    (The run-log half of this — ``include_log=True`` plus a projection that
    does not name the log — is pinned by
    ``test_include_log_without_the_log_field_does_not_fetch_the_log``.)
    """
    from projectman.server import pm_get
    from projectman.store import Store

    calls = []
    real = Store.get_task

    def spy(self, task_id, *a, **kw):
        calls.append(task_id)
        return real(self, task_id, *a, **kw)

    monkeypatch.setattr(Store, "get_task", spy)

    calls.clear()
    pm_get("US-TST-1-1")
    unprojected = len(calls)

    calls.clear()
    pm_get("US-TST-1-1", fields="status,assignee")
    projected = len(calls)

    assert projected <= unprojected, (
        f"projected pm_get made {projected} Store.get_task calls vs "
        f"{unprojected} unprojected — projection is buying the saving back"
    )


def test_projection_beats_the_old_include_story_false_mitigation(live_project):
    """`include_story=False` was the only lever before this; it is not close."""
    from projectman.server import pm_grab

    task_id = live_project.crowded
    live_project.make_grabbable(task_id)

    mitigated = len(pm_grab(task_id, include_story=False))
    projected = len(pm_grab(task_id, fields="status,assignee"))

    assert mitigated >= 3 * projected, (
        f"pm_grab({task_id}, include_story=False) is {mitigated} chars vs "
        f"{projected} projected — expected projection to be several times "
        "cheaper than the old mitigation"
    )
