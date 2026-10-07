"""Every pm skill/agent reference in the templates resolves under the plugin (US-PM-58-5).

Installed as a Claude Code plugin, our skills are `/projectman:<skill>` and our
agent is `projectman:<agent>`; a bare `/pm-do` or `subagent_type: pm` does not
resolve. This test scans the skill and agent templates (and the rendered
skills/ and agents/ plugin copies) for such references and fails on any name
the plugin does not ship, or on a pm reference that is not namespaced.

What the plugin provides is read from the repo, not hard-coded: the plugin
name from .claude-plugin/plugin.json, skills from skills/*/SKILL.md (directory
name cross-checked against frontmatter `name`), agents from agents/*.md
frontmatter `name`.

Excluded on purpose (to avoid false positives):
- `/pm...` preceded by a word char, `.`, `/`, `:`, `~` or `-` — paths and URLs
  such as `hooks/pm-context.sh`, `https://x/pm`, `.project/pm`;
- `/pm...` followed by a word char, `/`, `-`, or `.<word>` — file names such as
  `/pm-context.sh` and directories such as `/pm/`; a sentence-ending `.` is kept;
- skill/agent names in Skill(...) / "skill": / subagent_type / @agent- that are
  neither `projectman:`-namespaced nor pm-looking (other plugins, built-ins);
- built-in subagent types (general-purpose, Explore, Plan, ...).
"""

import ast
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "projectman" / "templates"

BUILTIN_AGENTS = {
    "general-purpose",
    "Explore",
    "Plan",
    "claude-code-guide",
    "statusline-setup",
    "claude",
    "fork",
}

_NAME = r"[A-Za-z0-9_][A-Za-z0-9_:-]*"
# /<plugin>:<name> — slash invocation of a namespaced skill.
NAMESPACED_SLASH = re.compile(r"(?<![\w./:~-])/(" + r"[A-Za-z0-9_-]+" + r"):([A-Za-z0-9_-]+)")
# Bare /pm or /pm-<x>, not part of a path, URL or file name.
BARE_SLASH = re.compile(r"(?<![\w./:~-])/(pm(?:-[A-Za-z0-9-]*[A-Za-z0-9])?)(?![\w/-]|\.\w)")
SKILL_REFS = [
    re.compile(r"Skill\(\s*(?:skill\s*=\s*)?[\"'`]?(" + _NAME + r")"),
    re.compile(r"[\"']skill[\"']\s*:\s*[\"'](" + _NAME + r")[\"']"),
]
AGENT_REFS = [
    re.compile(r"subagent_type[\"']?\s*[:=]\s*[\"'`]?(" + _NAME + r")"),
    re.compile(r"@agent-(" + _NAME + r")"),
]


def _frontmatter_name(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    nm = re.search(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", m.group(1), re.M)
    return nm.group(1) if nm else None


def plugin_provides(root: Path = REPO_ROOT) -> tuple[str, set[str], set[str]]:
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text())["name"]
    skills = set()
    for skill_md in sorted((root / "skills").glob("*/SKILL.md")):
        name = _frontmatter_name(skill_md)
        assert name == skill_md.parent.name, (
            f"{skill_md}: frontmatter name {name!r} != directory {skill_md.parent.name!r}"
        )
        skills.add(name)
    agents = set()
    for agent_md in sorted((root / "agents").glob("*.md")):
        name = _frontmatter_name(agent_md)
        assert name, f"{agent_md}: no frontmatter name"
        agents.add(name)
    return plugin, skills, agents


def _looks_ours(name: str) -> bool:
    return name == "pm" or name.startswith("pm-")


def scan(text: str, plugin: str, skills: set[str], agents: set[str]) -> list[str]:
    """Return one problem string per unresolvable or un-namespaced reference."""
    problems = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for m in NAMESPACED_SLASH.finditer(text):
        ns, name = m.groups()
        if ns == plugin and name not in skills:
            problems.append(f"line {line_of(m.start())}: /{ns}:{name} — no such skill shipped")

    for m in BARE_SLASH.finditer(text):
        problems.append(
            f"line {line_of(m.start())}: bare /{m.group(1)} — use /{plugin}:{m.group(1)}"
        )

    def check(name: str, pos: int, shipped: set[str], kind: str, builtins=frozenset()):
        if name in builtins:
            return
        if name.startswith(plugin + ":"):
            short = name.split(":", 1)[1]
            if short not in shipped:
                problems.append(f"line {line_of(pos)}: {kind} {name} — not shipped")
        elif ":" not in name and (_looks_ours(name) or name in shipped):
            problems.append(f"line {line_of(pos)}: {kind} {name} — use {plugin}:{name}")

    for rx in SKILL_REFS:
        for m in rx.finditer(text):
            check(m.group(1), m.start(), skills, "skill")
    for rx in AGENT_REFS:
        for m in rx.finditer(text):
            check(m.group(1), m.start(), agents, "agent", BUILTIN_AGENTS)
    return problems


def _scanned_files() -> list[Path]:
    files = sorted(TEMPLATES.glob("skill_*.md.j2")) + sorted(TEMPLATES.glob("agent_*.md.j2"))
    files += sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    files += sorted((REPO_ROOT / "agents").glob("*.md"))
    return files


@pytest.fixture(scope="module")
def provides():
    return plugin_provides()


def test_plugin_provides_is_derived_from_repo(provides):
    plugin, skills, agents = provides
    assert plugin == "projectman"
    assert "pm" in skills and "pm-do" in skills
    assert "pm" in agents


def test_scan_covers_templates_and_rendered_copies():
    files = _scanned_files()
    assert any(f.suffix == ".j2" and f.name.startswith("skill_") for f in files)
    assert any(f.suffix == ".j2" and f.name.startswith("agent_") for f in files)
    assert any(f.name == "SKILL.md" for f in files)
    assert any(f.parent.name == "agents" for f in files)


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_references_resolve_under_plugin(path, provides):
    problems = scan(path.read_text(encoding="utf-8"), *provides)
    assert not problems, f"{path.relative_to(REPO_ROOT)}:\n  " + "\n  ".join(problems)


def test_templates_do_reference_namespaced_skills(provides):
    """Guard against the scanner silently matching nothing."""
    plugin = provides[0]
    text = (TEMPLATES / "skill_pm.md.j2").read_text(encoding="utf-8")
    assert NAMESPACED_SLASH.search(text)
    assert f"/{plugin}:pm-do" in text


# --- negative / boundary tests on synthetic strings --------------------------

FAKE = ("projectman", {"pm", "pm-do", "pm-plan"}, {"pm"})


def test_catches_unshipped_namespaced_skill():
    problems = scan("Then run /projectman:pm-bogus on it.", *FAKE)
    assert len(problems) == 1 and "pm-bogus" in problems[0]


def test_catches_bare_slash_reference():
    problems = scan("Run /pm-do with the task id.\nOr just /pm.", *FAKE)
    assert len(problems) == 2
    assert "bare /pm-do" in problems[0] and "line 1" in problems[0]
    assert "bare /pm —" in problems[1] and "line 2" in problems[1]


def test_catches_bad_agent_references():
    text = (
        "Agent(subagent_type: projectman:nope)\n"
        'Agent(subagent_type="pm")\n'
        "@agent-projectman:ghost\n"
    )
    problems = scan(text, *FAKE)
    assert len(problems) == 3
    assert "projectman:nope" in problems[0]
    assert "use projectman:pm" in problems[1]
    assert "projectman:ghost" in problems[2]


def test_catches_bad_skill_tool_references():
    text = 'Skill(projectman:pm-ghost)\n{"skill": "pm-plan"}\n'
    problems = scan(text, *FAKE)
    assert len(problems) == 2
    assert "pm-ghost" in problems[0]
    assert "use projectman:pm-plan" in problems[1]


def test_no_false_positives():
    text = "\n".join(
        [
            "Run /projectman:pm-do and /projectman:pm.",
            "The hook hooks/pm-context.sh and ${CLAUDE_PLUGIN_ROOT}/pm-context.sh.",
            "Script /pm-context.sh runs at start; see /pm/ for nothing.",
            "Docs at https://example.com/pm and .project/pm-notes.md.",
            "Agent(subagent_type: general-purpose), subagent_type: Explore, @agent-Plan",
            "Agent(subagent_type: projectman:pm), Skill(projectman:pm-plan)",
            "Other plugins: /other:pm-do, Skill(other:thing), subagent_type: other:agent",
            "A pm-do skill mentioned without a slash, and pm_do the tool.",
        ]
    )
    assert scan(text, *FAKE) == []


# --- the worker and validator prompts (US-PM-58-1) ----------------------------
#
# The orchestrator hands each worker the "Worker Prompt Template" fence and
# each validator the "Validator Prompt Template" fence verbatim; those are the
# third surface beside skills and the pm agent.  The whole-file scan above
# already reads them, but these tests pin the fences down by name so a
# refactor that moves a prompt out of the skill file cannot drop it silently.

ORCHESTRATE_FILES = [
    TEMPLATES / "skill_pm_orchestrate.md.j2",
    REPO_ROOT / "skills" / "pm-orchestrate" / "SKILL.md",
]


def _prompt_fence(text: str, heading: str) -> str:
    m = re.search(r"^## " + re.escape(heading) + r"\s*\n+```[^\n]*\n(.*?)\n```", text, re.S | re.M)
    assert m, f"no fenced block under '## {heading}'"
    return m.group(1)


@pytest.mark.parametrize("heading", ["Worker Prompt Template", "Validator Prompt Template"])
@pytest.mark.parametrize("path", ORCHESTRATE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_orchestrator_prompt_fences_resolve(path, heading, provides):
    fence = _prompt_fence(path.read_text(encoding="utf-8"), heading)
    assert len(fence.splitlines()) >= 5, f"{heading} fence lost its body"
    problems = scan(fence, *provides)
    assert not problems, f"{path.relative_to(REPO_ROOT)} / {heading}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("path", ORCHESTRATE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_worker_prompt_names_the_namespaced_pm_do(path, provides):
    plugin, skills, _ = provides
    fence = _prompt_fence(path.read_text(encoding="utf-8"), "Worker Prompt Template")
    assert f"/{plugin}:pm-do" in fence
    assert "pm-do" in skills


def test_live_render_of_every_shipped_template_resolves(provides):
    """setup-claude renders through Jinja; the rendered text must scan clean too."""
    from projectman.cli import _render_template

    names = sorted(p.name for p in TEMPLATES.glob("skill_*.md.j2"))
    names += sorted(p.name for p in TEMPLATES.glob("agent_*.md.j2"))
    assert names
    for name in names:
        text = _render_template(name)
        assert "template not found" not in text, name
        problems = scan(text, *provides)
        assert not problems, f"rendered {name}:\n  " + "\n  ".join(problems)


# --- text the Python package emits to Claude (US-PM-58-1) ---------------------
#
# Besides the markdown, the package itself puts skill names in front of the
# model: MCP tool docstrings become tool descriptions, audit findings and
# other runtime strings come back as tool results, and `projectman
# session-context` (the plugin's SessionStart hook) prints a status block into
# the session.  Internal docstrings (module, class, non-tool function) and
# comments are not model-facing and are skipped.
#
# There are no known gaps: every model-facing string must use a resolvable
# name (``/projectman:pm-*``) or point at an MCP tool.

SRC = REPO_ROOT / "src" / "projectman"

_MCP_DECORATORS = {"tool", "resource", "prompt"}


def _is_mcp_decorated(fn) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if getattr(target, "attr", None) in _MCP_DECORATORS and getattr(
            getattr(target, "value", None), "id", None
        ) == "mcp":
            return True
    return False


def model_facing_strings(source: str) -> list[tuple[int, str]]:
    """(lineno, text) for every runtime string literal and MCP tool docstring."""

    tree = ast.parse(source)
    docstrings, tool_docs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_mcp_decorated(node):
                    tool_docs.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings and id(node) not in tool_docs:
                continue
            out.append((node.lineno, node.value))
    return out


def _source_problems(path: Path, provides) -> list[tuple[str, str]]:
    """(bare name, message) per unresolvable reference in model-facing text."""
    found = []
    for lineno, text in model_facing_strings(path.read_text(encoding="utf-8")):
        for problem in scan(text, *provides):
            m = re.search(r"bare (/\S+)|(\S+) — (?:no such|not shipped|use)", problem)
            name = (m.group(1) or m.group(2)) if m else problem
            found.append((name, f"{path.relative_to(REPO_ROOT)}:{lineno}: {problem}"))
    return found


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def test_source_scan_covers_the_emitting_modules():
    names = {p.name for p in _source_files()}
    assert {"server.py", "cli.py", "audit.py"} <= names


def test_source_scan_reads_tool_docstrings_and_skips_internal_ones():
    src = (
        '"""Module doc: /pm-orchestrate."""\n'
        "@mcp.tool(title='x')\n"
        'def pm_x():\n    """Use /pm-plan."""\n'
        'def helper():\n    """Internal /pm-do."""\n    return "run /pm-status"\n'
    )
    texts = [t for _, t in model_facing_strings(src)]
    assert "Use /pm-plan." in texts and "run /pm-status" in texts
    assert not any("Module doc" in t or "Internal" in t for t in texts)


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_source_emits_no_new_unresolvable_names(path, provides):
    """No model-facing string names an unresolvable skill."""
    new = [msg for _, msg in _source_problems(path, provides)]
    assert not new, "\n  ".join(["unresolvable skill names emitted to Claude:"] + new)


# --- end-to-end negative: the real scan entry point on a mutated copy (US-PM-58-2)


def test_real_scan_fails_on_unshipped_name_in_a_template_copy(tmp_path, monkeypatch, provides):
    """Inject /projectman:pm-bogus into a tmp copy of the templates and run the
    same file discovery + scan the parametrised test uses; it must be reported.
    The real templates are never touched."""
    import shutil
    import sys

    copy = tmp_path / "templates"
    shutil.copytree(TEMPLATES, copy)
    target = copy / "skill_pm.md.j2"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nThen run /projectman:pm-bogus on it.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "TEMPLATES", copy)

    files = [f for f in _scanned_files() if f.is_relative_to(copy)]
    assert target in files and len(files) >= 2
    reported = {f: scan(f.read_text(encoding="utf-8"), *provides) for f in files}
    bad = {f: p for f, p in reported.items() if p}
    assert list(bad) == [target]
    assert len(bad[target]) == 1 and "/projectman:pm-bogus" in bad[target][0]
    assert "no such skill shipped" in bad[target][0]
