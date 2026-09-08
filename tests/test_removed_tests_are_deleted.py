"""US-PM-27-5 — the tests for the removed features are *deleted*, not skipped.

US-PM-27's last acceptance criterion is "Full unit suite passes with the
removed tests deleted rather than skipped".  Both halves matter.  A suite can
be made green for a subtraction in two ways: delete the tests that covered the
deleted code, or leave them in place behind ``@pytest.mark.skip`` /
``pytest.importorskip`` and let them rot.  The second way still passes CI while
carrying every line of the dead feature's test code, plus the standing
temptation to "unskip it later" — which is exactly the tax the story set out to
stop paying.

So this file pins the shape of the removal rather than its behaviour:

1. none of the nine deleted test modules is back on disk;
2. no test module under ``tests/`` carries a skip/xfail whose reason (or
   whose condition) talks about the removed features — i.e. nothing was
   quietly parked instead of deleted;
3. the removed public names (``create_pr``, ``get_pr_status``,
   ``update_hub_refs``, ``create_feature_branch``, ``pm_changeset_*``)
   survive under ``tests/`` only inside the handful of files whose whole job
   is to assert those names are gone.

Point 2 is checked against the parsed source, not a line grep: every call to a
skipping API is located with :mod:`ast` and the *whole call* — condition and
reason both — is read back out of the source.  A grep for ``reason=`` would
miss ``pytest.skip("...")`` inside a function body and would misread a reason
that spans lines.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1. the nine modules deleted by US-PM-27-6 / -7 / -8
# ---------------------------------------------------------------------------

DELETED_TEST_FILES = (
    "test_changeset.py",
    "test_changeset_pr_commands.py",
    "test_hub_ref_update_after_merge.py",
    "test_pr_workflow_integration.py",
    "test_simultaneous_prs.py",
    "test_hub_pr_workflow.py",
    "test_update_hub_refs_after_merge.py",
    "test_create_feature_branch.py",
    "test_create_pr.py",
)

# ---------------------------------------------------------------------------
# 2. vocabulary of the removed features
# ---------------------------------------------------------------------------
#
# ``PR`` is matched case-sensitively and on word boundaries on purpose: a
# case-insensitive substring test flags "PROJECTMAN_SKIP_BENCH" and every
# "reproduce"/"approach" in a reason string, which would make this test a
# nuisance rather than a guard.

FEATURE_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("changeset", re.compile(r"changeset", re.IGNORECASE)),
    ("PR", re.compile(r"\bPRs?\b")),
    ("pull request", re.compile(r"pull[-\s]?requests?", re.IGNORECASE)),
    ("feature branch", re.compile(r"feature[-\s_]?branch", re.IGNORECASE)),
    ("hub ref", re.compile(r"hub[-\s_]?refs?", re.IGNORECASE)),
    ("subtraction", re.compile(r"subtraction", re.IGNORECASE)),
)

# ---------------------------------------------------------------------------
# 3. the removed public names, and the only files allowed to name them
# ---------------------------------------------------------------------------
#
# ``\bcreate_pr\b`` rather than a bare substring: "create_pr" is a prefix of
# "create_project", which is very much still a thing.  ``update_hub_refs`` is
# deliberately open-ended so it also catches ``update_hub_refs_after_merge``.

REMOVED_NAMES = re.compile(
    r"\bcreate_pr\b"
    r"|\bget_pr_status\b"
    r"|\bupdate_hub_refs"
    r"|\bcreate_feature_branch\b"
    r"|\bpm_changeset_"
)

# ``test_hub_pr_workflow_removed.py`` was on this list until EPIC-PM-6: it
# pinned the absence of those names inside ``hub/registry.py``, and the whole
# hub package is gone now (US-PM-46), so the file went with it.
NAME_ALLOWLIST = frozenset(
    {
        "test_changesets_removed.py",
        "test_docs_after_subtraction.py",
        "test_removed_tests_are_deleted.py",
    }
)

# ``pytest.mark.skip`` is a prefix of ``pytest.mark.skipif``; both are covered.
SKIPPING_CALLS = ("skip", "skipif", "xfail", "importorskip")


def _test_modules() -> list[Path]:
    """Every Python module under ``tests/``, including ``tests/integration``.

    The integration directory is excluded from the unit run for environment
    reasons, not because its content is exempt from the subtraction — a
    parked changeset test hiding there would be just as much of a lie.
    """
    return sorted(
        p
        for p in TESTS_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _relative(path: Path) -> str:
    return path.relative_to(TESTS_DIR).as_posix()


def _dotted(node: ast.AST) -> str:
    """Render ``pytest.mark.skipif`` (an Attribute chain) back to a string."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _skip_call_sources(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(lineno, dotted_name, source_of_the_whole_call)`` per skip."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if not dotted:
            continue
        tail = dotted.rsplit(".", 1)[-1]
        if tail not in SKIPPING_CALLS:
            continue
        # ``pytest.skip``/``pytest.mark.skipif``/``pytest.importorskip`` and
        # the aliases people bind them to (``_skip_no_numpy = ...``) all end
        # in one of those four attribute names.
        segment = ast.get_source_segment(source, node) or ""
        found.append((node.lineno, dotted, segment))
    return found


# ---------------------------------------------------------------------------
# criterion 1 — the files are gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", DELETED_TEST_FILES)
def test_the_deleted_test_module_is_not_on_disk(filename):
    """Each of the nine modules US-PM-27 removed stays removed."""
    assert not (TESTS_DIR / filename).exists(), (
        f"tests/{filename} is back; US-PM-27 deleted it along with the code "
        f"it covered"
    )


def test_no_deleted_module_reappears_anywhere_under_tests():
    """Also catches a module moved into a subdirectory instead of deleted."""
    revived = sorted(
        _relative(p)
        for p in _test_modules()
        if p.name in DELETED_TEST_FILES
    )
    assert revived == [], f"deleted test modules found under tests/: {revived}"


# ---------------------------------------------------------------------------
# criterion 2 — nothing was skipped instead of deleted
# ---------------------------------------------------------------------------


def test_no_skip_or_xfail_reason_mentions_a_removed_feature():
    """A skip that names the removed features is a deletion left half-done."""
    offenders: list[str] = []
    for path in _test_modules():
        for lineno, dotted, segment in _skip_call_sources(path):
            hit = [label for label, rx in FEATURE_WORDS if rx.search(segment)]
            if hit:
                one_line = " ".join(segment.split())
                offenders.append(
                    f"{_relative(path)}:{lineno} {dotted} mentions {hit}: "
                    f"{one_line[:160]}"
                )
    assert offenders == [], (
        "skips/xfails referring to the removed features (delete the test "
        "instead of parking it):\n" + "\n".join(offenders)
    )


def test_the_skip_scanner_actually_finds_the_skips_that_do_exist():
    """Guard the guard: a scanner that finds nothing proves nothing.

    The suite legitimately skips for missing optional dependencies and for
    benchmarks, so the AST walk above must come back non-empty — otherwise
    the test above would pass just as happily on a broken parser.
    """
    total = sum(len(_skip_call_sources(p)) for p in _test_modules())
    assert total > 0, "found no skip/xfail calls at all — scanner is broken"


# ---------------------------------------------------------------------------
# criterion 3 — the removed names survive only where their absence is pinned
# ---------------------------------------------------------------------------


def test_removed_names_appear_only_in_the_files_that_pin_their_absence():
    offenders: list[str] = []
    for path in _test_modules():
        if path.name in NAME_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        names = sorted({m.group(0) for m in REMOVED_NAMES.finditer(text)})
        if names:
            offenders.append(f"{_relative(path)}: {names}")
    assert offenders == [], (
        "removed function names still referenced outside the "
        "absence-pinning tests:\n" + "\n".join(offenders)
    )


def test_the_name_scanner_matches_where_the_absence_is_pinned():
    """Guard the guard, again: the regex must still match real occurrences."""
    pinned = TESTS_DIR / "test_docs_after_subtraction.py"
    assert pinned.exists(), "the docs-subtraction pin test is missing"
    text = pinned.read_text(encoding="utf-8")
    assert REMOVED_NAMES.search(text), (
        "the removed-name regex matches nothing in the file that exists to "
        "name those functions — the scan above is vacuous"
    )


def test_create_project_is_not_mistaken_for_create_pr():
    """The word-boundary in ``\\bcreate_pr\\b`` is load-bearing."""
    assert REMOVED_NAMES.search("registry.create_project(name)") is None
    assert REMOVED_NAMES.search("registry.create_pr(name)") is not None
