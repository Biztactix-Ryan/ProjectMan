"""The decision MCP tools: pm_create_decision, pm_list_decisions, and
decisions in pm_update (US-PM-63-9).

Story US-PM-63, criteria 2, 4 and 5:

* pm_create_decision writes .project/decisions/DEC-PREFIX-N.md with the next
  free number and logs a create event;
* pm_list_decisions filters by status and by blocked item and returns each
  decision's blocked points;
* pm_update can edit a decision's fields and rejects an answered decision
  with no answer text.

Every test calls the server functions against a tmp_path-isolated store;
nothing here touches the real ``.project``.
"""

import json

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError


@pytest.fixture
def server_store(tmp_project, monkeypatch):
    """A Store on tmp_project that the server's ``_store()`` also resolves to."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.setenv("PROJECTMAN_ACTOR", "test-actor")
    from projectman.server import _store_cache
    from projectman.store import Store, clear_all_caches

    clear_all_caches()
    _store_cache.clear()
    from projectman.server import _store

    # Guard: the server must resolve to the tmp store, never the real one.
    assert _store().project_dir == tmp_project / ".project"
    yield Store(tmp_project)
    clear_all_caches()
    _store_cache.clear()


def _create(**kwargs):
    from projectman.server import pm_create_decision

    return yaml.safe_load(pm_create_decision(**kwargs))["created"]


def _list(**kwargs):
    from projectman.server import pm_list_decisions

    return yaml.safe_load(pm_list_decisions(**kwargs))


def _update(id, **kwargs):
    from projectman.server import pm_update

    return yaml.safe_load(pm_update(id, **kwargs))["updated"]


def call_over_the_wire(name, arguments):
    """One real tools/call through the low-level handler; (isError, text)."""
    import anyio
    import mcp.types as types
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


def _events(store, item_id):
    path = store.project_dir / "activity.jsonl"
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text().splitlines() if line]
    return [e for e in entries if e["item_id"] == item_id]


def _story_with_tasks(store, title, points_and_statuses, epic_id=None):
    """A story whose tasks carry the given (points, status) pairs."""
    story, _ = store.create_story(title, "A description long enough to pass")
    if epic_id:
        store.update(story.id, epic_id=epic_id)
    ids = []
    for i, (points, status) in enumerate(points_and_statuses, 1):
        task = store.create_task(story.id, f"{title} task {i}", "Body", points=points)
        if status != "todo":
            store.update(task.id, status=status)
        ids.append(task.id)
    return story.id, ids


# ─── pm_create_decision (AC 2) ───────────────────────────────────


class TestCreate:
    def test_create_returns_id_and_writes_the_file(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        created = _create(
            title="Which queue backend?",
            context="Redis is already deployed.",
            options=[{"label": "redis", "pros": ["deployed"]}, "sqs"],
            recommendation="redis",
            blocks="US-TST-1",
            priority="must",
            raised_from="US-TST-1",
            raised_by="claude",
        )
        assert created["id"] == "DEC-TST-1"
        assert created["status"] == "open"
        assert created["priority"] == "must"
        assert created["blocks"] == ["US-TST-1"]
        assert created["option_labels"] == ["redis", "sqs"]

        path = server_store.project_dir / "decisions" / "DEC-TST-1.md"
        assert path.exists()
        meta, body = server_store.get_decision("DEC-TST-1")
        assert body.strip() == "Redis is already deployed."
        assert meta.recommendation == "redis"
        assert meta.raised_from == "US-TST-1"
        assert meta.raised_by == "claude"
        assert meta.options[0].pros == ["deployed"]
        assert meta.options[1].label == "sqs"

    def test_create_logs_a_create_event(self, server_store):
        _create(title="Q?")
        events = _events(server_store, "DEC-TST-1")
        assert [e["event_type"] for e in events] == ["create"]
        assert events[0]["item_type"] == "decision"

    def test_second_create_takes_the_next_number(self, server_store):
        assert _create(title="First?")["id"] == "DEC-TST-1"
        assert _create(title="Second?")["id"] == "DEC-TST-2"
        assert (server_store.decisions_dir / "DEC-TST-2.md").exists()

    def test_next_free_number_after_existing_files_and_a_gap(self, server_store):
        """End to end: existing DEC files on disk (with a gap) set the floor,
        the tool writes DEC-PREFIX-N.md whose frontmatter round-trips, and
        exactly one create event lands in the activity log for it."""
        import frontmatter

        decisions = server_store.decisions_dir
        decisions.mkdir(parents=True)
        (decisions / "DEC-TST-1.md").write_text("---\nid: DEC-TST-1\n---\n")
        (decisions / "DEC-TST-5.md").write_text("---\nid: DEC-TST-5\n---\n")

        created = _create(
            title="After the gap?",
            context="Context body.",
            options=["a", "b"],
            recommendation="a",
            priority="could",
        )
        assert created["id"] == "DEC-TST-6"

        path = server_store.project_dir / "decisions" / "DEC-TST-6.md"
        assert path.is_file()
        assert sorted(p.name for p in decisions.glob("*.md")) == [
            "DEC-TST-1.md",
            "DEC-TST-5.md",
            "DEC-TST-6.md",
        ]

        post = frontmatter.load(str(path))
        assert post.metadata["id"] == "DEC-TST-6"
        assert post.metadata["title"] == "After the gap?"
        assert post.metadata["status"] == "open"
        assert post.metadata["priority"] == "could"
        assert post.metadata["recommendation"] == "a"
        assert [o["label"] for o in post.metadata["options"]] == ["a", "b"]
        assert post.content == "Context body."
        meta, body = server_store.get_decision("DEC-TST-6")
        assert meta.model_dump(mode="json") == post.metadata
        assert body == post.content

        events = _events(server_store, "DEC-TST-6")
        assert [(e["event_type"], e["item_type"]) for e in events] == [
            ("create", "decision")
        ]
        assert events[0]["actor"] == "test-actor"
        # The pre-existing files were not re-logged.
        assert _events(server_store, "DEC-TST-1") == []
        assert _events(server_store, "DEC-TST-5") == []

        assert _create(title="Next?")["id"] == "DEC-TST-7"

    def test_blocks_accepts_a_list(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        server_store.create_story("B story", "A description long enough to pass")
        created = _create(title="Q?", blocks=["US-TST-1", "US-TST-2"])
        assert created["blocks"] == ["US-TST-1", "US-TST-2"]

    def test_unknown_blocks_id_is_refused_and_nothing_written(self, server_store):
        with pytest.raises(ToolError, match=r"not found: US-TST-9.*\[code: invalid\]"):
            _create(title="Q?", blocks="US-TST-9")
        assert not list(server_store.decisions_dir.glob("*.md"))
        # The refusal burnt no number.
        assert _create(title="Q?")["id"] == "DEC-TST-1"

    def test_bad_priority_is_invalid(self, server_store):
        with pytest.raises(ToolError, match=r"\[code: invalid\]"):
            _create(title="Q?", priority="urgent")


# ─── pm_list_decisions (AC 4) ────────────────────────────────────


class TestList:
    def test_empty_project_lists_nothing(self, server_store):
        data = _list()
        assert data["decisions"] == []
        assert (data["count"], data["total"], data["has_more"]) == (0, 0, False)

    def test_status_filter(self, server_store):
        _create(title="Open one?")
        _create(title="Answered one?")
        _create(title="Withdrawn one?")
        server_store.update_decision("DEC-TST-2", status="answered", answer="yes")
        server_store.update_decision("DEC-TST-3", status="withdrawn")

        assert [d["id"] for d in _list(status="open")["decisions"]] == ["DEC-TST-1"]
        assert [d["id"] for d in _list(status="answered")["decisions"]] == [
            "DEC-TST-2"
        ]
        assert _list()["total"] == 3

    def test_unknown_status_is_invalid(self, server_store):
        with pytest.raises(ToolError, match=r"Unknown decision status.*\[code: invalid\]"):
            _list(status="pending")

    def test_blocks_filter(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        server_store.create_story("B story", "A description long enough to pass")
        _create(title="Blocks A?", blocks="US-TST-1")
        _create(title="Blocks B?", blocks="US-TST-2")
        _create(title="Blocks both?", blocks="US-TST-1,US-TST-2")
        _create(title="Blocks nothing?")

        assert [d["id"] for d in _list(blocks="US-TST-1")["decisions"]] == [
            "DEC-TST-1",
            "DEC-TST-3",
        ]
        assert [d["id"] for d in _list(blocks=["US-TST-2"])["decisions"]] == [
            "DEC-TST-2",
            "DEC-TST-3",
        ]
        assert _list(blocks="US-TST-404")["decisions"] == []

    def test_blocks_filter_by_task_and_epic_ids_and_with_status(self, server_store):
        epic = server_store.create_epic("E", "Epic description").id
        story, tasks = _story_with_tasks(
            server_store, "S", [(3, "todo"), (5, "todo")], epic_id=epic
        )
        _create(title="Blocks the task?", blocks=tasks[0])  # DEC-TST-1
        _create(title="Blocks the epic?", blocks=epic)  # DEC-TST-2
        _create(title="Blocks the story?", blocks=story)  # DEC-TST-3
        _create(title="Also blocks the task?", blocks=tasks[0])  # DEC-TST-4
        server_store.update_decision("DEC-TST-4", status="answered", answer="yes")

        # Exact match: a task id does not pull in its story's or epic's blockers.
        assert [d["id"] for d in _list(blocks=tasks[0])["decisions"]] == [
            "DEC-TST-1",
            "DEC-TST-4",
        ]
        assert [d["id"] for d in _list(blocks=epic)["decisions"]] == ["DEC-TST-2"]
        assert _list(blocks=tasks[1])["decisions"] == []
        # Filters compose: status and blocks together.
        assert [
            d["id"] for d in _list(status="open", blocks=tasks[0])["decisions"]
        ] == ["DEC-TST-1"]
        assert [
            d["id"] for d in _list(status="answered", blocks=tasks[0])["decisions"]
        ] == ["DEC-TST-4"]
        # Each filtered entry still carries its blocked points.
        by_id = {d["id"]: d["blocked_points"] for d in _list()["decisions"]}
        assert by_id == {"DEC-TST-1": 3, "DEC-TST-2": 8, "DEC-TST-3": 8, "DEC-TST-4": 3}

    def test_malformed_blocks_filter_is_invalid(self, server_store):
        with pytest.raises(ToolError, match=r"malformed id.*\[code: invalid\]"):
            _list(blocks="not-an-id")

    def test_pagination_in_number_order(self, server_store):
        for i in range(12):
            _create(title=f"Q{i + 1}?")
        first = _list(limit=5)
        assert [d["id"] for d in first["decisions"]] == [
            f"DEC-TST-{n}" for n in range(1, 6)
        ]
        assert (first["count"], first["total"], first["has_more"]) == (5, 12, True)
        last = _list(limit=5, offset=10)
        # Numeric, not lexicographic: DEC-TST-10 sorts after DEC-TST-9.
        assert [d["id"] for d in last["decisions"]] == ["DEC-TST-11", "DEC-TST-12"]
        assert last["has_more"] is False
        assert last["offset"] == 10

    def test_listing_omits_the_body(self, server_store):
        _create(title="Q?", context="secret context")
        entry = _list()["decisions"][0]
        assert "secret context" not in yaml.safe_dump(entry)
        assert entry["title"] == "Q?"


class TestBlockedPoints:
    def test_task_blocked_directly(self, server_store):
        _, tasks = _story_with_tasks(server_store, "S", [(3, "todo"), (5, "todo")])
        _create(title="Q?", blocks=tasks[0])
        assert _list()["decisions"][0]["blocked_points"] == 3

    def test_story_blocks_all_its_open_tasks(self, server_store):
        story, _ = _story_with_tasks(
            server_store, "S", [(3, "todo"), (5, "in-progress"), (8, "done")]
        )
        _create(title="Q?", blocks=story)
        assert _list()["decisions"][0]["blocked_points"] == 8

    def test_epic_blocks_tasks_under_its_stories(self, server_store):
        epic = server_store.create_epic("E", "Epic description").id
        _story_with_tasks(server_store, "S1", [(2, "todo"), (3, "done")], epic_id=epic)
        _story_with_tasks(server_store, "S2", [(5, "review")], epic_id=epic)
        _story_with_tasks(server_store, "Outside", [(13, "todo")])
        _create(title="Q?", blocks=epic)
        assert _list()["decisions"][0]["blocked_points"] == 7

    def test_done_and_archived_tasks_are_ignored(self, server_store):
        story, tasks = _story_with_tasks(
            server_store, "S", [(3, "done"), (5, "todo"), (2, "todo")]
        )
        server_store.archive(tasks[1])
        _create(title="Q?", blocks=story)
        assert _list()["decisions"][0]["blocked_points"] == 2

    def test_a_task_reached_twice_counts_once(self, server_store):
        story, tasks = _story_with_tasks(server_store, "S", [(3, "todo"), (5, "todo")])
        _create(title="Q?", blocks=[story, tasks[0]])
        assert _list()["decisions"][0]["blocked_points"] == 8

    def test_epic_and_its_own_story_overlap_counts_once(self, server_store):
        epic = server_store.create_epic("E", "Epic description").id
        story, tasks = _story_with_tasks(
            server_store, "S", [(3, "todo"), (5, "todo")], epic_id=epic
        )
        _create(title="Q?", blocks=[epic, story, tasks[1]])
        assert _list()["decisions"][0]["blocked_points"] == 8

    def test_a_done_task_named_directly_scores_zero(self, server_store):
        _, tasks = _story_with_tasks(server_store, "S", [(5, "done")])
        _create(title="Q?", blocks=tasks[0])
        assert _list()["decisions"][0]["blocked_points"] == 0

    def test_unestimated_and_unblocking_decisions_score_zero(self, server_store):
        story, _ = _story_with_tasks(server_store, "S", [(None, "todo")])
        _create(title="Unestimated?", blocks=story)
        _create(title="Blocks nothing?")
        assert [d["blocked_points"] for d in _list()["decisions"]] == [0, 0]


# ─── pm_list_decisions(order="session") (US-PM-65-8) ─────────────
#
# Story US-PM-65 criterion: "The session orders open decisions by blocked
# points with active and next sprint work first and stops after the batch
# size".


def _sprint(store, name, stories, status):
    sprint = store.create_sprint(name=name, planned_stories=stories)
    if status != "planning":
        store.update_sprint(sprint.id, status=status)
    return sprint.id


def _set_created(store, decision_id, iso):
    """Back-date a decision in the tmp store; ``created`` is immutable via the API."""
    import frontmatter

    path = store.project_dir / "decisions" / f"{decision_id}.md"
    assert path.exists()  # server_store already pinned project_dir to tmp_path
    post = frontmatter.load(str(path))
    post.metadata["created"] = iso
    path.write_text(frontmatter.dumps(post))


def _session(**kwargs):
    return _list(order="session", **kwargs)


class TestSessionOrder:
    def test_active_sprint_then_planning_then_rest(self, server_store):
        active, _ = _story_with_tasks(server_store, "Active", [(1, "todo")])
        planned, _ = _story_with_tasks(server_store, "Planned", [(5, "todo")])
        rest, _ = _story_with_tasks(server_store, "Rest", [(13, "todo")])
        _sprint(server_store, "Now", [active], "active")
        _sprint(server_store, "Next", [planned], "planning")
        _sprint(server_store, "Old", [rest], "completed")
        _create(title="Rest?", blocks=rest)  # DEC-TST-1, most points
        _create(title="Planned?", blocks=planned)  # DEC-TST-2
        _create(title="Active?", blocks=active)  # DEC-TST-3, fewest points

        rows = _session()["decisions"]
        assert [d["id"] for d in rows] == ["DEC-TST-3", "DEC-TST-2", "DEC-TST-1"]
        assert [d["tier"] for d in rows] == ["active", "planning", "other"]
        assert [d["blocked_points"] for d in rows] == [1, 5, 13]

    def test_tier_reaches_through_tasks_and_epics(self, server_store):
        epic = server_store.create_epic("E", "Epic description").id
        in_epic, _ = _story_with_tasks(server_store, "S1", [(2, "todo")], epic_id=epic)
        other, tasks = _story_with_tasks(server_store, "S2", [(3, "todo"), (8, "done")])
        _sprint(server_store, "Now", [in_epic, other], "active")
        _create(title="Unplanned?")  # DEC-TST-1: blocks nothing
        _create(title="Done task?", blocks=tasks[1])  # DEC-TST-2: no open work
        _create(title="Epic?", blocks=epic)  # DEC-TST-3
        _create(title="Task?", blocks=tasks[0])  # DEC-TST-4

        rows = _session()["decisions"]
        assert [(d["id"], d["tier"]) for d in rows] == [
            ("DEC-TST-4", "active"),
            ("DEC-TST-3", "active"),
            ("DEC-TST-1", "other"),
            ("DEC-TST-2", "other"),
        ]

    def test_points_descending_within_a_tier(self, server_store):
        stories = []
        for title, points in (("Two", 2), ("Eight", 8), ("Five", 5)):
            story, _ = _story_with_tasks(server_store, title, [(points, "todo")])
            stories.append(story)
            _create(title=f"{title}?", blocks=story)
        _sprint(server_store, "Now", stories, "active")

        rows = _session()["decisions"]
        assert [d["blocked_points"] for d in rows] == [8, 5, 2]
        assert [d["id"] for d in rows] == ["DEC-TST-2", "DEC-TST-3", "DEC-TST-1"]

    def test_oldest_first_breaks_a_points_tie(self, server_store):
        story, _ = _story_with_tasks(server_store, "S", [(3, "todo")])
        for i in range(4):
            _create(title=f"Q{i + 1}?", blocks=story)
        _set_created(server_store, "DEC-TST-1", "2026-03-03")
        _set_created(server_store, "DEC-TST-2", "2026-01-01")
        _set_created(server_store, "DEC-TST-3", "2026-02-02")
        _set_created(server_store, "DEC-TST-4", "2026-02-02")

        assert [d["id"] for d in _session()["decisions"]] == [
            "DEC-TST-2",
            "DEC-TST-3",  # same day as DEC-TST-4: number order
            "DEC-TST-4",
            "DEC-TST-1",
        ]

    def test_stops_after_the_batch_size(self, server_store):
        for i in range(10):
            _create(title=f"Q{i + 1}?")

        batch = _session()
        assert (batch["count"], batch["total"], batch["has_more"]) == (7, 10, True)
        assert [d["id"] for d in batch["decisions"]] == [
            f"DEC-TST-{n}" for n in range(1, 8)
        ]
        assert _session(limit=3)["count"] == 3
        assert [d["id"] for d in _session(offset=7)["decisions"]] == [
            "DEC-TST-8",
            "DEC-TST-9",
            "DEC-TST-10",
        ]
        # The default listing keeps its own page size of 50.
        assert _list()["count"] == 10

    def test_answered_and_withdrawn_are_excluded(self, server_store):
        _create(title="Open?")
        _create(title="Answered?")
        _create(title="Withdrawn?")
        server_store.update_decision("DEC-TST-2", status="answered", answer="yes")
        server_store.update_decision("DEC-TST-3", status="withdrawn")

        data = _session()
        assert [d["id"] for d in data["decisions"]] == ["DEC-TST-1"]
        assert data["total"] == 1
        assert _session(status="open")["total"] == 1
        with pytest.raises(ToolError, match=r"open decisions only.*\[code: invalid\]"):
            _session(status="answered")

    def test_rows_carry_blocked_ids_and_titles(self, server_store):
        story, tasks = _story_with_tasks(server_store, "Login", [(3, "todo")])
        _create(title="Q?", blocks=[story, tasks[0]])

        row = _session()["decisions"][0]
        assert row["blocked"] == [
            {"id": story, "title": "Login"},
            {"id": tasks[0], "title": "Login task 1"},
        ]
        assert "blocked" not in _list()["decisions"][0]

    def test_unknown_order_is_invalid(self, server_store):
        with pytest.raises(ToolError, match=r"Unknown order.*\[code: invalid\]"):
            _list(order="points")


# ─── pm_update on a decision (AC 5) ──────────────────────────────


class TestUpdate:
    def test_edits_fields(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        _create(title="Q?", context="old context")
        updated = _update(
            "DEC-TST-1",
            title="Which queue?",
            body="new context",
            priority="must",
            blocks="US-TST-1",
            options=["redis", {"label": "sqs", "cons": ["vendor lock-in"]}],
            recommendation="redis",
            rationale="already deployed",
        )
        assert updated["id"] == "DEC-TST-1"
        assert updated["title"] == "Which queue?"
        assert updated["priority"] == "must"
        assert updated["blocks"] == ["US-TST-1"]
        assert updated["option_labels"] == ["redis", "sqs"]
        assert updated["body_chars"] == len("new context")

        meta, body = server_store.get_decision("DEC-TST-1")
        assert meta.title == "Which queue?"
        assert body.strip() == "new context"
        assert meta.options[1].cons == ["vendor lock-in"]
        assert meta.recommendation == "redis"
        assert meta.rationale == "already deployed"
        assert [e["event_type"] for e in _events(server_store, "DEC-TST-1")] == [
            "create",
            "update",
        ]

    def test_answering_stamps_who_and_when(self, server_store):
        _create(title="Q?")
        updated = _update("DEC-TST-1", status="answered", answer="redis")
        assert updated["status"] == "answered"
        assert updated["answer"] == "redis"
        assert updated["answered_by"] == "test-actor"
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.answered_at is not None

    def test_answered_without_answer_text_is_rejected(self, server_store):
        _create(title="Q?")
        before = (server_store.decisions_dir / "DEC-TST-1.md").read_text()
        with pytest.raises(
            ToolError, match=r"cannot be answered without answer text.*\[code: invalid\]"
        ):
            _update("DEC-TST-1", status="answered")
        with pytest.raises(ToolError, match=r"\[code: invalid\]"):
            _update("DEC-TST-1", status="answered", answer="   ")
        assert (server_store.decisions_dir / "DEC-TST-1.md").read_text() == before

    def test_every_editable_field_round_trips_from_disk(self, server_store):
        """Each editable field, written by pm_update, read back from the raw
        file and from a fresh Store (no in-process cache can answer)."""
        from projectman.store import Store, clear_all_caches

        server_store.create_story("A story", "A description long enough to pass")
        server_store.create_story("B story", "A description long enough to pass")
        _create(title="Q?", context="old", blocks="US-TST-1", priority="could")
        path = server_store.decisions_dir / "DEC-TST-1.md"

        def on_disk():
            clear_all_caches()
            raw = yaml.safe_load(path.read_text().split("---")[1])
            meta, body = Store(server_store.root).get_decision("DEC-TST-1")
            return raw, meta, body

        edits = [
            ({"title": "Which queue?"}, lambda r, m, b: m.title == r["title"] == "Which queue?"),
            ({"body": "new context"}, lambda r, m, b: b.strip() == "new context"),
            ({"priority": "must"}, lambda r, m, b: m.priority == r["priority"] == "must"),
            ({"blocks": "US-TST-1,US-TST-2"}, lambda r, m, b: m.blocks == r["blocks"] == ["US-TST-1", "US-TST-2"]),
            (
                {"options": [{"label": "redis", "summary": "s", "pros": ["p"], "cons": ["c"]}, "sqs"]},
                lambda r, m, b: [o["label"] for o in r["options"]] == ["redis", "sqs"]
                and (m.options[0].summary, m.options[0].pros, m.options[0].cons) == ("s", ["p"], ["c"]),
            ),
            ({"recommendation": "sqs"}, lambda r, m, b: m.recommendation == r["recommendation"] == "sqs"),
            ({"rationale": "cheaper"}, lambda r, m, b: m.rationale == r["rationale"] == "cheaper"),
            ({"answer": "redis"}, lambda r, m, b: m.answer == r["answer"] == "redis" and r["status"] == "open"),
            ({"status": "answered"}, lambda r, m, b: r["status"] == "answered" and m.answered_at is not None),
            ({"answer": "sqs after all"}, lambda r, m, b: m.answer == "sqs after all" and r["status"] == "answered"),
            ({"status": "withdrawn"}, lambda r, m, b: m.status.value == r["status"] == "withdrawn"),
            ({"status": "open"}, lambda r, m, b: r["status"] == "open"),
        ]
        for kwargs, check in edits:
            _update("DEC-TST-1", **kwargs)
            assert check(*on_disk()), kwargs

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"status": "answered"},
            {"status": "answered", "answer": ""},
            {"status": "answered", "answer": "  \t\n "},
        ],
        ids=["missing", "empty", "whitespace"],
    )
    def test_answered_without_text_is_a_genuine_error_on_the_wire(
        self, server_store, kwargs
    ):
        """The refusal reaches an MCP client as isError, nothing written."""
        _create(title="Q?")
        path = server_store.decisions_dir / "DEC-TST-1.md"
        before = path.read_bytes()
        log = server_store.project_dir / "activity.jsonl"
        log_before = log.read_bytes()

        with pytest.raises(ToolError, match=r"without answer text.*\[code: invalid\]"):
            _update("DEC-TST-1", **kwargs)
        is_error, text = call_over_the_wire("pm_update", {"id": "DEC-TST-1", **kwargs})
        assert is_error, text
        assert "without answer text" in text
        assert path.read_bytes() == before
        assert log.read_bytes() == log_before

    def test_answered_with_an_already_stored_empty_answer_is_rejected(
        self, server_store
    ):
        _create(title="Q?")
        _update("DEC-TST-1", answer="")  # an open decision may hold an empty answer
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.answer == ""
        path = server_store.decisions_dir / "DEC-TST-1.md"
        before = path.read_bytes()
        with pytest.raises(ToolError, match=r"without answer text.*\[code: invalid\]"):
            _update("DEC-TST-1", status="answered")
        assert path.read_bytes() == before

    def test_blanking_the_answer_of_an_answered_decision_is_rejected(
        self, server_store
    ):
        _create(title="Q?")
        _update("DEC-TST-1", status="answered", answer="redis")
        path = server_store.decisions_dir / "DEC-TST-1.md"
        before = path.read_bytes()
        for blank in ("", "   "):
            with pytest.raises(ToolError, match=r"without answer text.*\[code: invalid\]"):
                _update("DEC-TST-1", answer=blank)
        assert path.read_bytes() == before

    def test_unknown_blocks_id_is_rejected(self, server_store):
        _create(title="Q?")
        with pytest.raises(ToolError, match=r"not found: US-TST-9.*\[code: invalid\]"):
            _update("DEC-TST-1", blocks=["US-TST-9"])
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.blocks == []

    def test_empty_blocks_unblocks(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        _create(title="Q?", blocks="US-TST-1")
        assert _update("DEC-TST-1", blocks=[])["blocks"] == []

    def test_task_fields_are_refused_on_a_decision(self, server_store):
        _create(title="Q?")
        with pytest.raises(ToolError, match=r"points, tags cannot be set on decision"):
            _update("DEC-TST-1", points=3, tags="x")

    def test_decision_fields_are_refused_on_a_story(self, server_store):
        server_store.create_story("A story", "A description long enough to pass")
        with pytest.raises(ToolError, match=r"answer can only be set on a decision"):
            _update("US-TST-1", answer="yes")

    def test_missing_decision_is_not_found(self, server_store):
        with pytest.raises(ToolError, match=r"\[code: not_found\]"):
            _update("DEC-TST-404", title="x")

    def test_bad_status_is_invalid(self, server_store):
        _create(title="Q?")
        with pytest.raises(ToolError, match=r"\[code: invalid\]"):
            _update("DEC-TST-1", status="done")


# ─── pm_estimate on a decision (US-PM-63-8 follow-up) ────────────


def test_pm_estimate_refuses_decision_and_sprint_ids_as_invalid(server_store):
    from projectman.server import pm_estimate

    _create(title="Q?")
    server_store.create_sprint(name="S1")
    for item_id in ("DEC-TST-1", "SPRINT-TST-1"):
        with pytest.raises(ToolError, match=r"cannot be estimated.*\[code: invalid\]"):
            pm_estimate(item_id)


# ─── pm_answer_decision (US-PM-65-7) ─────────────────────────────
#
# Story US-PM-65, criteria 1 and 2:
#
# * pm_answer_decision records answer, rationale, answered_by and
#   answered_at, sets status answered and returns the items it unblocked;
# * pm_answer_decision with withdraw closes the decision as withdrawn with a
#   required reason.


def _answer(id, **kwargs):
    from projectman.server import pm_answer_decision

    return yaml.safe_load(pm_answer_decision(id, **kwargs))


def _snapshot(store, decision_id="DEC-TST-1"):
    """Bytes of the decision file and the activity log, for refusal checks."""
    log = store.project_dir / "activity.jsonl"
    return (
        (store.decisions_dir / f"{decision_id}.md").read_bytes(),
        log.read_bytes() if log.exists() else b"",
    )


class TestAnswer:
    def test_answer_records_every_field_and_unblocks(self, server_store):
        """AC 1: answer, rationale, answered_by, answered_at, status, unblocked."""
        from datetime import datetime, timedelta, timezone

        story, (t1, t2) = _story_with_tasks(server_store, "A", [(3, "todo"), (2, "todo")])
        _create(title="Which queue?", blocks=story, options=["redis", "sqs"])

        before = datetime.now(timezone.utc)
        out = _answer("DEC-TST-1", answer="redis", rationale="already deployed")
        answered = out["answered"]
        assert answered["id"] == "DEC-TST-1"
        assert answered["status"] == "answered"
        assert answered["answer"] == "redis"
        assert answered["rationale"] == "already deployed"
        assert answered["answered_by"] == "test-actor"
        assert answered["unblocked"] == [t1, t2]

        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.status.value == "answered"
        assert meta.answer == "redis"
        assert meta.rationale == "already deployed"
        assert meta.answered_by == "test-actor"
        assert before - timedelta(seconds=1) <= meta.answered_at
        assert meta.answered_at <= datetime.now(timezone.utc)

    def test_answer_logs_one_update_event(self, server_store):
        _create(title="Q?")
        _answer("DEC-TST-1", answer="yes", rationale="because")
        events = _events(server_store, "DEC-TST-1")
        assert [(e["event_type"], e["item_type"]) for e in events] == [
            ("create", "decision"),
            ("update", "decision"),
        ]
        changes = events[1]["changes"]
        assert changes["status"] == {"before": "open", "after": "answered"}
        assert changes["answer"]["after"] == "yes"
        assert changes["rationale"]["after"] == "because"
        assert events[1]["actor"] == "test-actor"

    def test_rationale_is_optional(self, server_store):
        _create(title="Q?")
        answered = _answer("DEC-TST-1", answer="yes")["answered"]
        assert "rationale" not in answered
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.status.value == "answered" and meta.rationale is None

    def test_unblocked_is_only_what_no_open_decision_still_holds(self, server_store):
        """A task another open decision still holds is not unblocked; done and
        archived tasks never are; the epic reach counts like the gate."""
        epic = server_store.create_epic("E", "An epic description long enough")
        story_a, (a1, a2, a_done) = _story_with_tasks(
            server_store, "A", [(1, "todo"), (2, "todo"), (3, "done")], epic_id=epic.id
        )
        story_b, (b1, b_arch) = _story_with_tasks(server_store, "B", [(1, "todo"), (1, "todo")])
        _story_c, (c1,) = _story_with_tasks(server_store, "C", [(1, "todo")])
        server_store.archive(b_arch)
        server_store.update(b1, status="review")  # a parked task is still unblocked

        # DEC-1 holds the epic (so story A's tasks) and story B.
        _create(title="Wide?", blocks=f"{epic.id},{story_b}")
        # DEC-2 still holds a2 directly.
        _create(title="Narrow?", blocks=a2)

        unblocked = _answer("DEC-TST-1", answer="go")["answered"]["unblocked"]
        assert unblocked == [a1, b1]
        assert a2 not in unblocked and a_done not in unblocked
        assert b_arch not in unblocked and c1 not in unblocked

        # Closing the second one lifts the last hold on a2.
        assert _answer("DEC-TST-2", withdraw=True, reason="moot")["withdrawn"][
            "unblocked"
        ] == [a2]

    def test_a_decision_blocking_nothing_unblocks_nothing(self, server_store):
        _create(title="Q?")
        assert _answer("DEC-TST-1", answer="x")["answered"]["unblocked"] == []

    def test_unblocked_tasks_become_grabbable(self, server_store):
        from projectman.readiness import check_readiness

        _story, (t1,) = _story_with_tasks(server_store, "A", [(2, "todo")])
        _create(title="Q?", blocks=t1)
        task, body = server_store.get_task(t1)
        held = check_readiness(task, body, server_store)
        assert any("DEC-TST-1" in b for b in held["blockers"])

        assert _answer("DEC-TST-1", answer="x")["answered"]["unblocked"] == [t1]
        task, body = server_store.get_task(t1)
        after = check_readiness(task, body, server_store)
        assert not any("DEC-TST-1" in b for b in after["blockers"])

    @pytest.mark.parametrize("answer", [None, "", "   "], ids=["missing", "empty", "blank"])
    def test_answer_text_is_required(self, server_store, answer):
        _create(title="Q?")
        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=r"without answer text.*\[code: invalid\]"):
            _answer("DEC-TST-1", answer=answer)
        assert _snapshot(server_store) == before

    def test_reason_without_withdraw_is_refused(self, server_store):
        _create(title="Q?")
        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=r"reason is only for withdraw.*\[code: invalid\]"):
            _answer("DEC-TST-1", answer="x", reason="why")
        assert _snapshot(server_store) == before

    def test_reanswering_is_a_conflict_unless_overwriting(self, server_store):
        _create(title="Q?")
        _answer("DEC-TST-1", answer="redis", rationale="first")
        first, _ = server_store.get_decision("DEC-TST-1")
        before = _snapshot(server_store)

        with pytest.raises(ToolError, match=r"already answered.*overwrite.*\[code: conflict\]"):
            _answer("DEC-TST-1", answer="sqs")
        assert _snapshot(server_store) == before
        is_error, text = call_over_the_wire(
            "pm_answer_decision", {"id": "DEC-TST-1", "answer": "sqs"}
        )
        assert is_error and "already answered" in text
        assert _snapshot(server_store) == before

        answered = _answer("DEC-TST-1", answer="sqs", rationale="second", overwrite=True)[
            "answered"
        ]
        assert answered["answer"] == "sqs"
        assert answered["rationale"] == "second"
        assert answered["overwrote"] == "answered"
        # A closed decision held nothing, so nothing new is unblocked.
        assert answered["unblocked"] == []
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert (meta.status.value, meta.answer, meta.rationale) == ("answered", "sqs", "second")
        assert meta.answered_at >= first.answered_at
        assert [e["event_type"] for e in _events(server_store, "DEC-TST-1")] == [
            "create",
            "update",
            "update",
        ]

    def test_missing_decision_is_not_found(self, server_store):
        with pytest.raises(ToolError, match=r"\[code: not_found\]"):
            _answer("DEC-TST-404", answer="x")

    @pytest.mark.parametrize("bad", ["US-TST-1", "DEC-1", "", "nope"])
    def test_a_non_decision_id_is_invalid(self, server_store, bad):
        server_store.create_story("A story", "A description long enough to pass")
        story_file = server_store.project_dir / "stories" / "US-TST-1.md"
        before = story_file.read_bytes()
        with pytest.raises(ToolError, match=r"\[code: invalid\]"):
            _answer(bad, answer="x")
        assert story_file.read_bytes() == before


class TestWithdraw:
    def test_withdraw_closes_with_the_reason(self, server_store):
        """AC 2: withdrawn, reason recorded, no answer, block lifted."""
        _story, (t1,) = _story_with_tasks(server_store, "A", [(2, "todo")])
        _create(title="Q?", blocks=t1)

        withdrawn = _answer("DEC-TST-1", withdraw=True, reason="no longer relevant")[
            "withdrawn"
        ]
        assert withdrawn["id"] == "DEC-TST-1"
        assert withdrawn["status"] == "withdrawn"
        assert withdrawn["rationale"] == "no longer relevant"
        assert withdrawn["unblocked"] == [t1]
        assert "answer" not in withdrawn

        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.status.value == "withdrawn"
        assert meta.rationale == "no longer relevant"
        assert meta.answer is None
        assert meta.answered_at is None

        events = _events(server_store, "DEC-TST-1")
        assert [e["event_type"] for e in events] == ["create", "update"]
        assert events[1]["changes"]["status"] == {"before": "open", "after": "withdrawn"}

    @pytest.mark.parametrize("reason", [None, "", "  \n"], ids=["missing", "empty", "blank"])
    def test_withdraw_requires_a_reason(self, server_store, reason):
        _create(title="Q?")
        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=r"needs a non-blank reason.*\[code: invalid\]"):
            _answer("DEC-TST-1", withdraw=True, reason=reason)
        args = {"id": "DEC-TST-1", "withdraw": True}
        if reason is not None:
            args["reason"] = reason
        is_error, text = call_over_the_wire("pm_answer_decision", args)
        assert is_error and "non-blank reason" in text
        assert _snapshot(server_store) == before
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.status.value == "open"

    @pytest.mark.parametrize(
        "extra, message",
        [({"answer": "x"}, "without an answer"), ({"rationale": "x"}, "not rationale")],
        ids=["answer", "rationale"],
    )
    def test_withdraw_refuses_answer_fields(self, server_store, extra, message):
        _create(title="Q?")
        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=rf"{message}.*\[code: invalid\]"):
            _answer("DEC-TST-1", withdraw=True, reason="moot", **extra)
        assert _snapshot(server_store) == before

    def test_closing_a_closed_decision_needs_overwrite(self, server_store):
        _create(title="Q?")
        _answer("DEC-TST-1", answer="redis")
        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=r"already answered.*\[code: conflict\]"):
            _answer("DEC-TST-1", withdraw=True, reason="changed course")
        assert _snapshot(server_store) == before

        withdrawn = _answer(
            "DEC-TST-1", withdraw=True, reason="changed course", overwrite=True
        )["withdrawn"]
        assert withdrawn["status"] == "withdrawn"
        assert withdrawn["overwrote"] == "answered"

        before = _snapshot(server_store)
        with pytest.raises(ToolError, match=r"already withdrawn.*\[code: conflict\]"):
            _answer("DEC-TST-1", withdraw=True, reason="again")
        with pytest.raises(ToolError, match=r"already withdrawn.*\[code: conflict\]"):
            _answer("DEC-TST-1", answer="redis")
        assert _snapshot(server_store) == before


# ─── Answers logged onto the tasks they unblock (US-PM-66-4) ─────
#
# Story US-PM-66 criterion: "Answering a decision adds a run-log entry to each
# unblocked task naming the decision id, the answer and the rationale".
#
# Choice pinned here: every open task the decision names gets the entry, even
# one another open decision still holds (suffixed "still held by"), but only
# the truly free ones are reported as `unblocked`.  Withdrawals log too, with
# the reason.  Done and archived tasks get nothing; refusals write nothing.


def _decision_notes(store, task_id):
    """Run-log entries on *task_id* written by a decision answer, oldest first."""
    entries = store.get_run_log(task_id, limit=100)
    return [e for e in reversed(entries) if e.note.startswith("Decision ")]


def _logs_snapshot(store):
    logs = store.project_dir / "logs"
    if not logs.exists():
        return {}
    return {p.name: p.read_bytes() for p in sorted(logs.iterdir())}


class TestAnswerRunLog:
    def test_each_unblocked_task_gets_an_entry_naming_id_answer_and_rationale(
        self, server_store
    ):
        """The US-PM-66 criterion, direct block."""
        _story, (t1, t2) = _story_with_tasks(server_store, "A", [(1, "todo"), (2, "todo")])
        _create(title="Which queue?", blocks=t1)

        out = _answer("DEC-TST-1", answer="redis", rationale="already deployed")
        assert out["answered"]["unblocked"] == [t1]

        (entry,) = _decision_notes(server_store, t1)
        assert "DEC-TST-1" in entry.note
        assert "redis" in entry.note
        assert "already deployed" in entry.note
        assert entry.note == "Decision DEC-TST-1 answered: redis; rationale: already deployed"
        assert entry.outcome.value == "info"
        assert entry.status == "todo"
        assert entry.actor == "test-actor"
        # A task the decision never named is left alone.
        assert _decision_notes(server_store, t2) == []

    def test_entry_is_read_back_by_pm_run_log(self, server_store):
        from projectman.server import pm_run_log

        _story, (t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=t1)
        _answer("DEC-TST-1", answer="sqs", rationale="cheaper")
        text = pm_run_log(t1)
        assert "Decision DEC-TST-1 answered: sqs; rationale: cheaper" in text

    def test_via_story_every_open_task_gets_it(self, server_store):
        story, (t1, t2, done) = _story_with_tasks(
            server_store, "A", [(1, "todo"), (2, "in-progress"), (3, "done")]
        )
        _create(title="Q?", blocks=story)
        assert _answer("DEC-TST-1", answer="go", rationale="why not")["answered"][
            "unblocked"
        ] == [t1, t2]
        for task_id, status in ((t1, "todo"), (t2, "in-progress")):
            (entry,) = _decision_notes(server_store, task_id)
            assert entry.note == "Decision DEC-TST-1 answered: go; rationale: why not"
            assert entry.status == status
        assert _decision_notes(server_store, done) == []

    def test_via_epic_every_open_task_under_it_gets_it(self, server_store):
        epic = server_store.create_epic("E", "An epic description long enough")
        _sa, (a1,) = _story_with_tasks(server_store, "A", [(1, "todo")], epic_id=epic.id)
        _sb, (b1, b_arch) = _story_with_tasks(
            server_store, "B", [(1, "review"), (1, "todo")], epic_id=epic.id
        )
        _sc, (c1,) = _story_with_tasks(server_store, "C", [(1, "todo")])
        server_store.archive(b_arch)
        _create(title="Q?", blocks=epic.id)

        assert _answer("DEC-TST-1", answer="go", rationale="r")["answered"][
            "unblocked"
        ] == [a1, b1]
        assert len(_decision_notes(server_store, a1)) == 1
        assert len(_decision_notes(server_store, b1)) == 1
        assert _decision_notes(server_store, b_arch) == []
        assert _decision_notes(server_store, c1) == []

    def test_done_and_archived_tasks_get_no_entry(self, server_store):
        _story, (done, archived) = _story_with_tasks(
            server_store, "A", [(1, "done"), (1, "todo")]
        )
        server_store.archive(archived)
        _create(title="Q?", blocks=f"{done},{archived}")
        before = _logs_snapshot(server_store)
        assert _answer("DEC-TST-1", answer="x", rationale="y")["answered"]["unblocked"] == []
        assert _logs_snapshot(server_store) == before

    def test_task_still_held_gets_the_entry_but_is_not_unblocked(self, server_store):
        story, (t1, t2) = _story_with_tasks(server_store, "A", [(1, "todo"), (1, "todo")])
        _create(title="Wide?", blocks=story)
        _create(title="Narrow?", blocks=t2)

        assert _answer("DEC-TST-1", answer="go", rationale="r")["answered"][
            "unblocked"
        ] == [t1]
        (free,) = _decision_notes(server_store, t1)
        assert free.note == "Decision DEC-TST-1 answered: go; rationale: r"
        (held,) = _decision_notes(server_store, t2)
        assert held.note == (
            "Decision DEC-TST-1 answered: go; rationale: r; still held by DEC-TST-2"
        )

    def test_missing_rationale_is_said_so(self, server_store):
        _story, (t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=t1)
        _answer("DEC-TST-1", answer="redis")
        (entry,) = _decision_notes(server_store, t1)
        assert entry.note == "Decision DEC-TST-1 answered: redis; rationale: (none given)"

    def test_withdrawal_logs_the_reason(self, server_store):
        _story, (t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=t1)
        _answer("DEC-TST-1", withdraw=True, reason="no longer relevant")
        (entry,) = _decision_notes(server_store, t1)
        assert entry.note == "Decision DEC-TST-1 withdrawn; reason: no longer relevant"
        assert entry.outcome.value == "info"

    def test_overwrite_logs_again(self, server_store):
        _story, (t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=t1)
        _answer("DEC-TST-1", answer="redis", rationale="first")
        out = _answer("DEC-TST-1", answer="sqs", rationale="second", overwrite=True)
        # Nothing new is unblocked, but the history still records the change.
        assert out["answered"]["unblocked"] == []
        notes = [e.note for e in _decision_notes(server_store, t1)]
        assert notes == [
            "Decision DEC-TST-1 answered: redis; rationale: first",
            "Decision DEC-TST-1 answered: sqs; rationale: second",
        ]

    def test_task_files_are_not_touched(self, server_store):
        _story, (t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=t1)
        task_file = server_store.project_dir / "tasks" / f"{t1}.md"
        before = task_file.read_bytes()
        _answer("DEC-TST-1", answer="x", rationale="y")
        assert task_file.read_bytes() == before
        assert len(_decision_notes(server_store, t1)) == 1

    @pytest.mark.parametrize(
        "first, kwargs",
        [
            (False, {"answer": None}),
            (False, {"answer": "   "}),
            (False, {"answer": "x", "reason": "why"}),
            (False, {"withdraw": True, "reason": None}),
            (False, {"withdraw": True, "reason": "moot", "answer": "x"}),
            (True, {"answer": "again"}),
            (True, {"withdraw": True, "reason": "again"}),
        ],
        ids=[
            "no-answer",
            "blank-answer",
            "reason-without-withdraw",
            "withdraw-no-reason",
            "withdraw-with-answer",
            "conflict-answer",
            "conflict-withdraw",
        ],
    )
    def test_refused_answers_write_no_entries(self, server_store, first, kwargs):
        story, (_t1,) = _story_with_tasks(server_store, "A", [(1, "todo")])
        _create(title="Q?", blocks=story)
        if first:
            _answer("DEC-TST-1", answer="redis", rationale="first")
        before = _logs_snapshot(server_store)
        with pytest.raises(ToolError):
            _answer("DEC-TST-1", **kwargs)
        assert _logs_snapshot(server_store) == before


# ─── pm_grab carries answered decisions (US-PM-66-5) ─────────────
#
# Story US-PM-66 criterion: "pm_grab's response lists answered decisions
# that blocked the task, its story or its epic".  Each entry is
# {id, title, answer, rationale}; open and withdrawn decisions are never
# listed, the key is absent when nothing applies, `decisions` is a
# projectable section, and a re-claim returns it too.

_GRAB_BODY = (
    "## Implementation\n\nDo the thing properly and completely.\n\n"
    "## Testing\n\nTest the thing properly.\n"
)


@pytest.fixture
def grab_tree(server_store):
    """EPIC-TST-1 > US-TST-1 (active) > US-TST-1-1, US-TST-1-2 (ready)."""
    epic = server_store.create_epic("Epic", "Epic description")
    story, _ = server_store.create_story(
        "Story", "Story description long enough to matter."
    )
    server_store.update(story.id, status="active", epic_id=epic.id)
    for title in ("Task one", "Task two"):
        server_store.create_task(story.id, title, _GRAB_BODY, points=1)
    return server_store


def _grabbed(task_id="US-TST-1-1", **kwargs):
    from projectman.server import pm_grab

    return yaml.safe_load(pm_grab(task_id, **kwargs))["grabbed"]


def _answered(blocks, answer="redis", rationale="already deployed", title="Q?"):
    created = _create(title=title, blocks=blocks)
    _answer(created["id"], answer=answer, rationale=rationale)
    return created["id"]


class TestGrabCarriesAnsweredDecisions:
    @pytest.mark.parametrize("target", ["US-TST-1-1", "US-TST-1", "EPIC-TST-1"])
    def test_criterion_answered_decision_on_task_story_or_epic_is_listed(
        self, grab_tree, target
    ):
        """US-PM-66 criterion: pm_grab's response lists answered decisions
        that blocked the task, its story or its epic."""
        dec_id = _answered(target, title="Which queue backend?")
        grabbed = _grabbed()
        assert grabbed["decisions"] == [
            {
                "id": dec_id,
                "title": "Which queue backend?",
                "answer": "redis",
                "rationale": "already deployed",
            }
        ]

    def test_all_three_levels_listed_in_number_order(self, grab_tree):
        ids = [
            _answered("EPIC-TST-1", answer="a"),
            _answered("US-TST-1", answer="b"),
            _answered("US-TST-1-1", answer="c"),
        ]
        grabbed = _grabbed()
        assert [d["id"] for d in grabbed["decisions"]] == ids
        assert [d["answer"] for d in grabbed["decisions"]] == ["a", "b", "c"]

    def test_open_and_withdrawn_decisions_are_excluded(self, grab_tree):
        answered = _answered("US-TST-1")
        withdrawn = _create(title="Moot?", blocks="US-TST-1")["id"]
        _answer(withdrawn, withdraw=True, reason="no longer relevant")
        # Open, but on the sibling task: an open decision on US-TST-1-1 itself
        # (or its story/epic) would refuse the grab outright.
        _create(title="Still open?", blocks="US-TST-1-2")
        grabbed = _grabbed()
        assert [d["id"] for d in grabbed["decisions"]] == [answered]

    def test_open_decision_on_the_task_refuses_the_grab_with_no_list(
        self, grab_tree
    ):
        from projectman.server import pm_grab

        _answered("US-TST-1")
        _create(title="Still open?", blocks="US-TST-1-1")
        out = yaml.safe_load(pm_grab("US-TST-1-1"))
        assert out["status"] == "not_ready"
        assert "grabbed" not in out and "decisions" not in out

    def test_decision_on_another_item_is_not_listed(self, grab_tree):
        _answered("US-TST-1-2")
        assert "decisions" not in _grabbed()

    def test_key_absent_when_no_decisions_exist(self, grab_tree):
        assert "decisions" not in _grabbed()

    def test_key_absent_when_only_withdrawn_apply(self, grab_tree):
        withdrawn = _create(title="Moot?", blocks="EPIC-TST-1")["id"]
        _answer(withdrawn, withdraw=True, reason="moot")
        assert "decisions" not in _grabbed()

    def test_rationale_is_null_when_none_was_given(self, grab_tree):
        dec = _create(title="Q?", blocks="US-TST-1")["id"]
        _answer(dec, answer="redis")
        assert _grabbed()["decisions"] == [
            {"id": dec, "title": "Q?", "answer": "redis", "rationale": None}
        ]

    def test_fields_projection_includes_decisions_when_named(self, grab_tree):
        dec = _answered("US-TST-1")
        grabbed = _grabbed(fields="decisions")
        assert set(grabbed) == {"task", "decisions"}
        assert grabbed["task"] == {"id": "US-TST-1-1"}
        assert [d["id"] for d in grabbed["decisions"]] == [dec]

    def test_verification_shape_excludes_decisions(self, grab_tree):
        _answered("US-TST-1")
        grabbed = _grabbed(fields="status,assignee")
        assert grabbed == {
            "task": {"id": "US-TST-1-1", "status": "in-progress", "assignee": "claude"}
        }

    def test_naming_decisions_with_none_applicable_is_not_an_error(self, grab_tree):
        assert _grabbed(fields="decisions") == {"task": {"id": "US-TST-1-1"}}

    def test_reclaim_returns_decisions_too(self, grab_tree):
        dec = _answered("EPIC-TST-1")
        first = _grabbed(run_id="run-a")
        again = _grabbed(run_id="run-a")
        assert again["decisions"] == first["decisions"]
        assert [d["id"] for d in again["decisions"]] == [dec]

    def test_done_next_grab_carries_decisions(self, grab_tree):
        from projectman.server import pm_done_next

        dec = _answered("US-TST-1-2")
        _grabbed()
        result = yaml.safe_load(pm_done_next("US-TST-1-1", note="done", run_id="r"))
        assert result["next"]["task"]["id"] == "US-TST-1-2"
        assert [d["id"] for d in result["next"]["decisions"]] == [dec]

    def test_grab_reads_the_decision_directory_once(self, grab_tree, monkeypatch):
        """One listing serves the open-decision gate and the answered list."""
        from projectman.store import Store

        _answered("US-TST-1")
        calls = []
        real = Store.list_decisions

        def counting(self, status=None):
            calls.append(status)
            return real(self, status=status)

        monkeypatch.setattr(Store, "list_decisions", counting)
        assert "decisions" in _grabbed()
        assert calls == [None]


# ─── Promoting a decision to an ADR (US-PM-66-6) ─────────────────
#
# Story US-PM-66 criterion: "Promoting a decision appends an ADR to
# DECISIONS.md numbered after the last ADR, and the decision and ADR
# reference each other".
#
# Choices pinned here: `pm_answer_decision(promote=True)` promotes while
# answering, and `promote=True` with no answer promotes a decision already
# answered.  The ADR goes newest-first (above the first existing ADR, as
# DECISIONS.md is kept), numbered one past the highest `## ADR-NNN` heading
# — gaps are not reused — and starts at ADR-001 when the file is missing or
# holds no ADR (then it is appended at the end).  Open, withdrawn and
# already-promoted decisions are refused and the refusal writes nothing.

_EXISTING = (
    "# Decisions\n\nNewest first.\n\n---\n\n"
    '<a id="adr-007"></a>\n\n## ADR-007: Seventh (2026-01-07)\n\n'
    "**Status:** Accepted\n\n---\n\n"
    '<a id="adr-002"></a>\n\n## ADR-002: Second (2026-01-02)\n\n'
    "**Status:** Accepted\n"
)


def _decisions_md(store):
    return store.project_dir / "DECISIONS.md"


def _promote_snapshot(store, decision_id="DEC-TST-1"):
    """Decision file, activity log and DECISIONS.md bytes, for refusals."""
    md = _decisions_md(store)
    return _snapshot(store, decision_id) + (md.read_bytes() if md.exists() else None,)


def _queue_decision(store):
    """DEC-TST-1 with context and three options, two of them to be rejected."""
    import os

    # Guard: the server writes into the tmp store, never the real one.
    assert os.getcwd() == str(store.project_dir.parent)
    _create(
        title="Which queue backend?",
        context="Workers need a durable queue; Redis is already deployed.",
        options=[
            {"label": "redis", "summary": "Redis streams", "cons": ["memory bound"]},
            {"label": "sqs", "summary": "Amazon SQS", "cons": ["vendor lock-in"]},
            {"label": "kafka", "summary": "Apache Kafka", "cons": ["heavy to run"]},
        ],
        recommendation="redis",
    )


class TestPromote:
    def test_answer_and_promote_numbers_after_the_highest_adr_despite_gaps(
        self, server_store
    ):
        """The criterion: numbered after the last ADR; both cite each other."""
        _decisions_md(server_store).write_text(_EXISTING)
        _queue_decision(server_store)

        answered = _answer(
            "DEC-TST-1", answer="redis", rationale="already deployed", promote=True
        )["answered"]
        assert answered["adr"] == "ADR-008"

        meta, _ = server_store.get_decision("DEC-TST-1")
        assert meta.status.value == "answered"
        assert meta.adr == "ADR-008"

        text = _decisions_md(server_store).read_text()
        # Newest first: above ADR-007, the header kept, nothing lost.
        assert text.startswith("# Decisions\n\nNewest first.\n\n---\n\n")
        assert (
            text.index("## ADR-008:")
            < text.index("## ADR-007:")
            < text.index("## ADR-002:")
        )
        assert text.count("## ADR-") == 3
        assert _EXISTING.split("---\n\n", 1)[1] in text
        entry = text[text.index("## ADR-008:"):text.index("## ADR-007:")]
        assert "DEC-TST-1" in entry

    def test_adr_content_has_context_decision_rejected_options_and_dec_id(
        self, server_store
    ):
        _queue_decision(server_store)
        _answer("DEC-TST-1", answer="redis", rationale="already deployed", promote=True)

        text = _decisions_md(server_store).read_text()
        entry = text[text.index('<a id="adr-001"></a>'):]
        assert "## ADR-001: Which queue backend? (" in entry
        assert "**Status:** Accepted" in entry and "DEC-TST-1" in entry
        assert (
            "**Context.** Workers need a durable queue; Redis is already deployed."
            in entry
        )
        decision = entry[
            entry.index("**Decision.**"):entry.index("**Alternatives rejected.**")
        ]
        assert "redis" in decision and "Redis streams" in decision
        assert "already deployed" in decision
        rejected = entry[entry.index("**Alternatives rejected.**"):]
        assert "- **sqs.** Amazon SQS" in rejected and "vendor lock-in" in rejected
        assert "- **kafka.** Apache Kafka" in rejected and "heavy to run" in rejected
        assert "**redis.**" not in rejected

    @pytest.mark.parametrize(
        "existing",
        [None, "# Decision Log\n\n## Decisions\n\n<!-- none yet -->\n"],
        ids=["missing", "no-adrs"],
    )
    def test_first_adr_is_001(self, server_store, existing):
        if existing is not None:
            _decisions_md(server_store).write_text(existing)
        _create(title="Q?")
        answered = _answer("DEC-TST-1", answer="yes", promote=True)["answered"]
        assert answered["adr"] == "ADR-001"
        text = _decisions_md(server_store).read_text()
        assert "## ADR-001: Q? (" in text
        assert '<a id="adr-001"></a>' in text
        if existing is not None:
            assert text.startswith(existing.rstrip())
        assert server_store.get_decision("DEC-TST-1")[0].adr == "ADR-001"

    def test_promote_alone_promotes_an_answered_decision(self, server_store):
        _decisions_md(server_store).write_text(_EXISTING)
        _queue_decision(server_store)
        _answer("DEC-TST-1", answer="sqs", rationale="managed")
        assert "## ADR-008" not in _decisions_md(server_store).read_text()

        out = _answer("DEC-TST-1", promote=True)
        assert out == {"promoted": {"id": "DEC-TST-1", "adr": "ADR-008"}}
        meta, _ = server_store.get_decision("DEC-TST-1")
        assert (meta.status.value, meta.answer, meta.adr) == ("answered", "sqs", "ADR-008")
        text = _decisions_md(server_store).read_text()
        entry = text[text.index("## ADR-008:"):text.index("## ADR-007:")]
        rejected = entry.split("**Alternatives rejected.**")[1]
        assert "**redis.**" in rejected and "**sqs.**" not in rejected
        assert "managed" in entry

    def test_promotion_is_logged_on_the_doc_and_the_decision(self, server_store):
        _create(title="Q?")
        _answer("DEC-TST-1", answer="yes", promote=True)
        doc_events = _events(server_store, "DECISIONS")
        assert [(e["event_type"], e["item_type"]) for e in doc_events] == [
            ("update", "note")
        ]
        assert doc_events[0]["changes"]["adr"] == "ADR-001"
        assert doc_events[0]["changes"]["decision"] == "DEC-TST-1"
        last = _events(server_store, "DEC-TST-1")[-1]
        assert last["changes"]["adr"] == {"before": None, "after": "ADR-001"}

    def test_without_promote_nothing_is_written_to_decisions_md(self, server_store):
        _create(title="Q?")
        answered = _answer("DEC-TST-1", answer="yes")["answered"]
        assert "adr" not in answered
        assert not _decisions_md(server_store).exists()
        assert server_store.get_decision("DEC-TST-1")[0].adr is None

    def test_promote_alone_on_an_open_decision_is_refused(self, server_store):
        _decisions_md(server_store).write_text(_EXISTING)
        _create(title="Q?")
        before = _promote_snapshot(server_store)
        with pytest.raises(
            ToolError, match=r"is open; only an answered.*\[code: conflict\]"
        ):
            _answer("DEC-TST-1", promote=True)
        assert _promote_snapshot(server_store) == before

    def test_a_withdrawn_decision_is_refused(self, server_store):
        _decisions_md(server_store).write_text(_EXISTING)
        _create(title="Q?")
        _answer("DEC-TST-1", withdraw=True, reason="moot")
        before = _promote_snapshot(server_store)
        with pytest.raises(
            ToolError, match=r"is withdrawn; only an answered.*\[code: conflict\]"
        ):
            _answer("DEC-TST-1", promote=True)
        with pytest.raises(ToolError, match=r"cannot be promoted.*\[code: invalid\]"):
            _answer(
                "DEC-TST-1", withdraw=True, reason="again", overwrite=True, promote=True
            )
        assert _promote_snapshot(server_store) == before

    def test_withdraw_with_promote_is_refused(self, server_store):
        _create(title="Q?")
        before = _promote_snapshot(server_store)
        with pytest.raises(ToolError, match=r"cannot be promoted.*\[code: invalid\]"):
            _answer("DEC-TST-1", withdraw=True, reason="moot", promote=True)
        assert _promote_snapshot(server_store) == before
        assert server_store.get_decision("DEC-TST-1")[0].status.value == "open"

    def test_promoting_twice_is_refused(self, server_store):
        _decisions_md(server_store).write_text(_EXISTING)
        _create(title="Q?")
        _answer("DEC-TST-1", answer="yes", promote=True)
        before = _promote_snapshot(server_store)
        with pytest.raises(
            ToolError, match=r"already promoted to ADR-008.*\[code: conflict\]"
        ):
            _answer("DEC-TST-1", promote=True)
        # Re-answering with overwrite cannot mint a second ADR either.
        with pytest.raises(
            ToolError, match=r"already promoted to ADR-008.*\[code: conflict\]"
        ):
            _answer("DEC-TST-1", answer="no", overwrite=True, promote=True)
        assert _promote_snapshot(server_store) == before
        is_error, text = call_over_the_wire(
            "pm_answer_decision", {"id": "DEC-TST-1", "promote": True}
        )
        assert is_error and "already promoted" in text
        assert _promote_snapshot(server_store) == before

    def test_promote_alone_refuses_a_rationale(self, server_store):
        _create(title="Q?")
        _answer("DEC-TST-1", answer="yes")
        before = _promote_snapshot(server_store)
        with pytest.raises(
            ToolError, match=r"rationale goes with an answer.*\[code: invalid\]"
        ):
            _answer("DEC-TST-1", promote=True, rationale="why")
        assert _promote_snapshot(server_store) == before

    def test_the_adr_field_is_validated(self):
        from datetime import date

        from projectman.models import DecisionFrontmatter

        base = {
            "id": "DEC-TST-1",
            "title": "Q?",
            "created": date.today(),
            "updated": date.today(),
        }
        assert DecisionFrontmatter(**base).adr is None
        assert DecisionFrontmatter(**base, adr="ADR-012").adr == "ADR-012"
        with pytest.raises(ValueError):
            DecisionFrontmatter(**base, adr="ADR-1")


def test_pm_update_doc_writes_atomically_and_logs(server_store):
    """pm_update_doc shares the promotion's write path (US-PM-66-6)."""
    from projectman.server import pm_update_doc

    assert pm_update_doc("decisions", "# Decisions\n") == "updated: DECISIONS.md"
    assert _decisions_md(server_store).read_text() == "# Decisions\n"
    events = _events(server_store, "DECISIONS")
    assert [(e["event_type"], e["item_type"], e["changes"]) for e in events] == [
        ("update", "note", {"doc": "DECISIONS.md"})
    ]
    assert not list(server_store.project_dir.glob(".DECISIONS.md.*.tmp"))
