"""Store-side decisions: ``.project/decisions/DEC-<PREFIX>-N.md`` (US-PM-63-7).

Every test runs against the tmp_path-isolated ``store`` fixture; nothing here
touches the real ``.project``.
"""

import json
from datetime import date, timedelta

import frontmatter
import pytest

from projectman.errors import NotFoundError, ValidationError
from projectman.models import DecisionStatus


def _log(store) -> list[dict]:
    path = store.project_dir / "activity.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _decision_events(store, event_type=None) -> list[dict]:
    return [
        e
        for e in _log(store)
        if e["item_type"] == "decision"
        and (event_type is None or e["event_type"] == event_type)
    ]


class TestCreateDecision:
    def test_writes_file_with_frontmatter_and_body(self, store):
        meta = store.create_decision(
            "Which queue backend?",
            "We need a queue. Redis is already deployed.",
            priority="must",
            raised_by="claude",
            options=[
                {"label": "redis", "summary": "Reuse Redis", "pros": ["deployed"]},
                {"label": "sqs", "cons": ["new dependency"]},
            ],
            recommendation="redis",
        )
        assert meta.id == "DEC-TST-1"
        path = store.project_dir / "decisions" / "DEC-TST-1.md"
        assert path.exists()
        post = frontmatter.load(str(path))
        assert post.metadata["id"] == "DEC-TST-1"
        assert post.metadata["title"] == "Which queue backend?"
        assert post.metadata["status"] == "open"
        assert post.metadata["priority"] == "must"
        assert post.metadata["raised_by"] == "claude"
        assert post.metadata["recommendation"] == "redis"
        assert [o["label"] for o in post.metadata["options"]] == ["redis", "sqs"]
        assert post.content == "We need a queue. Redis is already deployed."

    def test_decisions_dir_is_created_lazily(self, store):
        # Like sprints: init does not make the directory; the first write does.
        assert not store.decisions_dir.exists()
        assert store.list_decisions() == []
        store.create_decision("Q?")
        assert store.decisions_dir.is_dir()

    def test_second_create_gets_next_number(self, store):
        assert store.create_decision("First?").id == "DEC-TST-1"
        assert store.create_decision("Second?").id == "DEC-TST-2"

    def test_gaps_are_skipped_not_filled(self, store):
        store.decisions_dir.mkdir(parents=True)
        (store.decisions_dir / "DEC-TST-1.md").write_text("---\nid: x\n---\n")
        (store.decisions_dir / "DEC-TST-5.md").write_text("---\nid: x\n---\n")
        assert store.create_decision("After the gap?").id == "DEC-TST-6"

    def test_number_freed_by_deletion_is_not_reissued_this_session(self, store):
        store.create_decision("One?")
        second = store.create_decision("Two?")
        store._decision_path(second.id).unlink()
        assert store.create_decision("Three?").id == "DEC-TST-3"

    def test_other_prefix_files_are_not_counted(self, store):
        store.decisions_dir.mkdir(parents=True)
        (store.decisions_dir / "DEC-PRJ-40.md").write_text("---\nid: x\n---\n")
        assert store.create_decision("Q?").id == "DEC-TST-1"

    def test_logs_create_event_with_decision_item_type(self, store):
        store.create_decision("Q?")
        events = _decision_events(store, "create")
        assert len(events) == 1
        assert events[0]["item_id"] == "DEC-TST-1"

    def test_blocks_accepts_existing_task_story_and_epic(self, store):
        story, _ = store.create_story("Story", "Body")
        task = store.create_task(story.id, "Task", "Body")
        epic = store.create_epic("Epic", "Body")
        meta = store.create_decision("Q?", blocks=[task.id, story.id, epic.id])
        assert meta.blocks == [task.id, story.id, epic.id]

    def test_unknown_blocks_id_is_rejected_and_nothing_written(self, store):
        story, _ = store.create_story("Story", "Body")
        with pytest.raises(ValidationError, match="US-TST-99"):
            store.create_decision("Q?", blocks=[story.id, "US-TST-99"])
        assert not store._decision_path("DEC-TST-1").exists()
        assert _decision_events(store) == []
        # A refused create does not burn a number.
        assert store.create_decision("Q?").id == "DEC-TST-1"

    def test_badly_shaped_blocks_id_is_rejected(self, store):
        with pytest.raises(ValidationError):
            store.create_decision("Q?", blocks=["SPRINT-TST-1"])

    def test_refuses_to_overwrite_existing_file(self, store, monkeypatch):
        store.decisions_dir.mkdir(parents=True)
        target = store._decision_path("DEC-TST-3")
        target.write_text("keep me")
        monkeypatch.setattr(store, "_next_decision_id", lambda: "DEC-TST-3")
        with pytest.raises(FileExistsError, match="DEC-TST-3 already exists"):
            store.create_decision("Q?")
        assert target.read_text() == "keep me"
        assert _decision_events(store) == []


class TestGetAndListDecisions:
    def test_get_returns_meta_and_body(self, store):
        store.create_decision("Q?", "Context here")
        meta, body = store.get_decision("DEC-TST-1")
        assert meta.title == "Q?"
        assert body == "Context here"

    def test_unified_get_dispatches_to_decisions(self, store):
        store.create_decision("Q?", "Context")
        meta, _ = store.get("DEC-TST-1")
        assert meta.id == "DEC-TST-1"

    def test_get_missing_raises_not_found(self, store):
        with pytest.raises(NotFoundError):
            store.get_decision("DEC-TST-9")

    def test_list_and_filter_by_status(self, store):
        store.create_decision("A?")
        store.create_decision("B?")
        store.create_decision("C?")
        store.update_decision("DEC-TST-2", status="answered", answer="yes")
        store.update_decision("DEC-TST-3", status="withdrawn")
        assert [d.id for d in store.list_decisions()] == [
            "DEC-TST-1",
            "DEC-TST-2",
            "DEC-TST-3",
        ]
        assert [d.id for d in store.list_decisions(status="open")] == ["DEC-TST-1"]
        assert [d.id for d in store.list_decisions(status="answered")] == ["DEC-TST-2"]
        assert [d.id for d in store.list_decisions(status="withdrawn")] == ["DEC-TST-3"]

    def test_list_rejects_unknown_status(self, store):
        with pytest.raises(ValidationError):
            store.list_decisions(status="archived")


class TestMalformedAndArchived:
    """Same rules as stories: malformed files are skipped by list and raise
    on get; archiving is never a move, so every file stays numbered."""

    def test_malformed_file_is_skipped_by_list(self, store):
        store.create_decision("Good?")
        (store.decisions_dir / "DEC-TST-2.md").write_text(
            "---\nid: DEC-TST-2\nstatus: nonsense\n---\nbroken\n"
        )
        assert [d.id for d in store.list_decisions()] == ["DEC-TST-1"]

    def test_malformed_file_raises_on_get(self, store):
        store.decisions_dir.mkdir(parents=True)
        (store.decisions_dir / "DEC-TST-1.md").write_text(
            "---\nid: DEC-TST-1\n---\nno title or dates\n"
        )
        with pytest.raises(Exception):
            store.get_decision("DEC-TST-1")

    def test_malformed_file_still_holds_its_number(self, store):
        store.decisions_dir.mkdir(parents=True)
        (store.decisions_dir / "DEC-TST-1.md").write_text("not frontmatter at all")
        assert store.create_decision("Q?").id == "DEC-TST-2"

    def test_malformed_file_refuses_update(self, store):
        store.decisions_dir.mkdir(parents=True)
        path = store.decisions_dir / "DEC-TST-1.md"
        path.write_text("---\nid: DEC-TST-1\n---\nbroken\n")
        with pytest.raises(ValidationError):
            store.update_decision("DEC-TST-1", title="Fixed?")
        assert path.read_text() == "---\nid: DEC-TST-1\n---\nbroken\n"

    def test_withdrawn_decision_stays_in_place_and_keeps_its_number(self, store):
        store.create_decision("A?")
        store.update_decision("DEC-TST-1", status="withdrawn")
        assert store._decision_path("DEC-TST-1").exists()
        assert store.create_decision("B?").id == "DEC-TST-2"

    def test_archive_refuses_decisions(self, store):
        store.create_decision("A?")
        with pytest.raises(ValidationError, match="withdraw"):
            store.archive("DEC-TST-1")
        meta, _ = store.get_decision("DEC-TST-1")
        assert meta.status == DecisionStatus.open

    def test_archived_item_can_still_be_blocked(self, store):
        story, _ = store.create_story("Story", "Body")
        store.archive(story.id)
        assert store.create_decision("Q?", blocks=[story.id]).blocks == [story.id]


class TestUpdateDecision:
    def test_updates_fields_and_body_and_bumps_updated(self, store, monkeypatch):
        store.create_decision("Q?", "Old context")
        path = store._decision_path("DEC-TST-1")
        post = frontmatter.load(str(path))
        post.metadata["updated"] = (date.today() - timedelta(days=3)).isoformat()
        path.write_text(frontmatter.dumps(post))

        meta = store.update_decision(
            "DEC-TST-1",
            title="Sharper question?",
            priority="must",
            options=[{"label": "a"}, {"label": "b"}],
            recommendation="b",
            body="New context",
        )
        assert meta.title == "Sharper question?"
        assert meta.priority.value == "must"
        assert meta.recommendation == "b"
        assert meta.updated == date.today()
        on_disk, body = store.get_decision("DEC-TST-1")
        assert on_disk.title == "Sharper question?"
        assert on_disk.updated == date.today()
        assert body == "New context"

    def test_answer_round_trips(self, store):
        store.create_decision("Q?", options=[{"label": "a"}])
        store.update_decision(
            "DEC-TST-1",
            status="answered",
            answer="a",
            rationale="cheapest",
            answered_by="farhan",
        )
        meta, _ = store.get_decision("DEC-TST-1")
        assert meta.status == DecisionStatus.answered
        assert meta.answer == "a"
        assert meta.rationale == "cheapest"
        assert meta.answered_by == "farhan"

    def test_answered_without_answer_text_is_rejected(self, store):
        store.create_decision("Q?")
        with pytest.raises(ValidationError, match="answer"):
            store.update_decision("DEC-TST-1", status="answered")
        with pytest.raises(ValidationError, match="answer"):
            store.update_decision("DEC-TST-1", status="answered", answer="   ")
        meta, _ = store.get_decision("DEC-TST-1")
        assert meta.status == DecisionStatus.open

    def test_unknown_blocks_id_rejected_on_update(self, store):
        story, _ = store.create_story("Story", "Body")
        store.create_decision("Q?", blocks=[story.id])
        before = store._decision_path("DEC-TST-1").read_text()
        with pytest.raises(ValidationError, match="EPIC-TST-9"):
            store.update_decision("DEC-TST-1", blocks=[story.id, "EPIC-TST-9"])
        assert store._decision_path("DEC-TST-1").read_text() == before
        assert _decision_events(store, "update") == []

    def test_blocks_can_be_changed_to_existing_items(self, store):
        story, _ = store.create_story("Story", "Body")
        epic = store.create_epic("Epic", "Body")
        store.create_decision("Q?", blocks=[story.id])
        meta = store.update_decision("DEC-TST-1", blocks=[epic.id])
        assert meta.blocks == [epic.id]

    def test_immutable_and_unknown_fields_are_refused(self, store):
        store.create_decision("Q?")
        with pytest.raises(ValidationError, match="id"):
            store.update_decision("DEC-TST-1", id="DEC-TST-2")
        with pytest.raises(ValidationError, match="points"):
            store.update_decision("DEC-TST-1", points=3)

    def test_update_missing_raises_not_found(self, store):
        with pytest.raises(NotFoundError):
            store.update_decision("DEC-TST-4", title="x")

    def test_logs_update_event_with_changes(self, store):
        store.create_decision("Q?", "ctx")
        store.update_decision("DEC-TST-1", title="New?", body="ctx2", run_id="run-1")
        events = _decision_events(store)
        assert [e["event_type"] for e in events] == ["create", "update"]
        update = events[1]
        assert update["item_id"] == "DEC-TST-1"
        assert update["run_id"] == "run-1"
        assert update["changes"]["title"] == {"before": "Q?", "after": "New?"}
        assert update["changes"]["body"] == {"before": "ctx", "after": "ctx2"}
