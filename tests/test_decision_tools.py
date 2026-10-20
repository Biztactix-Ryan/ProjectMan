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

    def test_unestimated_and_unblocking_decisions_score_zero(self, server_store):
        story, _ = _story_with_tasks(server_store, "S", [(None, "todo")])
        _create(title="Unestimated?", blocks=story)
        _create(title="Blocks nothing?")
        assert [d["blocked_points"] for d in _list()["decisions"]] == [0, 0]


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
