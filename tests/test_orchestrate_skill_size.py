"""US-PM-25-1 — the pm-orchestrate skill must stay small enough to be read.

Story US-PM-25's acceptance criterion was a number: the rendered pm-orchestrate
skill was pinned at 9000 characters by US-PM-25, and raised to 10000 by
US-PM-53 (two-lane dispatch) on 2026-09-09 by user decision, because the
isolation model (US-PM-51) and the lanes did not fit in 9 KB.  The skill is
loaded into an orchestrating agent's context on every dispatch, so its length
is a per-run tax; before US-PM-25-6 the template was 31,731 bytes of mostly
rationale.

The size is pinned here on the *rendered* text rather than the template file,
because rendering is what the agent actually sees, and the tracked copy under
``.claude/skills/`` is asserted to be that same text — a template edit that
skips ``refresh-skills`` is caught rather than silently shipped.

The last test is a falsification guard: the pre-rewrite template, read straight
out of the pinned commit below and pushed through the very same renderer, is
asserted to be *rejected*.  A size check that never fires is not evidence, and this one is
shown to bite.
"""

import subprocess
from pathlib import Path

import pytest

import projectman
from projectman.cli import _render_template

# Pinned at 9000 by US-PM-25; raised to 10000 by US-PM-53 (two-lane dispatch)
# on 2026-09-09 by user decision, because the isolation model (US-PM-51) and
# the lanes did not fit in 9 KB.
MAX_CHARS = 10000

TEMPLATE_NAME = "skill_pm_orchestrate.md.j2"
TEMPLATE_REPO_PATH = f"src/projectman/templates/{TEMPLATE_NAME}"

#: the last commit before the US-PM-25-6 rewrite, holding the 31,731-byte
#: pre-rewrite template.  It is a SHA and not ``HEAD`` on purpose: since the
#: rewrite landed, ``HEAD`` carries the ~9,000-byte shortened template, which
#: is *inside* the budget and would make this falsification guard vacuous.
#: This history is post-rewrite, so the SHA is stable.
PRE_REWRITE_COMMIT = "1061084"

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERED_SKILLS = REPO_ROOT / ".claude" / "skills"
ORCHESTRATE_SKILL = RENDERED_SKILLS / "pm-orchestrate" / "SKILL.md"

DESIGN_DOC_LINK = "orchestrate-design.md"

#: the reference doc the rationale moved into (US-PM-25-6).  Sibling modules
#: import this and ``design_section`` to re-target assertions that used to pin
#: rationale prose inside the skill itself.
DESIGN_DOC = REPO_ROOT / "docs" / "reference" / DESIGN_DOC_LINK


def design_section(heading: str) -> str:
    """The block under a ``## `` heading of the design doc.

    The rationale the skill no longer carries has to be *somewhere*: a test
    that simply dropped its assertion would let the reasoning disappear.
    """
    lines = DESIGN_DOC.read_text(encoding="utf-8").splitlines()
    starts = [n for n, line in enumerate(lines) if line.strip() == heading]
    assert starts, (
        f"{DESIGN_DOC} has no {heading!r} section — the rationale moved out of "
        "the skill by US-PM-25-6 and this is where it must live"
    )
    start = starts[0]
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _within_limit(text: str) -> bool:
    """The criterion itself, as one function both the test and guard call."""
    return len(text) <= MAX_CHARS


def _render_orchestrate() -> str:
    return _render_template(TEMPLATE_NAME)


def test_rendered_orchestrate_skill_is_within_the_size_budget():
    """At most ``MAX_CHARS``: 9000 by US-PM-25, 10000 since US-PM-53."""
    rendered = _render_orchestrate()
    assert _within_limit(rendered), (
        f"rendered {TEMPLATE_NAME} is {len(rendered)} characters, "
        f"{len(rendered) - MAX_CHARS} over the {MAX_CHARS}-character budget"
    )


def test_tracked_rendered_skill_matches_the_template():
    """Editing the template without refreshing the skill is a bug, not a diff.

    Without this, the size test could pass on a slimmed template while agents
    kept loading a stale 31KB ``SKILL.md`` from the checkout.
    """
    assert ORCHESTRATE_SKILL.exists(), f"missing rendered skill at {ORCHESTRATE_SKILL}"
    tracked = ORCHESTRATE_SKILL.read_text(encoding="utf-8")
    rendered = _render_orchestrate()
    assert tracked == rendered, (
        f"{ORCHESTRATE_SKILL} is out of sync with {TEMPLATE_NAME} "
        f"(tracked {len(tracked)} chars, rendered {len(rendered)} chars) — "
        "regenerate it from the template"
    )


def test_rendered_skill_links_the_design_doc_exactly_once():
    """The rationale lives in the reference doc, and is pointed at once.

    Zero links means the rationale was deleted rather than moved; more than one
    means the essay is creeping back in as repeated cross-references.
    """
    rendered = _render_orchestrate()
    count = rendered.count(DESIGN_DOC_LINK)
    assert count == 1, f"rendered skill names {DESIGN_DOC_LINK} {count} times, expected exactly 1"


def test_the_size_check_would_have_failed_on_the_pre_rewrite_template(tmp_path, monkeypatch):
    """Falsification guard: the old template, same renderer, must be rejected.

    The template at ``PRE_REWRITE_COMMIT`` is the 31,731-byte pre-rewrite
    version.  It is written into a temporary template dir and rendered through
    ``_render_template`` itself (via a patched ``_template_dir``), so the guard
    exercises the production renderer rather than a lookalike.  If git is
    unavailable — a source tarball, a shallow CI checkout — the guard falls
    back to padding the current render past the budget, which still proves the
    check fires on oversized input.
    """
    old_source = None
    try:
        old_source = subprocess.run(
            ["git", "show", f"{PRE_REWRITE_COMMIT}:{TEMPLATE_REPO_PATH}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        old_source = None

    if old_source:
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / TEMPLATE_NAME).write_text(old_source, encoding="utf-8")
        monkeypatch.setattr(projectman.cli, "_template_dir", lambda: tdir)
        oversized = _render_template(TEMPLATE_NAME)
        # _render_template swallows render errors and returns a short stub; a
        # stub would make the guard pass for the wrong reason.
        assert not oversized.endswith("template not found\n"), (
            f"the {PRE_REWRITE_COMMIT} copy of {TEMPLATE_NAME} failed to render; "
            "guard is inconclusive"
        )
    else:  # pragma: no cover - only when git history is unavailable
        oversized = _render_orchestrate() + ("x" * MAX_CHARS)

    assert len(oversized) > MAX_CHARS, "guard input is not actually oversized"
    assert not _within_limit(oversized), (
        f"the size check accepted a {len(oversized)}-character skill — "
        f"it does not enforce the {MAX_CHARS}-character budget"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
