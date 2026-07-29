"""US-PM-4-2 — the determination "the CHECK was at fault, not the templates" as
executable fact rather than prose.

US-PM-4-5 produced ``docs/reference/readiness-warnings-determination.md``,
which concluded that the three always-on readiness warnings ("no Implementation
section in description", "no Testing section in description", "no Definition of
Done checklist") had to go because **the check** was wrong, not because the
templates were.  US-PM-4-6 acted on it: the warnings were deleted from
``readiness.py`` and the dead ``templates/task.md.j2`` was removed.

``test_readiness_warnings_suppressed.py`` locks the *outcome* (the strings are
gone, no warning has a 100% hit rate, the payload shrank).  It does not lock the
*reasoning*, which is what makes the outcome correct rather than merely
convenient.  This module does, on four fronts:

1. **No generator produces the demanded structure.**  ``create_task`` /
   ``create_tasks`` write the caller's description verbatim — asserted
   byte-for-byte, and structurally via AST so that a wrapper cannot be slipped
   in.  ``pm_create_story``'s auto-generated test tasks emit a fixed three-line
   body.  The scoper prescribes prose.
2. **No remaining template produces it either.**  Every ``.j2`` under
   ``src/projectman/templates/`` is enumerated *from the directory*, so a NEW
   template carrying the demanded structure fails these tests rather than
   sliding in under a hardcoded list.
3. **The two check bugs the determination found**, pinned as
   documentation-of-why-removed.  The check itself is gone, so these exercise a
   local reconstruction of the deleted predicate: they record *why* it must not
   come back and would have to be consciously deleted to reverse the reasoning.
4. **The determination document survives.**  Deleting it fails a test.

Together these mean the conclusion cannot be quietly reversed: reinstating the
check requires first inventing a producer for the layout it demands, and that
producer would trip these tests.
"""

import ast
import inspect
from pathlib import Path

import pytest


# ─── The three structures the deleted check demanded ─────────────────

# (marker, case_sensitive).  Semantics copied from the deleted
# readiness.py:53-59 — the two headings were matched against a lowered body,
# the checklist against the raw body.
DEMANDED = (
    ("## implementation", False),
    ("## testing", False),
    ("- [ ]", True),
)

DELETED_WARNINGS = (
    "no Implementation section in description",
    "no Testing section in description",
    "no Definition of Done checklist",
)

# A body in the prose form ProjectMan's scoper actually asks for.
PROSE_BODY = (
    "Add the login endpoint to the API router: a POST /login handler that "
    "accepts email and password, validates credentials against the user "
    "store, and returns a signed JWT. Touches api/routes.py and auth/jwt.py."
)

# A body carrying the full demanded layout.  Used to prove create_task is a
# pass-through in BOTH directions: it neither adds the structure nor strips it.
STRUCTURED_BODY = (
    "## Implementation\n\nAdd the handler to the router.\n\n"
    "## Testing\n\nRun pytest tests/test_auth.py.\n\n"
    "## Definition of Done\n\n- [ ] Endpoint works\n- [ ] Tests pass"
)


def _demanded_markers_in(text: str) -> list[str]:
    """Which of the three demanded structures appear in *text*."""
    lowered = text.lower()
    return [
        marker
        for marker, case_sensitive in DEMANDED
        if (marker in text if case_sensitive else marker in lowered)
    ]


def _package_root() -> Path:
    import projectman

    return Path(projectman.__file__).parent


def _templates_dir() -> Path:
    return _package_root() / "templates"


def _stored_body(store, task_id: str) -> str:
    """The task body as it landed on disk, read back through the file."""
    import frontmatter

    path = store.tasks_dir / f"{task_id}.md"
    return frontmatter.loads(path.read_text()).content


@pytest.fixture
def built_store(tmp_project):
    """A Store with one active story, ready for task creation."""
    from projectman.store import Store, _cache

    _cache.clear()
    store = Store(tmp_project)
    store.create_story("Story", "A story description that is long enough.")
    store.update("US-TST-1", status="active")
    return store


# ═══════════════════════════════════════════════════════════════════════
# 1. No generator produces the demanded structure
# ═══════════════════════════════════════════════════════════════════════


class TestNoGeneratorEmitsTheDemandedStructure:
    """The determination's core claim: the check had no conforming producer.

    If any of these fail, the determination is wrong — some generator *does*
    emit the layout, and the template half of the question reopens.
    """

    @pytest.mark.parametrize(
        "description",
        [
            PROSE_BODY,
            STRUCTURED_BODY,
            "Do the thing.",
            "Body with trailing marker chars: ## Impl, - [x] done",
        ],
        ids=["prose", "structured", "thin", "near-miss"],
    )
    def test_create_task_writes_the_description_byte_for_byte(
        self, built_store, description
    ):
        """Nothing is prepended, appended, wrapped, or templated.

        The assertion is exact equality against what came back off disk, so a
        single injected heading or checkbox line fails it.
        """
        built_store.create_task("US-TST-1", "T", description, points=2)

        on_disk = _stored_body(built_store, "US-TST-1-1")
        assert on_disk == description, (
            "create_task did not write the caller's description verbatim; "
            f"delta={on_disk[len(description):]!r} / {description[len(on_disk):]!r}"
        )

        # Belt and braces: identical through the read API too, and no growth.
        _, via_api = built_store.get_task("US-TST-1-1")
        assert via_api == description
        assert len(on_disk) == len(description)

    def test_create_task_adds_none_of_the_three_to_a_prose_body(self, built_store):
        """The 0-of-118 result on real task files, reproduced from the API."""
        built_store.create_task("US-TST-1", "T", PROSE_BODY, points=2)
        body = _stored_body(built_store, "US-TST-1-1")

        assert _demanded_markers_in(PROSE_BODY) == []
        assert _demanded_markers_in(body) == [], (
            "create_task injected a demanded structure into a prose body — "
            "a template is in the task-creation path after all"
        )

    def test_create_task_does_not_strip_them_either(self, built_store):
        """Pass-through, not a filter: what the caller writes is what lands.

        This is the other half of "verbatim" — the absence in the prose case
        is the caller's doing, not a transformation by the store.
        """
        built_store.create_task("US-TST-1", "T", STRUCTURED_BODY, points=2)
        body = _stored_body(built_store, "US-TST-1-1")

        assert sorted(_demanded_markers_in(body)) == sorted(
            marker for marker, _ in DEMANDED
        )
        assert body == STRUCTURED_BODY

    def test_create_tasks_batch_writes_every_description_byte_for_byte(
        self, built_store
    ):
        """The batch path is the same verbatim write, per entry."""
        descriptions = [PROSE_BODY, STRUCTURED_BODY, "Short one.", ""]
        built_store.create_tasks(
            "US-TST-1",
            [
                {"title": f"T{i}", "description": d, "points": 2}
                for i, d in enumerate(descriptions)
            ],
        )

        for i, expected in enumerate(descriptions):
            task_id = f"US-TST-1-{i + 1}"
            assert _stored_body(built_store, task_id) == expected, task_id

        # And the batch invents nothing for the prose entries.
        assert _demanded_markers_in(_stored_body(built_store, "US-TST-1-1")) == []
        assert _demanded_markers_in(_stored_body(built_store, "US-TST-1-4")) == []

    def test_auto_generated_test_tasks_emit_the_known_three_line_body(
        self, tmp_project
    ):
        """``pm_create_story``'s per-criterion tasks are structurally incapable
        of satisfying the deleted check: the body is a hardcoded f-string with
        no headings and no checklist, so the check fired on 100% of them by
        construction.
        """
        from projectman.store import Store, _cache

        _cache.clear()
        store = Store(tmp_project)
        criteria = ["Users can log in", "Error shown on invalid password"]
        _, test_tasks = store.create_story(
            "Story", "A story description that is long enough.", acceptance_criteria=criteria
        )

        assert len(test_tasks) == len(criteria)
        for task, criterion in zip(test_tasks, criteria):
            body = _stored_body(store, task.id)
            assert body == (
                f"Verify acceptance criterion for story US-TST-1:\n\n> {criterion}"
            )
            assert body.count("\n") == 2, "no longer a three-line body"
            assert _demanded_markers_in(body) == []

    def test_the_scoper_prescribes_prose_not_headings(self, built_store):
        """``pm_scope`` guidance asks for semantic content, not structure.

        The determination's point 2: the design deliberately went the other
        way.  If the guidance ever grew a ``## Implementation`` prescription
        the determination would need revisiting — so it is asserted, not
        assumed.
        """
        import yaml

        from projectman.scoper import scope

        payload = scope(built_store, "US-TST-1")
        assert _demanded_markers_in(payload) == [], (
            "the scoper now prescribes the layout the deleted check demanded"
        )

        guidance = yaml.safe_load(payload)["decomposition_guidance"]
        description_guidance = guidance["task_template"]["description"]
        assert "##" not in description_guidance
        assert "[ ]" not in description_guidance
        # It asks for content, not shape.
        assert "acceptance criteria" in description_guidance.lower()

    def test_auto_scope_guidance_prescribes_prose_too(self, built_store):
        """The other scoping surface, same property."""
        from projectman.scoper import auto_scope

        payload = auto_scope(built_store)
        assert _demanded_markers_in(payload) == []

    def test_the_task_writers_use_no_templating_at_all(self):
        """Structural proof that "verbatim" is not an accident of the sample.

        ``content=`` on the ``frontmatter.Post`` must be the description
        expression itself — a bare name, or the batch entry lookup.  A
        concatenation, an f-string, or a ``render(...)`` call there is exactly
        how boilerplate would get prepended, and each fails this test.
        """
        from projectman.store import Store

        for func in (Store.create_task, Store.create_tasks):
            source = inspect.getsource(func)
            tree = ast.parse(inspect.cleandoc(source).replace("\ndef ", "\ndef ", 1))

            posts = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Post"
            ]
            assert posts, f"{func.__qualname__}: no frontmatter.Post call found"

            for post in posts:
                content = [kw for kw in post.keywords if kw.arg == "content"]
                assert content, f"{func.__qualname__}: Post has no content= kwarg"
                expr = content[0].value
                assert not isinstance(expr, (ast.BinOp, ast.JoinedStr)), (
                    f"{func.__qualname__}: task body is built by concatenation "
                    f"or interpolation — {ast.unparse(expr)}"
                )
                assert isinstance(expr, (ast.Name, ast.Call)), (
                    f"{func.__qualname__}: unexpected body expression "
                    f"{ast.unparse(expr)}"
                )
                if isinstance(expr, ast.Call):
                    # Only the batch's ``entry.get("description", "")`` lookup.
                    assert ast.unparse(expr.func).endswith(".get"), ast.unparse(expr)

            # No Jinja anywhere near the task writers.
            for forbidden in (".j2", "render(", "get_template", "Environment("):
                assert forbidden not in source, (
                    f"{func.__qualname__} now touches templating: {forbidden}"
                )


# ═══════════════════════════════════════════════════════════════════════
# 2. No remaining template emits the demanded structure into a task body
# ═══════════════════════════════════════════════════════════════════════
#
# The list is derived from the directory, never hardcoded, so a new template
# carrying `## Implementation` / `## Testing` / `- [ ]` fails on arrival.
#
# Three templates legitimately carry a marker and are NOT task producers.
# Each is allowlisted with the reason; the allowlist is itself asserted to be
# neither stale nor over-broad.

NON_TASK_TEMPLATES_WITH_MARKERS = {
    # name: (destination document, why the marker is fine there)
    "epic.md.j2": "EPIC-*.md — epic-level success-criteria checkboxes",
    "story.md.j2": "US-*.md — story-level acceptance-criteria checkboxes",
    "architecture_hub.md.j2": "ARCHITECTURE.md — a '## Testing' prose section",
}


def _all_templates() -> list[Path]:
    return sorted(_templates_dir().glob("*.j2"))


def _is_task_path(expr: str) -> bool:
    """Does a path expression address a ``.project/tasks/*.md`` file?"""
    return "_task_path" in expr or "tasks_dir" in expr


def _write_targets(source: str) -> list[str]:
    """Receiver expressions of every ``X.write_text(...)`` / ``X.write(...)``."""
    targets = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("write_text", "write_bytes")
        ):
            targets.append(ast.unparse(node.func.value))
    return targets


class TestNoTemplateEmitsTheDemandedStructure:
    def test_the_template_directory_is_enumerable(self):
        """Anti-vacuity: the scans below must actually see templates."""
        templates = _all_templates()
        assert len(templates) >= 20, (
            f"only {len(templates)} templates found — the glob is wrong and "
            "every scan in this class is passing vacuously"
        )

    def test_the_dead_task_template_stays_deleted(self):
        """``task.md.j2`` was the sole definition of the demanded layout."""
        assert not (_templates_dir() / "task.md.j2").exists()
        # And no successor by another name defines it either — see below.

    def test_no_unexpected_template_carries_the_demanded_structure(self):
        """Derived from the directory: a NEW offending template fails here.

        This is the guard that keeps ``task.md.j2``'s deletion meaningful.
        Re-adding that layout under any filename lands it outside the
        allowlist and fails.
        """
        offenders = {
            path.name: _demanded_markers_in(path.read_text())
            for path in _all_templates()
        }
        offenders = {name: found for name, found in offenders.items() if found}

        unexpected = {
            name: found
            for name, found in offenders.items()
            if name not in NON_TASK_TEMPLATES_WITH_MARKERS
        }
        assert unexpected == {}, (
            "template(s) now emit the layout the deleted readiness check "
            "demanded. If one of these renders into a TASK body, US-PM-4-5's "
            "determination is invalidated and must be revisited; if it renders "
            "into an epic/story/doc, add it to "
            f"NON_TASK_TEMPLATES_WITH_MARKERS with the reason: {unexpected}"
        )

    def test_the_allowlist_is_not_stale(self):
        """Every allowlisted template still exists and still needs the waiver.

        Prevents the allowlist from silently growing into a blanket exemption.
        """
        for name in NON_TASK_TEMPLATES_WITH_MARKERS:
            path = _templates_dir() / name
            assert path.exists(), f"allowlisted template {name} no longer exists"
            assert _demanded_markers_in(path.read_text()), (
                f"{name} no longer contains any demanded marker — drop its "
                "allowlist entry rather than leaving a blanket exemption"
            )

    def test_no_template_is_rendered_into_a_task_body(self):
        """The allowlisted markers cannot reach a task, because *nothing*
        templated can: no module that touches Jinja also creates tasks.

        Task files are written in exactly one place (``Store.create_task`` /
        ``create_tasks``), and ``store.py`` has no templating.  Conversely the
        two Jinja render sites (``cli.py``, ``hub/registry.py``) never create
        tasks.  Wiring a template into task creation would break one side or
        the other.
        """
        package = _package_root()
        sources = {
            path.relative_to(package).as_posix(): path.read_text()
            for path in package.rglob("*.py")
        }

        templating = {
            name
            for name, src in sources.items()
            if "get_template" in src or "jinja2" in src
        }
        assert templating, "no Jinja site found — this guard is dead"

        for name in sorted(templating):
            src = sources[name]
            assert "create_task" not in src, (
                f"{name} both renders templates and creates tasks — a template "
                "can now reach a task body, which invalidates US-PM-4-5"
            )
            for target in _write_targets(src):
                assert not _is_task_path(target), (
                    f"{name} renders templates and writes to {target} — a "
                    "template may now land in a task file"
                )

        store_src = sources["store.py"]
        assert "create_task" in store_src, "store.py is no longer the task writer"
        assert store_src.count(".j2") == 0, "store.py now references a template"
        assert "jinja" not in store_src.lower()

        # And task files are written from store.py alone.
        writers = {
            name
            for name, src in sources.items()
            if any(_is_task_path(t) for t in _write_targets(src))
        }
        assert writers == {"store.py"}, (
            f"task files are written outside store.py: {sorted(writers)}"
        )

    def test_every_rendered_template_targets_a_non_task_document(self):
        """The render sites write project docs, skills and agents — never tasks.

        Complements the module-level split above by checking the destinations
        rather than the module boundaries.
        """
        package = _package_root()
        rendered: set[str] = set()
        for path in package.rglob("*.py"):
            src = path.read_text()
            if "get_template" not in src:
                continue
            for node in ast.walk(ast.parse(src)):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.endswith(".j2")
                ):
                    rendered.add(node.value)

        assert rendered, "no rendered template names found — guard is dead"
        assert "task.md.j2" not in rendered
        # None of the marker-carrying templates is on a render path that could
        # produce a task; assert directly that no rendered template's markers
        # are unaccounted for.
        for name in sorted(rendered):
            path = _templates_dir() / name
            if not path.exists():
                continue
            found = _demanded_markers_in(path.read_text())
            assert not found or name in NON_TASK_TEMPLATES_WITH_MARKERS, (
                f"{name} is rendered and carries {found}"
            )


# ═══════════════════════════════════════════════════════════════════════
# 3. Why the check was removed — the two defects, pinned
# ═══════════════════════════════════════════════════════════════════════
#
# These are NOT tests of live behaviour: the check is deleted and
# ``test_readiness_source_has_no_body_structure_checks`` keeps it that way.
# They exercise a local reconstruction of the deleted predicate so the two
# defects that justified deletion stay on the record as executable facts.
# Reversing the determination means deleting these tests deliberately.


def _deleted_check(task_body: str) -> list[str]:
    """Verbatim reconstruction of the removed ``readiness.py:53-59``.

    Kept here — and nowhere in ``src/`` — precisely because it must not ship.
    """
    warnings = []
    body_lower = task_body.lower()
    if "## implementation" not in body_lower:
        warnings.append("no Implementation section in description")
    if "## testing" not in body_lower:
        warnings.append("no Testing section in description")
    if "- [ ]" not in task_body:
        warnings.append("no Definition of Done checklist")
    return warnings


class TestWhyTheCheckWasRemoved:
    """Documentation-of-why-removed. The check itself no longer exists."""

    def test_the_reconstruction_matches_the_recorded_predicate(self):
        """Guard against this reconstruction drifting from the determination.

        If the doc's quoted source and the function above disagree, the two
        defects below stop being evidence about the real check.
        """
        doc = _determination_text()
        for line in (
            'if "## implementation" not in body_lower:',
            'if "## testing" not in body_lower:',
            'if "- [ ]" not in task_body:',
        ):
            assert line in doc, f"determination no longer records: {line}"
        for warning in DELETED_WARNINGS:
            assert warning in doc

    def test_bug_one_a_completed_definition_of_done_still_warned(self):
        """A task whose DoD is fully ticked off was reported as having none.

        ``- [x]`` does not contain ``- [ ]``, so *finishing* the checklist made
        the warning appear.  The check punished completion.
        """
        completed = (
            "Ship the login endpoint and verify it end to end.\n\n"
            "## Definition of Done\n\n- [x] Endpoint works\n- [x] Tests pass\n"
        )
        assert "no Definition of Done checklist" in _deleted_check(completed), (
            "the completed-DoD defect no longer reproduces — if the check is "
            "being reinstated, this is one of the two reasons it must not be"
        )

        # The same body with the boxes unticked passes — proving the warning
        # tracked tick-state, not the presence of a checklist.
        open_dod = completed.replace("- [x]", "- [ ]")
        assert "no Definition of Done checklist" not in _deleted_check(open_dod)

    def test_bug_two_naive_substring_matching_on_headings(self):
        """``## Tests`` failed while ``### Implementation`` passed.

        Raw substring matching with no notion of markdown: it could not
        enforce a heading level (``## `` is a substring of ``### ``) yet
        rejected any synonym of the exact word it wanted.
        """
        assert "no Testing section in description" in _deleted_check(
            "## Tests\n\nRun pytest."
        ), "the ## Tests defect no longer reproduces"
        assert "no Testing section in description" in _deleted_check(
            "## Test Plan\n\nRun pytest."
        )

        # Wrong heading level, accepted anyway.
        assert "no Implementation section in description" not in _deleted_check(
            "### Implementation\n\nDo it."
        ), "the heading-level defect no longer reproduces"
        assert "no Implementation section in description" not in _deleted_check(
            "#### Implementation\n\nDo it."
        )

        # ...while a bolded or two-spaced variant was rejected.
        assert "no Implementation section in description" in _deleted_check(
            "**Implementation**\n\nDo it."
        )

    def test_the_check_would_fire_on_everything_this_repo_generates(self):
        """The 100% hit rate, derived rather than quoted.

        Every body a ProjectMan generator actually produces trips all three.
        That is the determination in one assertion: the check demanded a
        layout with no producer.
        """
        generated_bodies = [
            PROSE_BODY,
            "Verify acceptance criterion for story US-TST-1:\n\n> Users can log in",
            "Do the thing.",
            "",
        ]
        for body in generated_bodies:
            assert _deleted_check(body) == list(DELETED_WARNINGS), (
                f"expected all three warnings on a generated body: {body!r}"
            )

    def test_the_reconstruction_does_not_ship(self):
        """The predicate lives only in this test module, never in ``src/``."""
        package = _package_root()
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text())
            literals = {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            for warning in DELETED_WARNINGS:
                assert warning not in literals, (
                    f"{path.relative_to(package)} reintroduces {warning!r}"
                )


# ═══════════════════════════════════════════════════════════════════════
# 4. The determination document itself
# ═══════════════════════════════════════════════════════════════════════

DETERMINATION_DOC = Path("docs/reference/readiness-warnings-determination.md")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _determination_text() -> str:
    path = _repo_root() / DETERMINATION_DOC
    assert path.exists(), (
        f"{DETERMINATION_DOC} is missing — US-PM-4-5's determination is the "
        "only record of why the warnings were deleted rather than the "
        "templates fixed. Do not remove it."
    )
    return path.read_text()


class TestDeterminationIsOnTheRecord:
    def test_the_document_exists(self):
        assert (_repo_root() / DETERMINATION_DOC).is_file()

    def test_it_states_the_conclusion(self):
        """Not just present — still saying the check was at fault."""
        doc = _determination_text()
        assert "the **CHECK** is at fault" in doc, (
            "the determination no longer states its verdict; if the verdict "
            "genuinely changed, US-PM-4-6's deletion needs revisiting"
        )
        assert "task.md.j2" in doc and "dead code" in doc
        assert "US-PM-4-6" in doc

    def test_it_records_the_two_defects_pinned_above(self):
        doc = _determination_text()
        assert "fully completed (`- [x]`) is reported as having no Definition" in doc
        assert "`## Tests`" in doc

    def test_the_source_comment_points_at_it(self):
        """``readiness.py`` links the reasoning, so the next reader finds it."""
        source = inspect.getsource(_readiness_module())
        assert DETERMINATION_DOC.as_posix() in source, (
            "readiness.py no longer references the determination — the "
            "reasoning becomes orphaned and easy to reverse by accident"
        )
        assert "Do not reinstate" in source


def _readiness_module():
    from projectman import readiness

    return readiness
