"""Audit checks over open decisions (US-PM-67-7).

Pins the acceptance criterion

    > pm_audit flags stale open decisions, decisions blocking nothing open,
    > and decisions blocking archived items

and the three finding codes behind it: ``decision-stale``,
``decision-blocks-nothing`` and ``decision-blocks-archived``.  All three are
warnings — never errors, because /pm-orchestrate halts a run on any
error-level finding and a parked question must not stop automation.

Every test runs in a ``tmp_path`` project: the cwd is moved there, the
``PROJECTMAN_ROOT`` pin is dropped, and the store root is asserted to be the
tmp project before anything is written or audited.  Nothing here reads or
writes the real ``.project``.
"""

import re
from datetime import date, timedelta
from pathlib import Path

import frontmatter
import pytest
import yaml

from projectman.audit import (
    DIGEST_LINE_PREFIX,
    check_decisions,
    compute_state_digest,
    run_audit,
)
from projectman.config import find_project_root
from projectman.models import (
    DEFAULT_DECISION_STALE_DAYS,
    DecisionFrontmatter,
    ProjectConfig,
)
from projectman.store import Store, clear_all_caches

DECISION_CODES = {
    "decision-stale",
    "decision-blocks-nothing",
    "decision-blocks-archived",
}

_COUNTS_RE = re.compile(
    r"\*\*Errors:\*\* (\d+) \| \*\*Warnings:\*\* (\d+) \| \*\*Info:\*\* (\d+)"
)


# ── Fixtures and helpers ────────────────────────────────────────────────


@pytest.fixture
def dec_store(tmp_project, monkeypatch):
    """A tmp project with one story and three open tasks, cwd moved into it.

    US-TST-1 holds US-TST-1-1 / -2 / -3, all ``todo``.
    """
    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    clear_all_caches()
    assert find_project_root() == tmp_project.resolve()
    store = Store(tmp_project)
    assert store.project_dir.resolve().is_relative_to(tmp_project.resolve())
    assert store.project_dir.resolve() == (tmp_project / ".project").resolve()

    store.create_story("Story", "A story to hang tasks off")
    for n in range(1, 4):
        store.create_task("US-TST-1", f"Task {n}", "A task with a body long enough")
    return store


def _write_decision(
    store: Store,
    number: int,
    *,
    blocks=(),
    age_days: int = 0,
    status: str = "open",
    answer=None,
) -> Path:
    """Write ``DEC-TST-<number>`` straight to disk with a chosen ``created``.

    The store's own create stamps today and update_decision refuses to touch
    ``created``, so the age can only be set by writing the file.
    """
    created = date.today() - timedelta(days=age_days)
    meta = DecisionFrontmatter(
        id=f"DEC-TST-{number}",
        title=f"Question {number}?",
        status=status,
        blocks=list(blocks),
        answer=answer,
        created=created,
        updated=created,
    )
    store.decisions_dir.mkdir(parents=True, exist_ok=True)
    path = store.decisions_dir / f"DEC-TST-{number}.md"
    assert path.resolve().is_relative_to(store.project_dir.resolve())
    path.write_text(
        frontmatter.dumps(frontmatter.Post(content="Context.", **meta.model_dump(mode="json")))
    )
    return path


def _findings(store: Store, *, stale_days=DEFAULT_DECISION_STALE_DAYS, today=None):
    clear_all_caches()
    return check_decisions(
        store,
        today=today or date.today(),
        stale_days=stale_days,
        tasks=store.list_tasks(),
        stories=store.list_stories(),
        epics=store.list_epics(),
    )


def _codes(findings, decision_id):
    return sorted(f["check"] for f in findings if f["items"][0] == decision_id)


def _set_config(root: Path, **values):
    path = root / ".project" / "config.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(values)
    path.write_text(yaml.dump(data))
    clear_all_caches()


def _counts(report):
    match = _COUNTS_RE.search(report)
    assert match is not None, report
    return tuple(int(g) for g in match.groups())


# ── decision-stale ──────────────────────────────────────────────────────


def test_open_decision_exactly_at_the_threshold_is_not_stale(dec_store):
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=14)
    assert _codes(_findings(dec_store), "DEC-TST-1") == []


def test_open_decision_one_day_past_the_threshold_is_stale(dec_store):
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=15)
    findings = _findings(dec_store)
    assert _codes(findings, "DEC-TST-1") == ["decision-stale"]
    (finding,) = findings
    assert finding["severity"] == "warning"
    assert finding["items"] == ["DEC-TST-1"]
    assert "15 days" in finding["message"]


def test_fresh_decision_is_not_stale(dec_store):
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=0)
    assert _findings(dec_store) == []


def test_default_threshold_is_fourteen_days():
    assert DEFAULT_DECISION_STALE_DAYS == 14
    assert ProjectConfig(name="x").decision_stale_days == 14


@pytest.mark.parametrize("junk", ["soon", -1, float("nan"), float("inf"), None])
def test_a_junk_threshold_falls_back_to_the_default(junk):
    assert ProjectConfig(name="x", decision_stale_days=junk).decision_stale_days == 14


def test_threshold_is_read_from_config(dec_store, tmp_project):
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=3)
    _write_decision(dec_store, 2, blocks=["US-TST-1-1"], age_days=4)

    report = run_audit(tmp_project)
    assert "DEC-TST-1" not in report and "DEC-TST-2" not in report

    _set_config(tmp_project, decision_stale_days=3)
    assert Store(tmp_project).config.decision_stale_days == 3
    report = run_audit(tmp_project)
    lines = [line for line in report.splitlines() if "has been open for" in line]
    assert len(lines) == 1
    assert "Decision DEC-TST-2 has been open for 4 days" in lines[0]
    assert "decision_stale_days is 3" in lines[0]


def test_threshold_is_a_parameter_of_the_check(dec_store):
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=5)
    assert _codes(_findings(dec_store, stale_days=5), "DEC-TST-1") == []
    assert _codes(_findings(dec_store, stale_days=4), "DEC-TST-1") == ["decision-stale"]


# ── decision-blocks-nothing ─────────────────────────────────────────────


def test_empty_blocks_list_blocks_nothing(dec_store):
    _write_decision(dec_store, 1, blocks=[])
    findings = _findings(dec_store)
    assert _codes(findings, "DEC-TST-1") == ["decision-blocks-nothing"]
    assert findings[0]["severity"] == "warning"
    assert findings[0]["items"] == ["DEC-TST-1"]
    assert "blocks list is empty" in findings[0]["message"]


def test_all_blocked_items_done_blocks_nothing(dec_store):
    dec_store.update("US-TST-1-1", status="done")
    dec_store.update("US-TST-1-2", status="done")
    _write_decision(dec_store, 1, blocks=["US-TST-1-1", "US-TST-1-2"])
    findings = _findings(dec_store)
    assert _codes(findings, "DEC-TST-1") == ["decision-blocks-nothing"]
    assert "US-TST-1-1, US-TST-1-2" in findings[0]["message"]


def test_one_open_blocked_item_is_enough(dec_store):
    dec_store.update("US-TST-1-1", status="done")
    _write_decision(dec_store, 1, blocks=["US-TST-1-1", "US-TST-1-2"])
    assert _findings(dec_store) == []


def test_done_story_counts_as_done(dec_store):
    dec_store.update("US-TST-1", status="done")
    _write_decision(dec_store, 1, blocks=["US-TST-1"])
    assert "decision-blocks-nothing" in _codes(_findings(dec_store), "DEC-TST-1")


def test_open_story_and_epic_are_open(dec_store):
    dec_store.create_epic("Epic", "An epic with a body")
    _write_decision(dec_store, 1, blocks=["US-TST-1"])
    _write_decision(dec_store, 2, blocks=["EPIC-TST-1"])
    assert _findings(dec_store) == []


# ── decision-blocks-archived ────────────────────────────────────────────


def test_blocking_an_archived_task_is_flagged(dec_store):
    dec_store.archive("US-TST-1-1")
    _write_decision(dec_store, 1, blocks=["US-TST-1-1", "US-TST-1-2"])
    findings = _findings(dec_store)
    assert _codes(findings, "DEC-TST-1") == ["decision-blocks-archived"]
    (finding,) = findings
    assert finding["severity"] == "warning"
    assert finding["items"] == ["DEC-TST-1", "US-TST-1-1"]


def test_blocking_an_archived_story_and_epic_is_flagged(dec_store):
    dec_store.create_story("Second story", "Another story with a body")
    dec_store.create_epic("Epic", "An epic with a body")
    dec_store.archive("US-TST-2")
    dec_store.archive("EPIC-TST-1")
    _write_decision(dec_store, 1, blocks=["US-TST-2", "EPIC-TST-1", "US-TST-1-1"])
    findings = _findings(dec_store)
    archived = [f for f in findings if f["check"] == "decision-blocks-archived"]
    assert len(archived) == 1
    assert archived[0]["items"] == ["DEC-TST-1", "US-TST-2", "EPIC-TST-1"]
    # US-TST-1-1 is still open, so the decision still blocks something.
    assert _codes(findings, "DEC-TST-1") == ["decision-blocks-archived"]


def test_blocking_only_archived_items_also_blocks_nothing(dec_store):
    dec_store.archive("US-TST-1-1")
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"])
    assert _codes(_findings(dec_store), "DEC-TST-1") == [
        "decision-blocks-archived",
        "decision-blocks-nothing",
    ]


# ── Answered / withdrawn decisions are never flagged ────────────────────


@pytest.mark.parametrize("status,answer", [("answered", "yes"), ("withdrawn", None)])
def test_settled_decisions_are_never_flagged(dec_store, tmp_project, status, answer):
    dec_store.archive("US-TST-1-1")
    dec_store.update("US-TST-1-2", status="done")
    # Every trigger at once: very old, empty, all-done, archived.
    _write_decision(dec_store, 1, blocks=[], age_days=400, status=status, answer=answer)
    _write_decision(dec_store, 2, blocks=["US-TST-1-2"], age_days=400, status=status, answer=answer)
    _write_decision(dec_store, 3, blocks=["US-TST-1-1"], age_days=400, status=status, answer=answer)
    assert _findings(dec_store) == []
    report = run_audit(tmp_project, include_info=True)
    assert "DEC-TST-" not in report
    assert "DEC-TST-" not in (tmp_project / ".project" / "DRIFT.md").read_text()


# ── Through run_audit / pm_audit: severity, DRIFT.md, digest ────────────


@pytest.fixture
def all_three(dec_store):
    """One open decision per finding code."""
    dec_store.archive("US-TST-1-3")
    _write_decision(dec_store, 1, blocks=["US-TST-1-1"], age_days=30)  # stale
    _write_decision(dec_store, 2, blocks=[])  # blocks nothing
    _write_decision(dec_store, 3, blocks=["US-TST-1-2", "US-TST-1-3"])  # archived
    return dec_store


def test_pm_audit_flags_all_three_as_warnings_never_errors(all_three, tmp_project):
    from projectman.server import _store_cache, pm_audit

    clear_all_caches()
    _store_cache.clear()
    assert find_project_root() == tmp_project.resolve()
    report = pm_audit()

    lines = {
        line for line in report.splitlines()
        if line.startswith("- [") and "Decision DEC-TST-" in line
    }
    assert any(l.startswith("- [WARN] Decision DEC-TST-1 has been open for 30 days") for l in lines)
    assert any(l.startswith("- [WARN] Decision DEC-TST-2 is open but blocks nothing") for l in lines)
    assert any(
        l.startswith("- [WARN] Decision DEC-TST-3 blocks archived item(s) US-TST-1-3")
        for l in lines
    )
    assert len(lines) == 3
    assert not any("[ERROR]" in l or "[INFO]" in l for l in lines)

    errors, warnings, _ = _counts(report)
    assert errors == 0
    assert warnings >= 3


def test_no_decision_finding_is_ever_an_error(all_three):
    findings = _findings(all_three)
    assert {f["check"] for f in findings} == DECISION_CODES
    assert {f["severity"] for f in findings} == {"warning"}


def test_drift_md_contains_the_decision_findings(all_three, tmp_project):
    run_audit(tmp_project, include_info=False)
    drift = (tmp_project / ".project" / "DRIFT.md").read_text()
    assert "[WARN] Decision DEC-TST-1 has been open for 30 days" in drift
    assert "[WARN] Decision DEC-TST-2 is open but blocks nothing" in drift
    assert "[WARN] Decision DEC-TST-3 blocks archived item(s) US-TST-1-3" in drift


def test_digest_changes_when_a_decision_is_edited(all_three, tmp_project):
    before = compute_state_digest(tmp_project)
    assert compute_state_digest(tmp_project) == before

    all_three.update_decision("DEC-TST-2", blocks=["US-TST-1-1"])
    after_edit = compute_state_digest(tmp_project)
    assert after_edit != before

    report = run_audit(tmp_project, since=before)
    assert f"{DIGEST_LINE_PREFIX}{after_edit}" in report
    assert "unchanged: true" not in report
    assert "DEC-TST-2" not in report  # it blocks an open task now


def test_digest_changes_when_a_decision_is_added(dec_store, tmp_project):
    before = compute_state_digest(tmp_project)
    _write_decision(dec_store, 1, blocks=[])
    assert compute_state_digest(tmp_project) != before


def test_no_decisions_means_no_decision_findings(dec_store, tmp_project):
    assert not dec_store.decisions_dir.exists()
    assert _findings(dec_store) == []
    report = run_audit(tmp_project, include_info=True)
    assert "Decision DEC-" not in report


def test_archived_items_are_read_at_most_once_per_audit(dec_store, tmp_project, monkeypatch):
    """No N+1: an archived story named by many decisions is read once."""
    dec_store.create_story("Second story", "Another story with a body")
    dec_store.archive("US-TST-2")
    for n in range(1, 6):
        _write_decision(dec_store, n, blocks=["US-TST-2", "US-TST-1-1"])

    calls: list[str] = []
    original = Store.get_story

    def spy(self, item_id, *args, **kwargs):
        calls.append(item_id)
        return original(self, item_id, *args, **kwargs)

    monkeypatch.setattr(Store, "get_story", spy)
    clear_all_caches()
    run_audit(tmp_project)
    assert calls.count("US-TST-2") <= 1
