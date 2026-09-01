"""US-PRJ-47: ``gh pr create`` commands are built from argv lists, not f-strings.

``changeset_create_prs`` used to paste the changeset title, the PR body and
the branch ref into a shell string inside double quotes.  A ``"``, a
backtick, ``$(…)`` or a ``;`` in any of them escaped its argument and the
rest of the string ran as shell.  The builder now assembles an ``argv``
list and renders the human-readable ``command`` with :func:`shlex.join`,
so every value survives ``shlex.split`` as exactly one token.

The cross-reference block used to be joined with a *literal* ``\\n``
(backslash-n in the source, two characters at runtime), so the PR body
arrived at GitHub as a single line.  It now uses real newlines.
"""

import json
import os
import re
import shlex
import subprocess
import sys

import frontmatter
import pytest

from projectman.changesets import changeset_create_prs, create_changeset
from projectman.models import ChangesetFrontmatter
from projectman.store import Store


def _persist(store: Store, meta: ChangesetFrontmatter, body: str) -> None:
    post = frontmatter.Post(content=body, **meta.model_dump(mode="json"))
    store._changeset_path(meta.id).write_text(frontmatter.dumps(post))


def _make(store: Store, title, projects, refs, description=""):
    """Create a changeset with the given title/projects/refs and return it."""
    cs = create_changeset(store, title, projects, description)
    meta, body = store.get_changeset(cs.id)
    for entry, ref in zip(meta.entries, refs):
        entry.ref = ref
    _persist(store, meta, body)
    return cs.id


def _expected_argv(title, project, body, ref):
    return ["gh", "pr", "create", "--title", f"{title}: {project}",
            "--body", body, "--head", ref]


# ─── argv list shape ───────────────────────────────────────────────


class TestArgvShape:
    """AC: PR commands use subprocess list args for all user input."""

    def test_each_pr_command_carries_an_argv_list(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", "feature/auth-ui"])

        result = changeset_create_prs(store, cs_id)

        for cmd in result["pr_commands"]:
            assert isinstance(cmd["argv"], list)
            assert all(isinstance(part, str) for part in cmd["argv"])

    def test_argv_is_the_full_gh_invocation_in_order(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        argv = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"]

        assert argv[:3] == ["gh", "pr", "create"]
        assert argv[3] == "--title"
        assert argv[4] == "add-auth: api"
        assert argv[5] == "--body"
        assert argv[7] == "--head"
        assert argv[8] == "feature/auth"
        assert len(argv) == 9

    def test_title_body_and_ref_are_each_exactly_one_argv_element(self, tmp_project):
        """The three user-supplied values occupy one slot each — no splitting."""
        store = Store(tmp_project)
        cs_id = _make(store, 'v2 "quoted" release; drop table',
                      ["api"], ["feature/x y; rm -rf /"],
                      description="body with $(whoami) and `id`")

        argv = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"]

        assert argv[4] == 'v2 "quoted" release; drop table: api'
        assert argv[8] == "feature/x y; rm -rf /"
        assert "$(whoami)" in argv[6] and "`id`" in argv[6]
        assert len(argv) == 9

    def test_entries_without_a_ref_are_skipped_and_carry_no_argv(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"], ["feature/auth", ""])

        commands = changeset_create_prs(store, cs_id)["pr_commands"]

        assert commands[1]["project"] == "web"
        assert "argv" not in commands[1]
        assert "command" not in commands[1]
        assert commands[1]["status"].startswith("skipped")


# ─── shlex round-trip ──────────────────────────────────────────────


class TestCommandRoundTrip:
    """AC: the rendered command string is shell-safe (shlex.quote)."""

    def test_command_splits_back_into_cd_project_and_argv(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", "feature/auth-ui"])

        result = changeset_create_prs(store, cs_id)

        for cmd in result["pr_commands"]:
            assert shlex.split(cmd["command"]) == [
                "cd", cmd["project"], "&&", *cmd["argv"]
            ]

    def test_command_is_the_cd_prefix_plus_shlex_join_of_argv(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert cmd["command"] == (
            f"cd {shlex.quote(cmd['project'])} && {shlex.join(cmd['argv'])}"
        )

    def test_project_name_is_quoted_in_the_cd_prefix(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["my project; rm -rf /"], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert shlex.split(cmd["command"])[:3] == ["cd", "my project; rm -rf /", "&&"]


# ─── injection payloads ────────────────────────────────────────────


PAYLOADS = [
    pytest.param('double "quote"', id="double-quote"),
    pytest.param("single 'quote'", id="single-quote"),
    pytest.param("back`tick`", id="backtick"),
    pytest.param("cmd $(whoami) sub", id="dollar-paren"),
    pytest.param("semi; echo pwned", id="semicolon"),
    pytest.param("and && echo pwned", id="and-and"),
    pytest.param("pipe | tee /tmp/pwned", id="pipe"),
    pytest.param("or || echo pwned", id="or-or"),
    pytest.param("redirect > /tmp/pwned", id="redirect"),
    pytest.param("newline\nrm -rf /", id="newline"),
    pytest.param("var $HOME and ${PATH}", id="dollar-var"),
    pytest.param("glob * ? [a-z]", id="glob"),
    pytest.param("back\\slash", id="backslash"),
    pytest.param("unicode — café ✓ 日本語", id="unicode"),
    pytest.param("nested \"'`$( ;", id="mixed"),
]


class TestSpecialCharactersAreInert:
    """AC: titles and descriptions with quotes/backticks/semicolons are safe."""

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_hostile_title_stays_one_token(self, tmp_project, payload):
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert cmd["argv"][4] == f"{payload}: api"
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_hostile_description_stays_one_token(self, tmp_project, payload):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"],
                      description=payload)

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert payload in cmd["argv"][6]
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_hostile_ref_stays_one_token(self, tmp_project, payload):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], [payload])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert cmd["argv"][8] == payload
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_hostile_project_name_stays_one_token(self, tmp_project, payload):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", [payload], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert shlex.split(cmd["command"]) == ["cd", payload, "&&", *cmd["argv"]]

    def test_command_never_grows_extra_shell_operators(self, tmp_project):
        """`&&` appears once — the cd separator — never from user input."""
        store = Store(tmp_project)
        cs_id = _make(store, "t && echo a", ["api"], ["r && echo b"],
                      description="body && echo c")

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert [t for t in shlex.split(cmd["command"]) if t == "&&"] == ["&&"]

    def test_no_bare_double_quote_wrapping_survives(self, tmp_project):
        """The old builder wrapped --title/--body in unescaped double quotes."""
        store = Store(tmp_project)
        cs_id = _make(store, 'x" ; echo pwned ; "y', ["api"], ["feature/auth"])

        command = changeset_create_prs(store, cs_id)["pr_commands"][0]["command"]

        assert '--title "x"' not in command
        # The payload survives intact as a single argument.
        assert shlex.split(command)[7] == 'x" ; echo pwned ; "y: api'


# ─── cross-reference block newlines ────────────────────────────────


class TestCrossRefNewlines:
    """AC: the cross-ref block renders newlines correctly in GitHub."""

    def test_body_uses_real_newlines_not_literal_backslash_n(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web", "worker"],
                      ["feature/auth"] * 3)

        body = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]

        assert "\\n" not in body
        assert "\n" in body

    def test_cross_ref_entries_land_on_separate_lines(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web", "worker"],
                      ["feature/auth", "feature/auth-ui", ""])

        body = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]
        lines = body.splitlines()

        assert "### Cross-references" in lines
        assert "- api (ref: feature/auth)" in lines
        assert "- web (ref: feature/auth-ui)" in lines
        assert "- worker (ref: TBD)" in lines

    def test_body_structure_is_heading_blank_line_then_cross_refs(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", "feature/auth-ui"],
                      description="Why this changeset exists.")

        body = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]
        lines = body.splitlines()

        assert lines[0].startswith("## Part of changeset: add-auth (")
        assert lines[1] == ""
        assert lines[2] == "### Cross-references"
        assert lines[3] == "- api (ref: feature/auth)"
        assert lines[4] == "- web (ref: feature/auth-ui)"
        assert lines[-1] == "Why this changeset exists."

    def test_newlines_are_preserved_through_the_rendered_command(self, tmp_project):
        """Quoting keeps the multi-line body one argument, newlines intact."""
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", "feature/auth-ui"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert shlex.split(cmd["command"])[9] == cmd["argv"][6]
        assert shlex.split(cmd["command"])[9].count("\n") >= 3


# ─── unchanged output shape for plain inputs ───────────────────────


class TestPlainInputShapeUnchanged:
    """Callers and the MCP tool see the same keys they always did."""

    def test_result_keys_are_unchanged(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        result = changeset_create_prs(store, cs_id)

        assert set(result) == {"changeset", "title", "pr_commands"}
        assert result["changeset"] == cs_id
        assert result["title"] == "add-auth"

    def test_command_entry_keys_are_the_old_ones_plus_argv(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert set(cmd) == {"project", "ref", "command", "argv"}
        assert cmd["project"] == "api"
        assert cmd["ref"] == "feature/auth"

    def test_plain_inputs_render_without_any_quoting(self, tmp_project):
        """Shell-safe values are not gratuitously quoted, so the display
        string reads exactly as it did before the fix."""
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        command = changeset_create_prs(store, cs_id)["pr_commands"][0]["command"]

        assert command.startswith("cd api && gh pr create --title ")
        assert command.endswith(" --head feature/auth")
        assert "gh pr create" in command

    def test_empty_changeset_still_raises(self, tmp_project):
        store = Store(tmp_project)
        cs = create_changeset(store, "empty", [])

        with pytest.raises(ValueError, match="no project entries"):
            changeset_create_prs(store, cs.id)


# ─── the MCP tool surfaces argv ────────────────────────────────────


class TestMCPToolOutput:
    def test_pm_changeset_create_prs_yaml_includes_argv(self, tmp_project, monkeypatch):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        from projectman.server import pm_changeset_create_prs

        result = yaml.safe_load(pm_changeset_create_prs(cs_id))
        cmd = result["pr_commands"][0]

        assert cmd["argv"][:3] == ["gh", "pr", "create"]
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]


# ─── the CLI shares the same builder ───────────────────────────────


class TestCLICreatePrs:
    """``projectman changeset create-prs`` had its own copy of the unsafe
    f-string; it now delegates to the shared, quoted builder."""

    def _run(self, tmp_project, monkeypatch, cs_id):
        from click.testing import CliRunner

        from projectman.cli import cli

        monkeypatch.chdir(tmp_project)
        result = CliRunner().invoke(cli, ["changeset", "create-prs", cs_id])
        assert result.exit_code == 0, result.output
        return result.output

    def test_cli_prints_quoted_commands(self, tmp_project, monkeypatch):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", "feature/auth-ui"])

        output = self._run(tmp_project, monkeypatch, cs_id)

        assert "# api:" in output
        assert "cd api && gh pr create --title " in output
        assert "--head feature/auth-ui" in output

    def test_cli_output_matches_the_shared_builder(self, tmp_project, monkeypatch):
        store = Store(tmp_project)
        cs_id = _make(store, 'v2 "release"; echo pwned', ["api"], ["feature/auth"])

        output = self._run(tmp_project, monkeypatch, cs_id)
        expected = changeset_create_prs(store, cs_id)["pr_commands"][0]["command"]

        assert expected in output
        assert 'gh pr create --title "v2 "release"' not in output

    def test_cli_reports_skipped_entries(self, tmp_project, monkeypatch):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"], ["feature/auth", ""])

        output = self._run(tmp_project, monkeypatch, cs_id)

        assert "# web: SKIPPED" in output


# ─── cross-ref text carries other entries' hostile values ──────────


class TestCrossRefTextIsInert:
    """The cross-ref block embeds *other* projects' names and refs, so a
    hostile value on entry B reaches entry A's ``--body``."""

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_other_entrys_hostile_ref_stays_inside_a_single_body_token(
        self, tmp_project, payload
    ):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"], ["feature/auth", payload])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert cmd["ref"] == "feature/auth"
        assert payload in cmd["argv"][6]
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]
        assert shlex.split(cmd["command"])[9] == cmd["argv"][6]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_other_entrys_hostile_project_name_stays_inside_the_body_token(
        self, tmp_project, payload
    ):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", payload], ["feature/auth", "b"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert f"- {payload} (ref: b)" in cmd["argv"][6]
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]


# ─── the MCP tool over a real tools/call ───────────────────────────


@pytest.mark.usefixtures("all_tool_families")
class TestMCPWirePath:
    """The gated ``pm_changeset_create_prs`` tool, driven through the real
    low-level ``tools/call`` handler — not by importing the function."""

    @staticmethod
    def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
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

    def test_wire_call_emits_argv_and_a_quoted_command(self, tmp_project, monkeypatch):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        is_error, text = self._call_over_the_wire(
            "pm_changeset_create_prs", {"changeset_id": cs_id}
        )

        assert is_error is False, text
        cmd = yaml.safe_load(text)["pr_commands"][0]
        assert cmd["argv"][:3] == ["gh", "pr", "create"]
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_wire_call_keeps_hostile_title_one_token(
        self, tmp_project, monkeypatch, payload
    ):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"], description=payload)

        is_error, text = self._call_over_the_wire(
            "pm_changeset_create_prs", {"changeset_id": cs_id}
        )

        assert is_error is False, text
        cmd = yaml.safe_load(text)["pr_commands"][0]
        assert cmd["argv"][4] == f"{payload}: api"
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_wire_call_keeps_hostile_project_name_in_the_cd_prefix(
        self, tmp_project, monkeypatch, payload
    ):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", [payload], ["feature/auth"])

        is_error, text = self._call_over_the_wire(
            "pm_changeset_create_prs", {"changeset_id": cs_id}
        )

        assert is_error is False, text
        cmd = yaml.safe_load(text)["pr_commands"][0]
        assert shlex.split(cmd["command"]) == ["cd", payload, "&&", *cmd["argv"]]


# ─── static guard: the bug class cannot silently come back ─────────


import ast  # noqa: E402
from pathlib import Path  # noqa: E402

import projectman  # noqa: E402

SRC = Path(projectman.__file__).parent
GUARDED = [SRC / "changesets.py", SRC / "cli.py"]


def _looks_like_a_shell_command(literal: str) -> bool:
    """A string literal that reads like a shell command line."""
    return literal.lstrip().startswith(("gh ", "git ")) or "&&" in literal


def _is_safely_quoted(node: ast.AST) -> bool:
    """``shlex.quote(x)`` / ``shlex.join(x)`` — the sanctioned interpolations."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"quote", "join"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "shlex"
    )


class TestStaticGuardAgainstShellStringBuilding:
    """US-PRJ-47 was an f-string pasting user input into a ``gh`` command.

    These tests read the source and fail if that shape reappears, so a
    future edit cannot quietly reintroduce the injection.
    """

    @pytest.mark.parametrize("path", GUARDED, ids=lambda p: p.name)
    def test_no_fstring_builds_a_shell_command_from_unquoted_parts(self, path):
        tree = ast.parse(path.read_text())
        offenders = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            literal = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant)
            )
            if not _looks_like_a_shell_command(literal):
                continue
            for part in node.values:
                if isinstance(part, ast.FormattedValue) and not _is_safely_quoted(
                    part.value
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno}: unquoted "
                        f"{ast.unparse(part.value)!r} in f{literal!r}"
                    )

        assert offenders == [], (
            "shell command built from unquoted f-string parts — "
            "use an argv list plus shlex.join/shlex.quote:\n"
            + "\n".join(offenders)
        )

    @pytest.mark.parametrize("path", GUARDED, ids=lambda p: p.name)
    def test_no_percent_or_format_builds_a_shell_command(self, path):
        tree = ast.parse(path.read_text())
        offenders = []

        for node in ast.walk(tree):
            literal = None
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Mod)
                and isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)
            ):
                literal = node.left.value
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)
            ):
                literal = node.func.value.value
            if literal is not None and _looks_like_a_shell_command(literal):
                offenders.append(f"{path.name}:{node.lineno}: {literal!r}")

        assert offenders == [], (
            "shell command built with %/.format — use argv + shlex:\n"
            + "\n".join(offenders)
        )

    def test_no_subprocess_call_anywhere_in_src_uses_shell_true(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")

        assert offenders == [], (
            "shell=True re-enables the injection this story fixed:\n"
            + "\n".join(offenders)
        )

    def test_the_only_shell_literal_in_the_builder_is_the_quoted_cd_prefix(self):
        """Positive control: the guard is looking at real code, and the one
        command-shaped f-string that exists is the sanctioned one."""
        tree = ast.parse((SRC / "changesets.py").read_text())
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            and _looks_like_a_shell_command(
                "".join(v.value for v in node.values if isinstance(v, ast.Constant))
            )
        ]

        assert len(found) == 1
        interpolations = [
            ast.unparse(v.value)
            for v in found[0].values
            if isinstance(v, ast.FormattedValue)
        ]
        assert interpolations == ["shlex.quote(entry.project)", "shlex.join(argv)"]


# ─── argv is for execution, never re-joined with spaces ────────────


class TestArgvIsNeverSpaceJoined:
    """AC/(e): callers execute ``argv``; nothing in src turns it back into a
    space-separated string (which would undo the quoting)."""

    def test_no_string_literal_join_is_applied_to_argv_in_src(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "join"
                    and isinstance(node.func.value, ast.Constant)
                ):
                    continue
                names = {
                    n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                } | {
                    n.value
                    for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                }
                if "argv" in names:
                    offenders.append(
                        f"{path.name}:{node.lineno}: {ast.unparse(node)}"
                    )

        assert offenders == [], (
            "argv joined into a shell string — execute the list instead:\n"
            + "\n".join(offenders)
        )

    def test_argv_is_only_ever_rendered_through_shlex_join(self):
        source = (SRC / "changesets.py").read_text()
        tree = ast.parse(source)
        renders = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and any(
                isinstance(n, ast.Name) and n.id == "argv" for n in ast.walk(node)
            )
        ]

        assert renders == ["shlex.join(argv)"]

    def test_the_command_string_is_not_argv_space_joined(self, tmp_project):
        """Behavioural twin of the static rule: for a hostile value the
        naive ``' '.join(argv)`` and the real command differ."""
        store = Store(tmp_project)
        cs_id = _make(store, "a b; echo pwned", ["api"], ["feature/auth"])

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]

        assert cmd["command"] != f"cd api && {' '.join(cmd['argv'])}"
        assert shlex.split(cmd["command"]) == ["cd", "api", "&&", *cmd["argv"]]


# ─── AC: the cross-ref block renders newlines correctly in GitHub ───


def _three_project_body(cs_id, description="Why this changeset exists."):
    """The exact PR body a 3-project changeset must produce."""
    return (
        f"## Part of changeset: add-auth ({cs_id})\n"
        "\n"
        "### Cross-references\n"
        "- api (ref: feature/auth)\n"
        "- web (ref: feature/auth-ui)\n"
        "- worker (ref: feature/auth-worker)\n"
        "\n"
        f"{description}"
    )


def _three_project_changeset(store, description="Why this changeset exists."):
    return _make(
        store,
        "add-auth",
        ["api", "web", "worker"],
        ["feature/auth", "feature/auth-ui", "feature/auth-worker"],
        description=description,
    )


class TestExactRenderedBody:
    """(a) The body in ``argv`` is this exact multi-line markdown."""

    def test_three_project_body_is_exactly_the_expected_markdown(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)

        result = changeset_create_prs(store, cs_id)

        expected = _three_project_body(cs_id)
        for cmd in result["pr_commands"]:
            assert cmd["argv"][6] == expected

    def test_headings_are_separated_from_content_by_blank_lines(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)

        lines = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]
        lines = lines.split("\n")

        assert lines[0].startswith("## Part of changeset: ")
        assert lines[1] == ""
        assert lines[2] == "### Cross-references"
        assert lines[3:6] == [
            "- api (ref: feature/auth)",
            "- web (ref: feature/auth-ui)",
            "- worker (ref: feature/auth-worker)",
        ]
        assert lines[6] == ""
        assert lines[7] == "Why this changeset exists."

    def test_every_cross_ref_is_its_own_markdown_list_item(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)

        body = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]
        bullets = [ln for ln in body.split("\n") if ln.startswith("- ")]

        assert len(bullets) == 3
        assert all("\\n" not in ln for ln in body.split("\n"))


class TestBodySurvivesShellQuotingRoundTrip:
    """(b) ``shlex.split(command)`` gives back the same multi-line body."""

    def test_split_command_yields_the_exact_body_as_one_argument(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)

        expected = _three_project_body(cs_id)
        for cmd in changeset_create_prs(store, cs_id)["pr_commands"]:
            tokens = shlex.split(cmd["command"])
            assert tokens == ["cd", cmd["project"], "&&", *cmd["argv"]]
            assert tokens[tokens.index("--body") + 1] == expected

    def test_the_rendered_command_holds_no_literal_backslash_n(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)

        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]["command"]

        assert "\\n" not in cmd
        assert cmd.count("\n") == 7


class TestBodyRendersAsMarkdown:
    """(c) Rendered as markdown the cross-refs are separate list items, not
    one run-on paragraph.  Uses the ``markdown`` package when the test
    environment has it, otherwise a structural check."""

    def test_cross_refs_render_as_separate_list_items(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        body = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]

        try:
            import markdown as markdown_mod
        except ImportError:
            markdown_mod = None

        if markdown_mod is not None:
            html = markdown_mod.markdown(body)
            items = re.findall(r"<li>(.*?)</li>", html, flags=re.S)
            assert len(items) == 3
            assert [i.split(" (ref:")[0].strip() for i in items] == [
                "api",
                "web",
                "worker",
            ]
            assert "<h2>" in html and "<h3>" in html
        else:
            lines = body.split("\n")
            bullets = [ln for ln in lines if ln.startswith("- ")]
            assert len(bullets) == 3
            assert [ln.split(" (ref:")[0][2:] for ln in bullets] == [
                "api",
                "web",
                "worker",
            ]
            # consecutive lines — not one run-on paragraph
            first = lines.index(bullets[0])
            assert lines[first:first + 3] == bullets
            assert all("\\n" not in ln for ln in lines)
            assert lines[first - 1] == "### Cross-references"

    def test_a_single_line_body_would_fail_this_check(self, tmp_project):
        """Positive control: the pre-fix body (literal backslash-n) does not
        pass the same markdown/structural check."""
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        good = changeset_create_prs(store, cs_id)["pr_commands"][0]["argv"][6]
        broken = good.replace("\n", "\\n")

        try:
            import markdown as markdown_mod

            assert len(re.findall(r"<li>", markdown_mod.markdown(broken))) < 3
        except ImportError:
            assert len([ln for ln in broken.split("\n") if ln.startswith("- ")]) < 3


class TestMultiLineBodyThroughCLIAndMCP:
    """(d) Both surfaces carry the multi-line body intact."""

    def test_cli_output_carries_the_quoted_multi_line_body(
        self, tmp_project, monkeypatch
    ):
        from click.testing import CliRunner

        from projectman.cli import cli

        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        expected_body = _three_project_body(cs_id)
        expected_cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]["command"]

        monkeypatch.chdir(tmp_project)
        result = CliRunner().invoke(cli, ["changeset", "create-prs", cs_id])

        assert result.exit_code == 0, result.output
        assert "\\n" not in result.output
        assert expected_cmd in result.output

        start = result.output.index(expected_cmd)
        printed = result.output[start:start + len(expected_cmd)]
        tokens = shlex.split(printed)
        assert tokens[tokens.index("--body") + 1] == expected_body

    def test_mcp_response_carries_the_multi_line_body(self, tmp_project, monkeypatch):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        expected_body = _three_project_body(cs_id)

        from projectman.server import pm_changeset_create_prs

        cmd = yaml.safe_load(pm_changeset_create_prs(cs_id))["pr_commands"][0]

        assert cmd["argv"][6] == expected_body
        tokens = shlex.split(cmd["command"])
        assert tokens[tokens.index("--body") + 1] == expected_body


@pytest.mark.usefixtures("all_tool_families")
class TestMultiLineBodyOverTheWire:
    """(d) …including a real ``tools/call`` round trip through YAML."""

    def test_wire_call_carries_the_multi_line_body(self, tmp_project, monkeypatch):
        import yaml

        monkeypatch.chdir(tmp_project)
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        expected_body = _three_project_body(cs_id)

        is_error, text = TestMCPWirePath._call_over_the_wire(
            "pm_changeset_create_prs", {"changeset_id": cs_id}
        )

        assert is_error is False, text
        cmd = yaml.safe_load(text)["pr_commands"][0]
        assert cmd["argv"][6] == expected_body
        assert "\\n" not in cmd["command"]
        tokens = shlex.split(cmd["command"])
        assert tokens[tokens.index("--body") + 1] == expected_body


class TestNoEscapedNewlineInBodyBuilder:
    """(e) Regression guard: a literal backslash-n must not come back."""

    @staticmethod
    def _builder_string_constants():
        tree = ast.parse((SRC / "changesets.py").read_text())
        builder = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "changeset_create_prs"
        )
        docstring = ast.get_docstring(builder, clean=False)
        return [
            node.value
            for node in ast.walk(builder)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value != docstring
        ]

    def test_builder_has_no_literal_backslash_n_string(self):
        offenders = [
            value
            for value in self._builder_string_constants()
            if "\\n" in value
        ]

        assert offenders == [], (
            "escaped newline back in the PR-body builder — GitHub renders the "
            f"cross-ref block as one line: {offenders!r}"
        )

    def test_the_guard_sees_the_real_newline_literals(self):
        """Positive control: the guard is reading the builder that actually
        joins the cross-refs with a real newline."""
        values = self._builder_string_constants()

        assert any(v == "\n" for v in values)
        assert any("### Cross-references" in v for v in values)


# ─── real-shell execution: a fake `gh` records the argv it actually got ───
#
# Everything above reasons about safety through ``shlex.split``.  That is a
# model of a shell, not a shell.  The tests below hand the rendered
# ``command`` to a *real* ``/bin/bash`` and ``/bin/sh`` with a fake ``gh``
# first on ``PATH``, and assert that the argv the fake ``gh`` recorded is
# byte-for-byte the argv the builder produced.  If a payload could break
# out of its argument, the recorded argv would differ (or the shell would
# run something else entirely) and these tests would fail.


_GH_RECORDER = """\
import json, os, sys
with open(os.environ["GH_ARGV_OUT"], "w", encoding="utf-8") as fh:
    json.dump(sys.argv[1:], fh)
"""


class FakeGh:
    """A ``gh`` on PATH that dumps its argv to a file instead of doing anything."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.root.mkdir(parents=True, exist_ok=True)
        self.bindir = tmp_path / "fakebin"
        self.bindir.mkdir(parents=True, exist_ok=True)
        recorder = self.bindir / "_gh_recorder.py"
        recorder.write_text(_GH_RECORDER)
        gh = self.bindir / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            f'exec {shlex.quote(sys.executable)} {shlex.quote(str(recorder))} "$@"\n'
        )
        gh.chmod(0o755)
        self.out = tmp_path / "gh_argv.json"
        self.workdir = tmp_path / "work"
        self.workdir.mkdir(parents=True, exist_ok=True)

    def project_dir(self, name):
        """Create (and return) the directory the generated ``cd`` targets."""
        d = self.workdir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _env(self):
        env = dict(os.environ)
        env["PATH"] = f"{self.bindir}{os.pathsep}{env.get('PATH', '')}"
        env["GH_ARGV_OUT"] = str(self.out)
        return env

    def run_in_shell(self, shell, command):
        """Execute ``command`` with a real shell; return the recorded argv."""
        if self.out.exists():
            self.out.unlink()
        proc = subprocess.run(
            [shell, "-c", command],
            cwd=str(self.workdir),
            env=self._env(),
            capture_output=True,
            text=True,
        )
        return proc, self._recorded()

    def run_argv(self, argv, cwd=None):
        """Execute ``argv`` directly — no shell at all."""
        if self.out.exists():
            self.out.unlink()
        proc = subprocess.run(
            argv,
            cwd=str(cwd or self.workdir),
            env=self._env(),
            capture_output=True,
            text=True,
        )
        return proc, self._recorded()

    def _recorded(self):
        if not self.out.exists():
            return None
        return json.loads(self.out.read_text(encoding="utf-8"))


@pytest.fixture
def fake_gh(tmp_path):
    return FakeGh(tmp_path / "shellharness")


SHELLS = [
    pytest.param(p, id=p.rsplit("/", 1)[-1])
    for p in ("/bin/bash", "/bin/sh")
]


def _require(shell):
    if not os.path.exists(shell):
        pytest.skip(f"{shell} not available")


# Payloads for the execution harness — the AC's characters plus the ones the
# DoD calls out (`#`, `!`, `$VAR`) and combinations of them.
EXEC_PAYLOADS = [
    pytest.param('has "double" quotes', id="double-quote"),
    pytest.param("has 'single' quotes", id="single-quote"),
    pytest.param("back`whoami`tick", id="backtick"),
    pytest.param("sub $(whoami) stitution", id="dollar-paren"),
    pytest.param("semi; echo pwned", id="semicolon"),
    pytest.param("and && echo pwned", id="and-and"),
    pytest.param("or || echo pwned", id="or-or"),
    pytest.param("pipe | cat", id="pipe"),
    pytest.param("redirect > out.txt", id="redirect"),
    pytest.param("line one\nline two", id="newline"),
    pytest.param("hash # not a comment", id="hash"),
    pytest.param("var $HOME and ${PATH}", id="dollar-var"),
    pytest.param("bang ! and !! history", id="bang"),
    pytest.param("unicode — café ✓ 日本語", id="unicode"),
    pytest.param(
        "combo \"'`$(id);&&||>|#!$HOME\nsecond line",
        id="combination",
    ),
]


class TestRealShellDeliversTheExactText:
    """AC: titles and descriptions with quotes/backticks/semicolons are safe.

    Not "shlex says so" — a real shell says so.
    """

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("payload", EXEC_PAYLOADS)
    def test_hostile_title_reaches_gh_as_one_exact_argument(
        self, tmp_project, fake_gh, shell, payload
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert recorded[3] == f"{payload}: api"

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("payload", EXEC_PAYLOADS)
    def test_hostile_description_reaches_gh_as_one_exact_argument(
        self, tmp_project, fake_gh, shell, payload
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"],
                      description=payload)
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert payload in recorded[5]

    @pytest.mark.parametrize("shell", SHELLS)
    def test_hostile_ref_reaches_gh_as_one_exact_argument(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ['r"; echo pwned; `id` $(id) &&'])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert recorded[7] == 'r"; echo pwned; `id` $(id) &&'

    @pytest.mark.parametrize("shell", SHELLS)
    def test_hostile_project_name_only_steers_the_cd(
        self, tmp_project, fake_gh, shell
    ):
        """The `cd` prefix is the one shell literal — it must stay one path."""
        _require(shell)
        hostile = 'my proj"; touch escaped; echo "x'
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", [hostile], ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir(hostile)

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert not (fake_gh.workdir / "escaped").exists()

    @pytest.mark.parametrize("shell", SHELLS)
    def test_no_stray_output_means_nothing_extra_ran(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, 'x"; echo BREAKOUT; echo "y', ["api"],
                      ["feature/auth"],
                      description='b"; echo BODYBREAK; echo "z')
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, _ = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.stdout == ""
        assert "BREAKOUT" not in proc.stdout + proc.stderr
        assert "BODYBREAK" not in proc.stdout + proc.stderr


class TestTheHarnessItself:
    """The fake `gh` must shadow any real one, or every result above is noise."""

    @pytest.mark.parametrize("shell", SHELLS)
    def test_gh_resolves_to_the_fake_inside_the_harness(self, fake_gh, shell):
        _require(shell)
        proc = subprocess.run(
            [shell, "-c", "command -v gh"],
            cwd=str(fake_gh.workdir),
            env=fake_gh._env(),
            capture_output=True,
            text=True,
        )
        assert proc.stdout.strip() == str(fake_gh.bindir / "gh")

    def test_direct_argv_execution_also_resolves_the_fake(self, fake_gh):
        _, recorded = fake_gh.run_argv(["gh", "sentinel-arg"])
        assert recorded == ["sentinel-arg"]

    @pytest.mark.parametrize("shell", SHELLS)
    def test_the_recorder_captures_argv_verbatim(self, fake_gh, shell):
        _require(shell)
        _, recorded = fake_gh.run_in_shell(
            shell, "gh 'a b' \"c\nd\" '$(id)'"
        )
        assert recorded == ["a b", "c\nd", "$(id)"]


class TestArgvExecutesDirectlyWithoutAShell:
    """AC (b): the same argv, run with no shell at all, is byte-identical."""

    @pytest.mark.parametrize("payload", EXEC_PAYLOADS)
    def test_argv_run_directly_delivers_the_exact_title(
        self, tmp_project, fake_gh, payload
    ):
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"],
                      description=payload)
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        project = fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_argv(cmd["argv"], cwd=project)

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert recorded[3] == f"{payload}: api"
        assert payload in recorded[5]

    @pytest.mark.parametrize("shell", SHELLS)
    def test_shell_and_direct_execution_agree(self, tmp_project, fake_gh, shell):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, 'T"`$(id);&&|># !$HOME', ["api"], ["feature/auth"],
                      description="D'\"`$(id)\nsecond")
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        project = fake_gh.project_dir("api")

        _, via_shell = fake_gh.run_in_shell(shell, cmd["command"])
        _, direct = fake_gh.run_argv(cmd["argv"], cwd=project)

        assert via_shell == direct == cmd["argv"][1:]


class TestCanaryFileIsNeverCreated:
    """AC (c): the classic `touch` payload must not touch anything."""

    @pytest.mark.parametrize("shell", SHELLS)
    def test_touch_payload_in_the_title_creates_no_file(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        canary = fake_gh.root / "pwned"
        title = f'x"; touch {canary}; echo "'
        store = Store(tmp_project)
        cs_id = _make(store, title, ["api"], ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert not canary.exists(), "shell injection: the canary file was created"
        assert proc.returncode == 0, proc.stderr
        assert recorded[3] == f"{title}: api"

    @pytest.mark.parametrize("shell", SHELLS)
    def test_touch_payload_in_the_description_creates_no_file(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        canary = fake_gh.root / "pwned_body"
        desc = f'y"; touch {canary}; echo "'
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"],
                      description=desc)
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert not canary.exists(), "shell injection: the canary file was created"
        assert proc.returncode == 0, proc.stderr
        assert desc in recorded[5]

    @pytest.mark.parametrize("shell", SHELLS)
    def test_backtick_and_dollar_paren_payloads_create_no_file(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        a = fake_gh.root / "pwned_tick"
        b = fake_gh.root / "pwned_paren"
        store = Store(tmp_project)
        cs_id = _make(store, f"t `touch {a}` end", ["api"], ["feature/auth"],
                      description=f"d $(touch {b}) end")
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert not a.exists() and not b.exists()
        assert recorded == cmd["argv"][1:]


class TestCrossRefBlockReachesGhIntact:
    """AC (d): the body's cross-ref block is built from *other* entries."""

    @pytest.mark.parametrize("shell", SHELLS)
    def test_another_entrys_hostile_ref_arrives_inside_the_body(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        hostile_ref = 'r"; touch CROSSREF_PWNED; `id` $(id) ; echo "'
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", "web"],
                      ["feature/auth", hostile_ref])
        cmds = changeset_create_prs(store, cs_id)["pr_commands"]
        api = next(c for c in cmds if c["project"] == "api")
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, api["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == api["argv"][1:]
        assert f"- web (ref: {hostile_ref})" in recorded[5]
        assert not (fake_gh.workdir / "CROSSREF_PWNED").exists()
        assert not (fake_gh.workdir / "api" / "CROSSREF_PWNED").exists()

    @pytest.mark.parametrize("shell", SHELLS)
    def test_another_entrys_hostile_project_name_arrives_inside_the_body(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        hostile = 'web"; touch XREF_PROJ_PWNED; echo "'
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api", hostile],
                      ["feature/auth", "feature/ui"])
        cmds = changeset_create_prs(store, cs_id)["pr_commands"]
        api = next(c for c in cmds if c["project"] == "api")
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, api["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == api["argv"][1:]
        assert f"- {hostile} (ref: feature/ui)" in recorded[5]
        assert not (fake_gh.workdir / "XREF_PROJ_PWNED").exists()

    @pytest.mark.parametrize("shell", SHELLS)
    def test_the_multi_line_body_survives_the_shell_verbatim(
        self, tmp_project, fake_gh, shell
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _three_project_changeset(store)
        cmds = changeset_create_prs(store, cs_id)["pr_commands"]
        api = next(c for c in cmds if c["project"] == "api")
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, api["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded[5] == api["argv"][6]
        assert recorded[5] == _three_project_body(cs_id)
        assert recorded[5].count("\n") >= 5


class TestLegacyFormatIsDetectablyUnsafe:
    """AC (e): positive control — the *old* f-string shape fails the canary.

    Reconstructed here (it no longer exists in ``src/``) so the harness is
    shown to be capable of detecting injection.  If this test ever stops
    creating the canary, the harness is broken and every assertion above
    is vacuous.
    """

    @staticmethod
    def _legacy_command(title, project, body, ref):
        # The pre-US-PRJ-47 shape: bare double quotes around user input.
        return (
            f'cd {project} && gh pr create '
            f'--title "{title}: {project}" '
            f'--body "{body}" '
            f'--head "{ref}"'
        )

    @pytest.mark.parametrize("shell", SHELLS)
    def test_legacy_title_payload_does_create_the_canary(self, fake_gh, shell):
        _require(shell)
        canary = fake_gh.root / "legacy_pwned"
        title = f'x"; touch {canary}; echo "'
        fake_gh.project_dir("api")

        legacy = self._legacy_command(title, "api", "body", "feature/auth")
        fake_gh.run_in_shell(shell, legacy)

        assert canary.exists(), (
            "the harness cannot detect injection — the positive control failed"
        )

    @pytest.mark.parametrize("shell", SHELLS)
    def test_legacy_body_payload_does_create_the_canary(self, fake_gh, shell):
        _require(shell)
        canary = fake_gh.root / "legacy_body_pwned"
        body = f'b"; touch {canary}; echo "'
        fake_gh.project_dir("api")

        legacy = self._legacy_command("t", "api", body, "feature/auth")
        fake_gh.run_in_shell(shell, legacy)

        assert canary.exists()

    @pytest.mark.parametrize("shell", SHELLS)
    def test_current_builder_survives_the_exact_payload_the_legacy_one_fell_to(
        self, tmp_project, fake_gh, shell
    ):
        """Same payload, same harness, same shell — old breaks, new holds."""
        _require(shell)
        old_canary = fake_gh.root / "control_old"
        new_canary = fake_gh.root / "control_new"
        store = Store(tmp_project)
        fake_gh.project_dir("api")

        legacy = self._legacy_command(
            f'x"; touch {old_canary}; echo "', "api", "body", "feature/auth"
        )
        fake_gh.run_in_shell(shell, legacy)

        cs_id = _make(store, f'x"; touch {new_canary}; echo "', ["api"],
                      ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.run_in_shell(shell, cmd["command"])

        assert old_canary.exists(), "positive control did not fire"
        assert not new_canary.exists(), "current builder is injectable"


# ═══ US-PRJ-47-4: the special-character coverage matrix ═════════════
#
# The tests above grew payload-first: someone thought of a hostile string
# and wrote a test for it.  That answers "is this payload safe?" but never
# "which edge cases are we not thinking of?".  The matrix below inverts it:
# every *input* the builder reads crossed with every *class* of edge case,
# with each cell naming the test that covers it.  Adding a class to
# ``EDGE_CLASSES`` without covering it fails
# ``TestTheMatrixItself::test_every_input_by_class_cell_maps_to_a_test``.

from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402

from pydantic import ValidationError  # noqa: E402

from projectman.models import ChangesetEntry  # noqa: E402


@dataclass(frozen=True)
class EdgeClass:
    """One class of hostile/awkward value, with a representative sample."""

    id: str
    sample: str
    why: str


EDGE_CLASSES = [
    EdgeClass("empty", "", "a missing value must not shift argv positions"),
    EdgeClass("whitespace", "   \t   ",
              "whitespace-only must stay one token, not vanish or split"),
    EdgeClass("leading-dash", "--body=evil",
              "a value that looks like an option to `gh`"),
    EdgeClass("very-long", "L" * 10240, "10 KB value (body-sized)"),
    EdgeClass("nul", "before\x00after",
              "argv cannot carry NUL — pinned as a rejection"),
    EdgeClass("cr-crlf", "cr\rmid\r\ncrlf\nlf",
              "bare CR and CRLF, not just LF"),
    EdgeClass("tab", "tab\there\tand\tthere", "tabs are shell word separators"),
    EdgeClass("trailing-backslash", "back\\slash and a trailing\\",
              "a trailing backslash can escape the closing quote"),
    EdgeClass("percent-brace", "100% done {name} {0} %s %(key)s",
              "format-string-looking text must never be formatted"),
    EdgeClass("non-bmp",
              "emoji \U0001f680\U0001f9e8 rtl \u202eevil\u202c mark \u200f end",
              "non-BMP astral chars and RTL/bidi marks"),
    EdgeClass("glob", "glob * ? [a-z]", "shell glob characters"),
    EdgeClass("tilde", "~ and ~root/.ssh and a~b", "tilde expansion"),
    EdgeClass("dollar-paren", "$(id) `whoami` ${PATH} $HOME",
              "command and variable substitution"),
    EdgeClass("quotes", "\"double\" 'single' mixed \"'", "quote characters"),
    EdgeClass("shell-operators", "a; b && c || d | e > f < g",
              "every separator/redirection operator, `<` included"),
    EdgeClass("hash", "# not a comment", "comment character"),
    EdgeClass("bang", "bang ! and !! history", "history expansion"),
    EdgeClass("shlex-quoted", shlex.quote("evil; rm -rf /"),
              "a value that is itself already a valid shlex-quoted string"),
]

# Every value the builder reads and puts into an argv element or the `cd`.
MATRIX_INPUTS = (
    "title",            # meta.title  → --title
    "description",      # body        → --body
    "cross_ref",        # another entry's project/ref → inside --body
    "project",          # entry.project → the `cd` prefix and the title suffix
    "ref",              # entry.ref   → --head
    "changeset_id",     # meta.id     → inside --body
)

# Cells already covered before US-PRJ-47-4, by node ID.  A citation is
# ``Class::test_name[param-id]``; where a test stacks two parametrisations
# (payload × shell) the collected node ID composes both ids and the
# param-id cited here is the payload half.
PRE_COVERED = {
    ("title", "quotes"): (
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[double-quote]",
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[single-quote]",
    ),
    ("title", "dollar-paren"): (
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[dollar-paren]",
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[backtick]",
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[dollar-var]",
    ),
    ("title", "glob"): (
        "TestSpecialCharactersAreInert::test_hostile_title_stays_one_token"
        "[glob]",
    ),
    ("title", "hash"): (
        "TestRealShellDeliversTheExactText::"
        "test_hostile_title_reaches_gh_as_one_exact_argument[hash]",
    ),
    ("title", "bang"): (
        "TestRealShellDeliversTheExactText::"
        "test_hostile_title_reaches_gh_as_one_exact_argument[bang]",
    ),
    ("description", "quotes"): (
        "TestSpecialCharactersAreInert::test_hostile_description_stays_one_token"
        "[double-quote]",
        "TestSpecialCharactersAreInert::test_hostile_description_stays_one_token"
        "[single-quote]",
    ),
    ("description", "dollar-paren"): (
        "TestSpecialCharactersAreInert::test_hostile_description_stays_one_token"
        "[dollar-paren]",
        "TestSpecialCharactersAreInert::test_hostile_description_stays_one_token"
        "[backtick]",
    ),
    ("description", "glob"): (
        "TestSpecialCharactersAreInert::test_hostile_description_stays_one_token"
        "[glob]",
    ),
    ("description", "hash"): (
        "TestRealShellDeliversTheExactText::"
        "test_hostile_description_reaches_gh_as_one_exact_argument[hash]",
    ),
    ("description", "bang"): (
        "TestRealShellDeliversTheExactText::"
        "test_hostile_description_reaches_gh_as_one_exact_argument[bang]",
    ),
    ("ref", "quotes"): (
        "TestSpecialCharactersAreInert::test_hostile_ref_stays_one_token"
        "[double-quote]",
        "TestSpecialCharactersAreInert::test_hostile_ref_stays_one_token"
        "[single-quote]",
    ),
    ("ref", "dollar-paren"): (
        "TestSpecialCharactersAreInert::test_hostile_ref_stays_one_token"
        "[dollar-paren]",
        "TestSpecialCharactersAreInert::test_hostile_ref_stays_one_token"
        "[backtick]",
    ),
    ("ref", "glob"): (
        "TestSpecialCharactersAreInert::test_hostile_ref_stays_one_token[glob]",
    ),
    ("project", "quotes"): (
        "TestSpecialCharactersAreInert::test_hostile_project_name_stays_one_token"
        "[double-quote]",
        "TestSpecialCharactersAreInert::test_hostile_project_name_stays_one_token"
        "[single-quote]",
    ),
    ("project", "dollar-paren"): (
        "TestSpecialCharactersAreInert::test_hostile_project_name_stays_one_token"
        "[dollar-paren]",
        "TestSpecialCharactersAreInert::test_hostile_project_name_stays_one_token"
        "[backtick]",
    ),
    ("project", "glob"): (
        "TestSpecialCharactersAreInert::test_hostile_project_name_stays_one_token"
        "[glob]",
    ),
    ("cross_ref", "quotes"): (
        "TestCrossRefTextIsInert::"
        "test_other_entrys_hostile_ref_stays_inside_a_single_body_token"
        "[double-quote]",
        "TestCrossRefTextIsInert::"
        "test_other_entrys_hostile_project_name_stays_inside_the_body_token"
        "[single-quote]",
    ),
    ("cross_ref", "dollar-paren"): (
        "TestCrossRefTextIsInert::"
        "test_other_entrys_hostile_ref_stays_inside_a_single_body_token"
        "[dollar-paren]",
        "TestCrossRefTextIsInert::"
        "test_other_entrys_hostile_ref_stays_inside_a_single_body_token"
        "[backtick]",
    ),
    ("cross_ref", "glob"): (
        "TestCrossRefTextIsInert::"
        "test_other_entrys_hostile_ref_stays_inside_a_single_body_token[glob]",
    ),
}

# The gap-filling test per input, added by US-PRJ-47-4.
GAP_TESTS = {
    "title": "test_title_edge_class",
    "description": "test_description_edge_class",
    "cross_ref": "test_cross_ref_edge_class",
    "project": "test_project_edge_class",
    "ref": "test_ref_edge_class",
    "changeset_id": "test_changeset_id_edge_class",
}


def _gaps(input_name):
    """The classes this input has no pre-existing test for."""
    return [
        pytest.param(case, id=case.id)
        for case in EDGE_CLASSES
        if (input_name, case.id) not in PRE_COVERED
    ]


def citations_for(input_name, class_id):
    """Every node ID the matrix claims for one cell."""
    cites = list(PRE_COVERED.get((input_name, class_id), ()))
    if any(p.values[0].id == class_id for p in _gaps(input_name)):
        cites.append(
            f"TestEdgeCaseMatrix::{GAP_TESTS[input_name]}[{class_id}]"
        )
    return cites


# ─── the builder under exact inputs: a stub store ──────────────────
#
# The matrix is about the *builder's* contract, so the samples are handed
# to it directly.  Going through disk would silently normalise some of
# them (python-frontmatter strips the body, so a whitespace-only
# description would arrive as "" and the cell would prove nothing).
# ``TestTheStubStoreIsFaithful`` pins the stub against the real Store.


class _StubStore:
    """Just enough Store for ``changeset_create_prs``: one changeset."""

    def __init__(self, meta, body):
        self._meta = meta
        self._body = body

    def get_changeset(self, changeset_id):
        return self._meta, self._body


def _stub(title="add-auth", projects=(("api", "feature/auth"),),
          description="Why this changeset exists.", cs_id="CS-TST-1"):
    meta = ChangesetFrontmatter(
        id=cs_id,
        title=title,
        entries=[ChangesetEntry(project=p, ref=r) for p, r in projects],
        created=date.today(),
        updated=date.today(),
    )
    return _StubStore(meta, description)


def _round_trips(cmd, project):
    """The rendered command splits back into exactly `cd <project> && argv`."""
    return shlex.split(cmd["command"]) == ["cd", project, "&&", *cmd["argv"]]


NUL_MESSAGE = "NUL byte"


class TestEdgeCaseMatrix:
    """One test per (input, edge class) cell the earlier tests left open.

    Each asserts the same two invariants: the sample lands in the argv slot
    it belongs in (nothing shifts, nothing splits, nothing is expanded), and
    ``shlex.split(command)`` round-trips to ``cd <project> && *argv``.
    """

    @pytest.mark.parametrize("case", _gaps("title"))
    def test_title_edge_class(self, case):
        store = _stub(title=case.sample)

        if case.id == "nul":
            with pytest.raises(ValueError, match=NUL_MESSAGE):
                changeset_create_prs(store, "CS-TST-1")
            return

        cmd = changeset_create_prs(store, "CS-TST-1")["pr_commands"][0]

        assert len(cmd["argv"]) == 9
        assert cmd["argv"][3] == "--title"
        assert cmd["argv"][4] == f"{case.sample}: api"
        assert _round_trips(cmd, "api")

    @pytest.mark.parametrize("case", _gaps("description"))
    def test_description_edge_class(self, case):
        store = _stub(description=case.sample)

        if case.id == "nul":
            with pytest.raises(ValueError, match=NUL_MESSAGE):
                changeset_create_prs(store, "CS-TST-1")
            return

        cmd = changeset_create_prs(store, "CS-TST-1")["pr_commands"][0]

        assert len(cmd["argv"]) == 9
        assert cmd["argv"][5] == "--body"
        assert cmd["argv"][6].endswith(case.sample)
        assert _round_trips(cmd, "api")

    @pytest.mark.parametrize("case", _gaps("cross_ref"))
    def test_cross_ref_edge_class(self, case):
        """The *other* entry's text is quoted inside this entry's body."""
        if case.id == "empty":
            # An empty ref renders as TBD, so the empty sample goes in the
            # other entry's project name instead.
            projects = (("api", "feature/auth"), ("", ""))
            expected_line = "-  (ref: TBD)"
        else:
            projects = (("api", "feature/auth"), ("b-proj", case.sample))
            expected_line = f"- b-proj (ref: {case.sample})"
        store = _stub(projects=projects)

        if case.id == "nul":
            with pytest.raises(ValueError, match=NUL_MESSAGE):
                changeset_create_prs(store, "CS-TST-1")
            return

        cmd = changeset_create_prs(store, "CS-TST-1")["pr_commands"][0]

        assert cmd["project"] == "api"
        assert expected_line in cmd["argv"][6]
        assert _round_trips(cmd, "api")

    @pytest.mark.parametrize("case", _gaps("project"))
    def test_project_edge_class(self, case):
        store = _stub(projects=((case.sample, "feature/auth"),))

        if case.id == "nul":
            with pytest.raises(ValueError, match=NUL_MESSAGE):
                changeset_create_prs(store, "CS-TST-1")
            return

        cmd = changeset_create_prs(store, "CS-TST-1")["pr_commands"][0]

        assert cmd["argv"][4] == f"add-auth: {case.sample}"
        assert shlex.split(cmd["command"])[:2] == ["cd", case.sample]
        assert _round_trips(cmd, case.sample)

    @pytest.mark.parametrize("case", _gaps("ref"))
    def test_ref_edge_class(self, case):
        store = _stub(projects=(("api", case.sample),))

        if case.id == "nul":
            with pytest.raises(ValueError, match=NUL_MESSAGE):
                changeset_create_prs(store, "CS-TST-1")
            return

        cmd = changeset_create_prs(store, "CS-TST-1")["pr_commands"][0]

        if case.id == "empty":
            # Pinned behaviour: no ref means no command at all.
            assert cmd == {"project": "api",
                           "status": "skipped — no ref/branch set"}
            assert "argv" not in cmd
            return

        assert len(cmd["argv"]) == 9
        assert cmd["argv"][7] == "--head"
        assert cmd["argv"][8] == case.sample
        assert _round_trips(cmd, "api")

    @pytest.mark.parametrize("case", _gaps("changeset_id"))
    def test_changeset_id_edge_class(self, case):
        """The id is model-validated, so most classes never reach the builder.

        Whatever the validator lets through must still be inert in the body.
        """
        try:
            store = _stub(cs_id=case.sample)
        except ValidationError as exc:
            assert "Changeset ID must be alphanumeric" in str(exc)
            return

        cmd = changeset_create_prs(store, case.sample)["pr_commands"][0]

        assert f"({case.sample})" in cmd["argv"][6]
        assert _round_trips(cmd, "api")

    def test_a_nul_id_that_bypasses_the_validator_is_still_rejected(self):
        """``model_construct`` skips validation — the builder guards anyway."""
        meta = ChangesetFrontmatter.model_construct(
            id="CS-TST\x00-1",
            title="add-auth",
            entries=[ChangesetEntry(project="api", ref="feature/auth")],
            created=date.today(),
            updated=date.today(),
        )

        with pytest.raises(ValueError, match=NUL_MESSAGE):
            changeset_create_prs(_StubStore(meta, "desc"), "CS-TST-1")


class TestNulByteIsRejectedNotRendered:
    """Pinned decision (US-PRJ-47-4): a NUL byte is refused with a clear error.

    ``execve`` argv strings are NUL-terminated, so no argument can carry
    one: ``subprocess.run`` raises ``ValueError: embedded null byte`` and a
    shell truncates at the NUL.  ``shlex.quote`` would happily wrap it and
    hand the caller a display string that cannot run — so the builder says
    so instead, naming the field.  Documented in
    ``docs/reference/mcp-tools.md``.
    """

    @pytest.mark.parametrize("field", ["title", "description", "project", "ref"])
    def test_a_nul_in_any_field_raises_naming_that_field(self, tmp_project, field):
        store = Store(tmp_project)
        cs_id = _make(
            store,
            "ti\x00tle" if field == "title" else "add-auth",
            ["ap\x00i" if field == "project" else "api"],
            ["fea\x00ture" if field == "ref" else "feature/auth"],
            description="de\x00sc" if field == "description" else "desc",
        )

        with pytest.raises(ValueError) as exc:
            changeset_create_prs(store, cs_id)

        message = str(exc.value)
        assert "NUL byte (0x00)" in message
        assert cs_id in message
        assert field in message

    def test_the_nul_survives_the_store_round_trip_so_the_guard_is_needed(
        self, tmp_project
    ):
        """Positive control: YAML really does carry a NUL back to the builder."""
        store = Store(tmp_project)
        cs_id = _make(store, "ti\x00tle", ["api"], ["feature/auth"])

        meta, _ = store.get_changeset(cs_id)

        assert meta.title == "ti\x00tle"

    def test_subprocess_would_refuse_the_argv_a_nul_produced(self):
        """Why rejecting beats rendering: the argv could never be executed."""
        with pytest.raises(ValueError, match="null byte"):
            subprocess.run(["/bin/true", "a\x00b"], capture_output=True)

    def test_the_cli_reports_the_rejection_instead_of_a_traceback(
        self, tmp_project, monkeypatch
    ):
        from click.testing import CliRunner

        from projectman.cli import cli

        store = Store(tmp_project)
        cs_id = _make(store, "ti\x00tle", ["api"], ["feature/auth"])
        monkeypatch.chdir(tmp_project)

        result = CliRunner().invoke(cli, ["changeset", "create-prs", cs_id])

        assert result.exit_code == 1
        assert "NUL byte (0x00)" in result.output
        assert result.exception is None or isinstance(
            result.exception, SystemExit
        )

    def test_a_clean_changeset_is_untouched_by_the_guard(self, tmp_project):
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], ["feature/auth"])

        result = changeset_create_prs(store, cs_id)

        assert result["pr_commands"][0]["argv"][4] == "add-auth: api"


class TestTheStubStoreIsFaithful:
    """The matrix uses a stub store; it must agree with the real one."""

    def test_stub_and_real_store_produce_the_same_commands(self, tmp_project):
        real = Store(tmp_project)
        cs_id = _make(real, 'x"; echo pwned', ["api", "web"],
                      ["feature/auth", "feature/ui"],
                      description="Why this changeset exists.")
        stub = _stub(
            title='x"; echo pwned',
            projects=(("api", "feature/auth"), ("web", "feature/ui")),
            description="Why this changeset exists.",
            cs_id=cs_id,
        )

        assert (changeset_create_prs(stub, cs_id)
                == changeset_create_prs(real, cs_id))


# ─── (c) option injection: `--body=evil` as a title, `-x` as a ref ──


OPTION_PAYLOADS = [
    pytest.param("--body=evil", id="long-option-with-value"),
    pytest.param("--body", id="bare-long-option"),
    pytest.param("-x", id="short-option"),
    pytest.param("--", id="end-of-options"),
    pytest.param("-", id="lone-dash"),
]


class TestOptionLookingValuesStayValues:
    """A value that looks like a `gh` flag must arrive as the flag's *value*.

    Quoting alone does not settle this: ``--body=evil`` needs no quoting at
    all, and a naive builder would hand ``gh`` a second ``--body``.  What
    protects it is argv *position* — the payload is the element right after
    ``--title``, and ``gh``'s flag parser takes the following argument as a
    string flag's value.  The fake ``gh`` records the argv it was actually
    handed, through a real shell, so the position is verified end to end.
    """

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("payload", OPTION_PAYLOADS)
    def test_option_looking_title_lands_after_title(
        self, tmp_project, fake_gh, shell, payload
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert len(recorded) == 8
        assert recorded[recorded.index("--title") + 1] == f"{payload}: api"
        # The option the payload imitates appears exactly once, still with
        # the builder's own value.
        assert recorded.count("--body") == 1
        assert recorded[recorded.index("--body") + 1] == cmd["argv"][6]

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("payload", OPTION_PAYLOADS)
    def test_option_looking_ref_lands_after_head(
        self, tmp_project, fake_gh, shell, payload
    ):
        _require(shell)
        store = Store(tmp_project)
        cs_id = _make(store, "add-auth", ["api"], [payload])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert len(recorded) == 8
        assert recorded[recorded.index("--head") + 1] == payload
        assert recorded[-1] == payload

    @pytest.mark.parametrize("payload", OPTION_PAYLOADS)
    def test_direct_argv_execution_places_them_identically(
        self, tmp_project, fake_gh, payload
    ):
        """No shell at all — the argv form callers are told to execute."""
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], [payload])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        workdir = fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_argv(cmd["argv"], cwd=workdir)

        assert proc.returncode == 0, proc.stderr
        assert recorded == cmd["argv"][1:]
        assert recorded[recorded.index("--title") + 1] == f"{payload}: api"
        assert recorded[recorded.index("--head") + 1] == payload

    @pytest.mark.parametrize("shell", SHELLS)
    def test_an_option_looking_title_creates_no_extra_words(
        self, tmp_project, fake_gh, shell
    ):
        """`--body=evil --head=evil` in the title is still one argument."""
        _require(shell)
        payload = "--body=evil --head=evil-branch --repo=evil/repo"
        store = Store(tmp_project)
        cs_id = _make(store, payload, ["api"], ["feature/auth"])
        cmd = changeset_create_prs(store, cs_id)["pr_commands"][0]
        fake_gh.project_dir("api")

        proc, recorded = fake_gh.run_in_shell(shell, cmd["command"])

        assert proc.returncode == 0, proc.stderr
        assert len(recorded) == 8
        assert recorded[3] == f"{payload}: api"
        assert not any(a.startswith("--repo") for a in recorded)
        assert recorded.count("--head") == 1


# ─── the matrix guards itself ───────────────────────────────────────


_CITATION = re.compile(r"^(?P<cls>Test\w+)::(?P<fn>test_\w+)(?:\[(?P<param>.+)\])?$")


def _parametrize_ids(func):
    """Every param id pytest will build node IDs from for ``func``."""
    ids = set()
    for mark in getattr(func, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        id_maker = mark.kwargs.get("ids")
        for value in mark.args[1]:
            param_id = getattr(value, "id", None)
            if param_id:
                ids.add(param_id)
            elif callable(id_maker):
                ids.add(id_maker(value))
    return ids


def _citation_resolves(citation):
    """True when ``Class::test[param]`` names a real test in this module."""
    match = _CITATION.match(citation)
    if not match:
        return False
    cls = globals().get(match["cls"])
    if not isinstance(cls, type):
        return False
    func = getattr(cls, match["fn"], None)
    if not callable(func):
        return False
    if match["param"] is None:
        return True
    return match["param"] in _parametrize_ids(func)


class TestTheMatrixItself:
    """(b) The matrix is data, and this is the test that keeps it honest.

    Add an edge class to ``EDGE_CLASSES`` and every input immediately owes
    it a test; delete or rename a cited test and the citation stops
    resolving.  Either way this fails before the coverage claim rots.
    """

    def test_every_input_by_class_cell_maps_to_a_test(self):
        uncovered = []
        unresolved = []

        for input_name in MATRIX_INPUTS:
            for case in EDGE_CLASSES:
                cites = citations_for(input_name, case.id)
                if not cites:
                    uncovered.append(f"{input_name} × {case.id}")
                unresolved += [
                    f"{input_name} × {case.id} → {c}"
                    for c in cites
                    if not _citation_resolves(c)
                ]

        assert uncovered == [], (
            "edge cases with no test — add a parametrised case or cite one:\n"
            + "\n".join(uncovered)
        )
        assert unresolved == [], (
            "matrix cites a test that does not exist:\n" + "\n".join(unresolved)
        )

    def test_the_matrix_covers_every_value_the_builder_reads(self):
        """The input list is not a guess: these are the builder's own reads."""
        source = (SRC / "changesets.py").read_text()
        builder = source.split("def changeset_create_prs(", 1)[1]
        builder = builder.split("\ndef ", 1)[0]

        for expression in ("meta.title", "meta.id", "entry.project",
                           "entry.ref", "e.project", "e.ref", "body"):
            assert expression in builder, expression
        assert len(MATRIX_INPUTS) == 6

    def test_the_resolver_rejects_citations_that_do_not_exist(self):
        """Positive control — otherwise the guard above passes vacuously."""
        assert _citation_resolves(
            "TestEdgeCaseMatrix::test_title_edge_class[tab]"
        )
        assert not _citation_resolves(
            "TestEdgeCaseMatrix::test_title_edge_class[no-such-param]"
        )
        assert not _citation_resolves("TestEdgeCaseMatrix::test_no_such_test")
        assert not _citation_resolves("TestNoSuchClass::test_title_edge_class")
        assert not _citation_resolves("not a node id")

    def test_edge_class_ids_are_unique_and_samples_distinct(self):
        ids = [case.id for case in EDGE_CLASSES]
        samples = [case.sample for case in EDGE_CLASSES]

        assert len(set(ids)) == len(ids)
        assert len(set(samples)) == len(samples)

    def test_every_pre_covered_citation_names_a_real_input_and_class(self):
        known_classes = {case.id for case in EDGE_CLASSES}

        for input_name, class_id in PRE_COVERED:
            assert input_name in MATRIX_INPUTS, input_name
            assert class_id in known_classes, class_id

    def test_no_cell_is_both_pre_covered_and_gap_filled(self):
        """A gap test must not be generated for a cell that was covered."""
        for input_name in MATRIX_INPUTS:
            gap_ids = {p.values[0].id for p in _gaps(input_name)}
            pre_ids = {
                class_id
                for (inp, class_id) in PRE_COVERED
                if inp == input_name
            }

            assert gap_ids & pre_ids == set()
