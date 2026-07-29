"""pm_audit checks for acceptance-criteria / test-task drift.

US-PM-5-7.  Before this, editing a story's criteria left its auto-generated
test tasks quoting text that no longer existed and created nothing for the new
criteria — and ``pm_audit`` reported "No issues found. Project is clean." the
entire time.  /pm-orchestrate uses pm_audit as its systemic health check, so
that blind spot was a blind spot in the safety net.

Two checks, both warning-level (see the rationale in ``audit.py``):

* ``criteria-without-test-task`` — a live criterion nothing tests.
* ``test-task-stale-criterion`` — a test task quoting a dead criterion.
"""

import frontmatter
import pytest

from projectman.audit import run_audit
from projectman.store import Store, clear_all_caches, generate_test_task_body

DRIFT_CHECKS = ("criteria-without-test-task", "test-task-stale-criterion")


def _set_criteria_on_disk(tmp_project, story_id, criteria):
    """Edit a story's criteria the way a human editing the file does.

    Deliberately bypasses ``Store.update`` — that reconciles, and reconciled
    data is exactly the state that must produce no finding.  This reproduces
    how the drift got into the real project in the first place.
    """
    path = tmp_project / ".project" / "stories" / f"{story_id}.md"
    post = frontmatter.load(str(path))
    post.metadata["acceptance_criteria"] = criteria
    path.write_text(frontmatter.dumps(post))
    clear_all_caches()


def _audit_lines(tmp_project):
    clear_all_caches()
    return run_audit(tmp_project).splitlines()


def _drift_lines(tmp_project):
    """Report lines produced by the two drift checks, keyed by story."""
    lines = _audit_lines(tmp_project)
    return [
        l
        for l in lines
        if "no test task" in l or "no longer exists" in l
    ]


def _counts(tmp_project):
    """(errors, warnings, info) from the report header."""
    header = next(l for l in _audit_lines(tmp_project) if l.startswith("**Errors:**"))
    nums = [int(p) for p in header.replace("*", "").replace("|", " ").split() if p.isdigit()]
    return tuple(nums)


class TestDriftIsDetected:
    def test_new_criterion_with_no_test_task_is_reported(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        lines = _drift_lines(tmp_project)
        assert any(f"{meta.id} has 1 acceptance criterion" in l for l in lines), lines

    def test_test_task_quoting_a_dead_criterion_is_reported(self, store, tmp_project):
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        _set_criteria_on_disk(tmp_project, meta.id, ["Alpha criterion"])
        lines = _drift_lines(tmp_project)
        assert any(
            f"{meta.id} has 1 test task(s) quoting" in l for l in lines
        ), lines

    def test_an_edited_criterion_counts_as_a_dead_quote(self, store, tmp_project):
        """The body still quotes the pre-edit text, which is no longer a criterion."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Sessions expire after 30 minutes"],
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Sessions expire after 60 minutes"]
        )
        lines = _drift_lines(tmp_project)
        assert any("quoting an acceptance criterion" in l for l in lines), lines

    def test_the_finding_names_the_drifted_task(self, store, tmp_project):
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        _set_criteria_on_disk(tmp_project, meta.id, ["Alpha criterion"])
        clear_all_caches()
        drift = Store(tmp_project).detect_criteria_drift(meta.id)
        assert [e["task_id"] for e in drift["stale"]] == [f"{meta.id}-2"]


class TestSeverityIsWarning:
    def test_drift_never_raises_the_error_count(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        errors_before, _, _ = _counts(tmp_project)
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Wholly different replacement wording"]
        )
        errors_after, warnings_after, _ = _counts(tmp_project)
        assert errors_after == errors_before
        assert warnings_after >= 2

    def test_findings_are_tagged_warning_in_the_report(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        for line in _drift_lines(tmp_project):
            assert line.startswith("- [WARN]"), line


class TestCleanProjectsProduceNothing:
    def test_a_freshly_created_story_is_clean(self, store, tmp_project):
        store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        assert _drift_lines(tmp_project) == []

    def test_a_project_with_no_stories_is_clean(self, store, tmp_project):
        assert _drift_lines(tmp_project) == []

    def test_a_story_with_no_criteria_is_clean(self, store, tmp_project):
        store.create_story("S", "A story body long enough")
        assert _drift_lines(tmp_project) == []

    def test_a_story_with_no_criteria_and_manual_tasks_is_clean(
        self, store, tmp_project
    ):
        meta, _ = store.create_story("S", "A story body long enough")
        store.create_task(meta.id, "Build the thing", "Implementation work here")
        assert _drift_lines(tmp_project) == []

    def test_reconciled_criteria_are_clean(self, store, tmp_project):
        """What US-PM-5-5/5-6 leave behind must never be reported."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.update(
            meta.id,
            acceptance_criteria=["Alpha criterion revised", "Gamma criterion", "Delta"],
        )
        assert _drift_lines(tmp_project) == []

    def test_reconciling_the_drift_clears_the_finding(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        assert _drift_lines(tmp_project) != []
        clear_all_caches()
        fresh = Store(tmp_project)
        fresh.update(
            meta.id, acceptance_criteria=["Alpha criterion", "Beta criterion"]
        )
        assert _drift_lines(tmp_project) == []


class TestNoFalsePositives:
    def test_manual_tasks_are_not_mistaken_for_test_tasks(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        store.create_task(meta.id, "Test: something hand written", "I wrote this body")
        assert _drift_lines(tmp_project) == []

    def test_a_human_rewritten_test_task_body_is_not_reported_as_stale(
        self, store, tmp_project
    ):
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.update(f"{meta.id}-2", body="I own this task now, my own words")
        _set_criteria_on_disk(tmp_project, meta.id, ["Alpha criterion"])
        lines = _drift_lines(tmp_project)
        assert not any("quoting" in l for l in lines), lines

    def test_an_archived_test_task_does_not_make_its_criterion_look_untested(
        self, store, tmp_project
    ):
        """Retiring a test task is a decision; the audit must not nag about it."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.archive(f"{meta.id}-2")
        assert _drift_lines(tmp_project) == []

    def test_an_archived_orphan_is_not_reported_as_a_dead_quote(
        self, store, tmp_project
    ):
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.archive(f"{meta.id}-2")
        _set_criteria_on_disk(tmp_project, meta.id, ["Alpha criterion"])
        assert _drift_lines(tmp_project) == []

    def test_orphans_archived_by_the_5_6_policy_are_not_reported(
        self, store, tmp_project
    ):
        """The end state of a real pm_update removal must audit clean."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.update(meta.id, acceptance_criteria=["Alpha criterion"])
        assert store.last_criteria_reconciliation["archived_task_ids"] == [
            f"{meta.id}-2"
        ]
        assert _drift_lines(tmp_project) == []

    def test_a_flagged_orphan_is_reported_once_and_only_as_a_dead_quote(
        self, store, tmp_project
    ):
        """A flagged orphan stays active, so it legitimately still quotes dead text."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        store.update(f"{meta.id}-2", status="in-progress", assignee="ryan")
        store.update(meta.id, acceptance_criteria=["Alpha criterion"])
        lines = _drift_lines(tmp_project)
        assert len(lines) == 1
        assert "quoting" in lines[0]

    def test_an_archived_story_is_skipped(self, store, tmp_project):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        assert _drift_lines(tmp_project) != []
        clear_all_caches()
        Store(tmp_project).archive(meta.id)
        assert _drift_lines(tmp_project) == []

    def test_reordering_criteria_on_disk_is_not_drift(self, store, tmp_project):
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Beta criterion", "Alpha criterion"]
        )
        assert _drift_lines(tmp_project) == []


class TestAuditAgreesWithTheReconciler:
    """Requirement 1: reuse the matcher, never reimplement it."""

    @pytest.mark.parametrize(
        "before,after",
        [
            (["Alpha criterion"], ["Alpha criterion", "Beta criterion"]),
            (["Alpha criterion", "Beta criterion"], ["Alpha criterion"]),
            (["Sessions expire after 30 minutes"], ["Sessions expire after 60 minutes"]),
            (["Alpha criterion"], ["Wholly different replacement wording"]),
        ],
    )
    def test_missing_is_exactly_what_pm_update_would_create(
        self, store, tmp_project, before, after
    ):
        meta, _ = store.create_story("S", "A story body long enough", acceptance_criteria=before)
        _set_criteria_on_disk(tmp_project, meta.id, after)
        clear_all_caches()
        fresh = Store(tmp_project)
        drift = fresh.detect_criteria_drift(meta.id)
        plan = fresh.plan_criteria_reconciliation(meta.id, after)
        assert [e["criterion"] for e in drift["missing"]] == [
            e["criterion"] for e in plan["create"]
        ]

    def test_a_clean_story_yields_empty_buckets(self, store):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        assert store.detect_criteria_drift(meta.id) == {"missing": [], "stale": []}

    def test_detection_is_read_only(self, store, tmp_project):
        import hashlib

        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        _set_criteria_on_disk(tmp_project, meta.id, ["Alpha criterion"])
        clear_all_caches()
        fresh = Store(tmp_project)
        tasks_dir = tmp_project / ".project" / "tasks"

        def digest():
            h = hashlib.sha256()
            for p in sorted(tasks_dir.glob("*.md")):
                h.update(p.read_bytes())
            return h.hexdigest()

        before = digest()
        fresh.detect_criteria_drift(meta.id)
        assert digest() == before

    def test_an_unknown_story_id_is_empty_not_an_error(self, store):
        assert store.detect_criteria_drift("US-TST-99") == {"missing": [], "stale": []}


class TestThroughThePmAuditToolSurface:
    """US-PM-5-4 — the criterion, verified on the surface it names.

    Everything above drives ``run_audit`` (and, in two places,
    ``detect_criteria_drift``) directly.  The story's criterion is about
    ``pm_audit``, which is what /pm-orchestrate actually calls: the MCP tool in
    ``server.py`` that resolves the project root from the cwd, runs the audit,
    persists DRIFT.md, and hands the report back.  These tests go through that
    whole path so a regression anywhere along it — root resolution, the report
    the tool returns, or the file it leaves behind — is caught here.
    """

    ICONS = {"[ERROR]": "error", "[WARN]": "warning", "[INFO]": "info"}

    @pytest.fixture
    def audit(self, tmp_project, monkeypatch):
        """Call the real ``pm_audit`` MCP tool against ``tmp_project``."""
        import projectman.server as server

        monkeypatch.chdir(tmp_project)

        def run():
            clear_all_caches()
            server._store_cache.clear()
            return server.pm_audit()

        return run

    @classmethod
    def _findings(cls, report):
        """Parse the report into ``(severity, message)`` pairs.

        Severity comes from the icon, not from searching the whole report for
        the word "error" — the point of these assertions is the parsed field.
        """
        out = []
        for line in report.splitlines():
            if not line.startswith("- "):
                continue
            icon, _, message = line[2:].partition(" ")
            out.append((cls.ICONS[icon], message))
        return out

    @classmethod
    def _untested(cls, report, story_id):
        """Findings of the ``criteria-without-test-task`` check for one story."""
        return [
            (sev, msg)
            for sev, msg in cls._findings(report)
            if msg.startswith(f"Story {story_id} ") and "no test task" in msg
        ]

    @staticmethod
    def _counts(report):
        header = next(l for l in report.splitlines() if l.startswith("**Errors:**"))
        nums = [int(p) for p in header.replace("*", "").replace("|", " ").split() if p.isdigit()]
        return dict(zip(("errors", "warnings", "info"), nums))

    # -- positive -----------------------------------------------------------

    def test_pm_audit_reports_a_criterion_with_no_test_task(
        self, store, tmp_project, audit
    ):
        """The criterion itself: the finding exists, and it names the story."""
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        report = audit()
        found = self._untested(report, meta.id)
        assert len(found) == 1, report
        severity, message = found[0]
        assert severity == "warning"
        assert f"Story {meta.id} " in message
        assert "1 acceptance criterion/criteria with no test task" in message

    def test_the_finding_lands_in_drift_md_as_well_as_the_return_value(
        self, store, tmp_project, audit
    ):
        """DRIFT.md is the durable half of the surface; it must agree."""
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        report = audit()
        drift_md = (tmp_project / ".project" / "DRIFT.md").read_text()
        assert drift_md.rstrip("\n") == report.rstrip("\n")
        assert self._untested(drift_md, meta.id) == self._untested(report, meta.id)
        assert self._untested(drift_md, meta.id)

    def test_every_untested_criterion_is_counted(self, store, tmp_project, audit):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project,
            meta.id,
            ["Alpha criterion", "Beta criterion", "Gamma criterion", "Delta criterion"],
        )
        _, message = self._untested(audit(), meta.id)[0]
        assert "3 acceptance criterion/criteria with no test task" in message

    # -- negative -----------------------------------------------------------

    def test_a_fully_covered_story_produces_no_finding(self, store, tmp_project, audit):
        store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        report = audit()
        assert self._findings(report) == []
        assert "No issues found. Project is clean." in report

    def test_only_the_drifted_story_is_named(self, store, tmp_project, audit):
        """No collateral: a covered story sitting beside a drifted one is silent."""
        drifted, _ = store.create_story(
            "Drifted", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        covered, _ = store.create_story(
            "Covered",
            "A story body long enough",
            acceptance_criteria=["Gamma criterion", "Delta criterion"],
        )
        _set_criteria_on_disk(
            tmp_project, drifted.id, ["Alpha criterion", "Beta criterion"]
        )
        report = audit()
        assert len(self._untested(report, drifted.id)) == 1, report
        assert self._untested(report, covered.id) == []

    def test_an_archived_story_is_skipped_by_the_tool(self, store, tmp_project, audit):
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        assert self._untested(audit(), meta.id)
        clear_all_caches()
        Store(tmp_project).archive(meta.id)
        report = audit()
        assert self._untested(report, meta.id) == []
        assert (tmp_project / ".project" / "DRIFT.md").read_text().count("no test task") == 0

    # -- the original motivating bug ----------------------------------------

    def test_the_audit_no_longer_calls_the_motivating_drift_clean(
        self, store, tmp_project, audit
    ):
        """US-PM-5's second defect, reproduced through pm_audit.

        A story is created with criteria; the criteria are then edited without
        reconciliation — the state US-PM-1 and US-PM-2 were left in.  pm_audit
        answered "No issues found. Project is clean." for that state.  It must
        now name the story instead.
        """
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        before = audit()
        assert "No issues found. Project is clean." in before
        assert self._untested(before, meta.id) == []

        _set_criteria_on_disk(
            tmp_project,
            meta.id,
            ["Alpha criterion", "Beta criterion", "Gamma criterion"],
        )

        after = audit()
        assert "No issues found. Project is clean." not in after
        assert self._untested(after, meta.id), after
        assert self._counts(after)["warnings"] >= 1
        assert "Project is clean" not in (tmp_project / ".project" / "DRIFT.md").read_text()

    def test_reapplying_the_criteria_through_pm_update_returns_it_to_clean(
        self, store, tmp_project, audit
    ):
        """The remedy the finding's own message prescribes must work."""
        import projectman.server as server

        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Alpha criterion", "Beta criterion"]
        )
        assert self._untested(audit(), meta.id)
        server._store_cache.clear()
        clear_all_caches()
        server.pm_update(meta.id, acceptance_criteria="Alpha criterion,Beta criterion")
        report = audit()
        assert self._untested(report, meta.id) == []

    # -- severity -----------------------------------------------------------

    def test_the_finding_is_warning_and_never_error(self, store, tmp_project, audit):
        """/pm-orchestrate halts the run on any error-level finding.

        Asserted on the parsed severity and the header counts, not on a
        substring of the report: if this check is ever promoted to error, the
        orchestrator stops dead on a coverage gap.
        """
        meta, _ = store.create_story(
            "S", "A story body long enough", acceptance_criteria=["Alpha criterion"]
        )
        _set_criteria_on_disk(
            tmp_project,
            meta.id,
            ["Alpha criterion", "Beta criterion", "Gamma criterion"],
        )
        report = audit()
        findings = self._findings(report)
        counts = self._counts(report)

        assert {sev for sev, _ in self._untested(report, meta.id)} == {"warning"}
        assert counts["errors"] == 0
        assert [sev for sev, _ in findings].count("error") == 0
        assert counts["warnings"] == [sev for sev, _ in findings].count("warning")
        assert counts["warnings"] >= 1

    def test_drift_of_both_kinds_stays_out_of_the_error_count(
        self, store, tmp_project, audit
    ):
        """Missing *and* stale at once — still nothing the orchestrator halts on."""
        meta, _ = store.create_story(
            "S",
            "A story body long enough",
            acceptance_criteria=["Alpha criterion", "Beta criterion"],
        )
        errors_before = self._counts(audit())["errors"]
        _set_criteria_on_disk(
            tmp_project, meta.id, ["Wholly different wording", "Another new one"]
        )
        report = audit()
        severities = [sev for sev, msg in self._findings(report) if "criteri" in msg]
        assert set(severities) == {"warning"}
        assert self._counts(report)["errors"] == errors_before == 0


class TestTheRealDataCase:
    """The shape of the drift that was live in ProjectMan's own .project/.

    US-PM-1 and US-PM-2 were each created with a single semicolon-joined blob
    of a criterion, which was later split into four separate criteria.  Their
    one test task still quotes the blob; three of the four criteria have no
    test task at all.  pm_audit called this "clean".
    """

    BLOB = (
        "Tool failures raise a real MCP error rather than returning an error string "
        "body;is_error is set on every failure path;Distinguish expected-negative "
        "results from failures so pm_grab on a not-ready task is not an error;No tool "
        "returns a body beginning with error:;Test asserts is_error for each known "
        "failure class"
    )
    SPLIT = [
        "Tool failures raise a real MCP error rather than returning an error string body",
        "is_error is set on every failure path",
        "Expected-negative results are distinguished from failures so pm_grab on a not-ready task is not an error",
        "No tool returns a body beginning with the error prefix",
    ]

    @pytest.fixture
    def drifted(self, store, tmp_project):
        meta, _ = store.create_story(
            "S",
            "A story body long enough to pass the thin-description check easily",
            acceptance_criteria=[self.BLOB],
        )
        # The story is done, exactly as US-PM-2 is: done stories must still be
        # checked, or the real case would be invisible.
        store.update(meta.id, status="done")
        store.update(f"{meta.id}-1", status="done")
        _set_criteria_on_disk(tmp_project, meta.id, self.SPLIT)
        return meta.id

    def test_the_body_really_does_quote_the_dead_blob(self, drifted, tmp_project):
        clear_all_caches()
        _, body = Store(tmp_project).get_task(f"{drifted}-1")
        assert body == generate_test_task_body(drifted, self.BLOB)

    def test_three_criteria_are_reported_as_untested(self, drifted, tmp_project):
        lines = _drift_lines(tmp_project)
        assert any(
            f"{drifted} has 3 acceptance criterion/criteria with no test task" in l
            for l in lines
        ), lines

    def test_the_surviving_task_is_reported_as_quoting_dead_text(
        self, drifted, tmp_project
    ):
        lines = _drift_lines(tmp_project)
        assert any(
            f"{drifted} has 1 test task(s) quoting" in l for l in lines
        ), lines

    def test_the_audit_no_longer_calls_it_clean(self, drifted, tmp_project):
        report = "\n".join(_audit_lines(tmp_project))
        assert "No issues found. Project is clean." not in report
        errors, warnings, _ = _counts(tmp_project)
        assert errors == 0
        assert warnings >= 2

    def test_reapplying_the_criteria_repairs_it(self, drifted, tmp_project):
        clear_all_caches()
        Store(tmp_project).update(drifted, acceptance_criteria=self.SPLIT)
        assert _drift_lines(tmp_project) == []
