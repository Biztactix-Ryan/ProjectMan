"""ProjectMan MCP server — FastMCP-based with stdio/SSE transport."""

import asyncio
from pathlib import Path
from typing import Optional, Union

import frontmatter
import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .config import find_project_root, load_config
from .event_bus import EventBus, NoOpEventBus
from .indexer import build_index, write_index
from .models import ChangesetStatus, Evidence, ProjectIndex
from .store import NOTE_SUMMARY_RECOMMENDED, NothingToCommit, Store

mcp = FastMCP("projectman")

# Lock for write operations in SSE (multi-client) mode
_write_lock = asyncio.Lock()

# Event bus — replaced with a real EventBus in SSE mode
_event_bus: EventBus | NoOpEventBus = NoOpEventBus()


def _emit(event_type: str, data: dict) -> None:
    """Fire-and-forget event emission (safe from sync tool handlers)."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_event_bus.publish(event_type, data))
    except RuntimeError:
        pass  # no event loop — stdio mode or tests


def _resolve_project_dir(project: Optional[str] = None) -> Path:
    """Return the .project/ directory for a project, handling hub layout."""
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            pm_dir = root / ".project" / "projects" / project
            if pm_dir.exists() and (pm_dir / "config.yaml").exists():
                return pm_dir
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    return root / ".project"


_store_cache: dict[Path, Store] = {}


def _store(project: Optional[str] = None) -> Store:
    root = find_project_root()
    if project:
        config = load_config(root)
        if config.hub:
            project_dir = root / ".project" / "projects" / project
            if project_dir.exists() and (project_dir / "config.yaml").exists():
                if project_dir not in _store_cache:
                    _store_cache[project_dir] = Store(root, project_dir=project_dir)
                return _store_cache[project_dir]
            raise FileNotFoundError(f"Project '{project}' not found in hub")
    default_dir = root / ".project"
    if default_dir not in _store_cache:
        _store_cache[default_dir] = Store(root)
    return _store_cache[default_dir]


def _note_truncation_fields(store: Store, note: Optional[str]) -> dict:
    """Consume the run-log truncation record left behind by ``store.update``.

    ``Store.last_note_truncation`` is per-instance mutable state and Stores are
    cached in ``_store_cache`` for the life of the process, so the record from
    one call outlives that call.  Two guards keep a later response honest:

    1. It is only read when *this* call actually supplied a note.
    2. It is cleared on the way out, so nothing can re-report it.

    Returns the response fields to merge, and deliberately returns ``{}`` when
    the note fitted: absence means "not truncated".  Emitting the fields only
    on the truncated path keeps the common response byte-for-byte the size it
    was — response bytes are a tracked cost for this epic, see
    docs/telemetry/baseline-pre-fix.md (median 341 bytes per call, and only
    ~13% of real notes exceed the old cap at all).

    Every tool that writes a run-log note merges this result into its response
    the same way — ``pm_update``, ``pm_release`` and ``pm_done_next`` — so the
    flag means the same thing wherever a note can be sent.
    """
    record = store.last_note_truncation if note is not None else None
    store.last_note_truncation = None
    if not record or not record.get("truncated"):
        return {}
    return {
        "note_truncated": True,
        "note_original_length": record["original_length"],
        "note_stored_length": record["stored_length"],
        "note_dropped_chars": record["dropped_chars"],
        "note_limit": record["limit"],
    }


def _evidence_clamp_fields(store: Store, evidence: object) -> dict:
    """Consume the clamp record left behind by ``store.update``.

    The sibling of :func:`_note_truncation_fields`, with the same two guards
    (only read when *this* call supplied evidence; cleared on the way out)
    and the same rule: ``{}`` when nothing was clamped, so absence means the
    evidence was stored whole.
    """
    record = store.last_evidence_clamp if evidence is not None else None
    store.last_evidence_clamp = None
    if not record or not record.get("clamped"):
        return {}
    return {"evidence_clamped": True, "evidence_dropped": record["dropped"]}


def _note_length_fields(note: object, evidence: object) -> dict:
    """Advise — never enforce — the one-line note length when evidence is present.

    Once the lists live in ``evidence`` the note is meant to be a one-line
    human summary, so a long one alongside evidence is a signal the caller is
    still packing structure into prose.  Advisory only: no error, no extra
    truncation (the 4096-char cap is unchanged), and absent entirely unless
    both conditions hold, so the common response keeps its size.
    """
    if evidence is None or not isinstance(note, str):
        return {}
    if len(note) <= NOTE_SUMMARY_RECOMMENDED:
        return {}
    return {
        "note_long": True,
        "note_length": len(note),
        "note_recommended": NOTE_SUMMARY_RECOMMENDED,
    }


def _evidence_arg(evidence: object) -> Optional[Evidence]:
    """Normalise the wire-shaped ``evidence`` argument into an ``Evidence``.

    Declared loosely on the tools (``Optional[dict]``) and validated here, per
    ``docs/reference/evidence-contract.md`` §3's named fallback: identical
    wire shape and identical validation, without depending on a nested
    pydantic-model annotation surviving every client's schema handling.
    """
    if evidence is None:
        return None
    if isinstance(evidence, Evidence):
        return evidence
    return Evidence.model_validate(evidence)


#: Discriminator value carried by every expected-negative response.  A caller
#: that does not know a particular ``status`` code can still tell "the call
#: worked, the answer is no" from "the call failed" by testing this one field.
EXPECTED_NEGATIVE = "expected_negative"


def _expected_negative(status: str, message: str, **detail) -> str:
    """Render an *expected negative* — a valid negative answer, not a failure.

    Some questions have a legitimate "no": a task that is not ready to grab,
    an optional document that was never written, a commit with nothing to
    commit.  The call did exactly what it was asked to do; the answer is just
    negative.  These must therefore be **successful** responses — no
    ``is_error``, and no body beginning with ``error:`` (the two markers
    ``tools/usage_telemetry/classify.py`` counts as failures).  Contrast
    ``_expected_negative`` with a genuine failure, which raises so ``is_error``
    is set (US-PM-2-3).

    One shape is used for all of them so callers branch on structure, never on
    prose::

        outcome: expected_negative   # the discriminator — always this literal
        status: not_ready            # machine-readable reason code, snake_case
        message: task is not ready to grab   # human-readable; never parse it
        blockers:                    # optional per-tool detail, unchanged
          - task has no point estimate

    ``status`` is the field to branch on.  Codes in use: ``not_ready`` and
    ``already_claimed`` (``pm_grab``), ``not_created`` (``pm_docs``),
    ``nothing_to_commit`` (``pm_commit``).  ``not_ready`` and
    ``already_claimed`` are deliberately distinct because their recoveries
    differ: ``not_ready`` means *this task needs fixing*, ``already_claimed``
    means *this task is fine, take a different one*.
    The already-correct negatives in ``pm_web_start`` /
    ``pm_web_stop`` / ``pm_web_status`` (``already_running``, ``not_running``,
    ``running: false``) predate this helper and use the same ``status`` key
    with the same meaning.

    Detail fields are passed through verbatim and are the reason this is a
    superset of the old response rather than a replacement: ``pm_grab``'s
    ``blockers`` list is the caller's whole recovery path and must survive.
    Nothing beyond the three fixed keys is added — response bytes are a tracked
    cost for this epic (docs/telemetry/baseline-pre-fix.md).

    Ported (was inventory §7.1): ``pm_done_next``'s ``next: null`` result is the
    same kind of answer (89 of 413 observed calls, carrying a ``next_info``
    hint) and now carries this shape — ``status: no_next_task`` with the hint
    kept as a detail field.  See docs/reference/error-paths-inventory.md §7.1.
    """
    return _yaml_dump(_expected_negative_payload(status, message, **detail))


def _expected_negative_payload(status: str, message: str, **detail) -> dict:
    """The dict behind `_expected_negative`, for callers that compose it.

    `_do_grab` returns a dict its callers branch on structurally (`pm_done_next`
    tests for a "grabbed" key), so it cannot return the rendered string.  Both
    spellings therefore build the payload here — one shape, two renderings.
    """
    return {
        "outcome": EXPECTED_NEGATIVE,
        "status": status,
        "message": message,
        **detail,
    }


def _failed(exc: Exception) -> ToolError:
    """Turn a caught exception into a real MCP error (US-PM-2-3).

    The counterpart to :func:`_expected_negative`.  A genuine failure is one
    where the tool did not do what it was asked; the caller must be able to see
    that without parsing prose.  Returning ``f"error: {e}"`` produced a
    *successful* result whose body happened to start with ``error:`` — invisible
    to every transport-level metric, which is the whole subject of US-PM-2.

    ``ToolError`` is FastMCP's own signal: anything raised out of a tool body is
    wrapped by ``mcp.server.fastmcp.tools.base.Tool.run`` and rendered by the
    low-level server as a ``CallToolResult`` with ``isError=True``, so the
    caller sees a hard error.  We raise it explicitly rather than letting the
    original exception escape so that (a) the message is exactly the text that
    used to be in the body — nothing the caller relied on is lost — and (b) one
    exception type covers every converted site, which is what US-PM-2-5 asserts
    against.

    Use ``raise _failed(e) from e`` so the original traceback stays attached for
    server-side logs.  For a failure detected without an exception, raise
    ``ToolError("...")`` directly.

    Ported (was inventory §7.1): ``pm_done_next``'s own copy of the generic
    ``except Exception as e: return f"error: {e}"`` handler is a GENUINE FAILURE
    site and now raises through this helper like every other one.  See
    docs/reference/error-paths-inventory.md 7.1.
    """
    return ToolError(str(exc) or exc.__class__.__name__)


def _resolve_id(
    canonical_name: str,
    canonical_value: object,
    *,
    required: bool = True,
    **aliases: object,
) -> Optional[str]:
    """Resolve one ID argument that has more than one accepted spelling (US-PM-3).

    The API grew two conventions for the same thing — the generic ``id``
    (``pm_get``, ``pm_update``, ``pm_archive``, ``pm_epic``, ``pm_estimate``,
    ``pm_scope``, ``pm_run_log``, ``pm_fix_malformed``) and a typed one
    (``task_id`` on ``pm_grab``, ``sprint_id`` on ``pm_get_sprint`` /
    ``pm_update_sprint``) — and callers guess wrong in both directions often
    enough to be one of the largest measured hard-error classes in the corpus.
    This is the single mechanism that makes both spellings work; no tool is
    meant to hand-roll its own.

    Usage is one line at the top of a tool body — the tool declares its
    canonical parameter name and every alias it accepts::

        task_id = _resolve_id("task_id", task_id, id=id)     # pm_grab
        sprint_id = _resolve_id("sprint_id", sprint_id, id=id)  # pm_get_sprint
        id = _resolve_id("id", id, task_id=task_id)          # pm_get

    The canonical value wins whenever the values agree, so nothing downstream
    ever sees an alias.  The rules, all of them deliberate:

    * **Canonical only** — the pre-existing behaviour, unchanged.
    * **Alias only** — resolves to the alias's value.  This is the whole point.
    * **Both, same value** — *not* an error.  It is unambiguous, so failing it
      would reject a call that says exactly what it wants; the model belt-and-
      braces this shape (Study B's census shows repeated keys), and refusing it
      would trade one error class for another.  Compared after stripping, so
      ``" US-A "`` and ``"US-A"`` agree.
    * **Both, different values** — a GENUINE FAILURE.  There is no safe guess:
      picking either one silently acts on an item the caller did not name.  It
      raises :class:`ToolError`, so ``is_error`` is set on the wire per
      US-PM-2's convention — it must never become an ``error:`` body.
    * **Neither** — the missing-argument failure.  Aliasing forces the
      canonical parameter to be optional in the signature (otherwise passing
      only the alias could not typecheck), which moves this check out of
      FastMCP's schema validation and into here.  Same outcome for the caller:
      a hard error naming the argument, now naming its aliases too.
    * **Empty or whitespace-only** values count as *not supplied* anywhere they
      appear, so ``id=""`` alongside ``task_id="US-A"`` resolves to ``US-A``
      rather than silently winning with nothing (and two blank spellings are
      the missing-argument error, not a conflict between two empties).

    ``required=False`` covers the tools whose ID is an optional *filter* rather
    than the operand — ``pm_activity``'s ``item_id`` (omit to see everything),
    ``pm_changeset_status``'s ``changeset_id`` (omit to list all).  Only the
    "neither" rule changes: it returns ``None`` instead of raising, so omitting
    the argument keeps meaning "no filter".  A conflict is still a conflict —
    two different filters are as unanswerable as two different operands.

    Values are returned stripped: an ID never legitimately carries surrounding
    whitespace, and a stray space is exactly the kind of thing that turns an
    alias fix into a "not found".

    NOT EVERY ``*_id`` PARAMETER IS AN ALIAS CANDIDATE (US-PM-3-6).  Several
    tools already spend a typed name on a *different* argument — a parent or a
    link, not the item being acted on:

    * ``pm_update(epic_id=...)``   links a story **to** an epic
    * ``pm_create_story(epic_id=...)``            — same
    * ``pm_create_task(story_id=...)`` / ``pm_create_tasks`` — the parent story
    * ``pm_fix_malformed(story_id=...)``          — the parent story

    Aliasing those onto the operand would silently retarget real calls: the
    corpus contains ``pm_update(id=..., epic_id=...)`` with two *deliberately*
    different values, which an alias would turn into a "conflicting ids"
    failure.  Hence ``pm_update``'s alias is ``task_id`` and never ``epic_id``.

    ``pm_fix_malformed`` is left un-aliased for the same reason plus one more:
    its ``id`` sits between required parameters, so making it optional would
    also have to drop ``title``/``item_type`` out of ``required`` and weaken
    the schema validation of a repair tool that has zero calls in the corpus.

    ``pm_done_next`` — the single busiest ``task_id`` tool in the corpus (432
    calls) — gets the same one-line treatment: it resolves ``task_id`` against
    an ``id`` alias like every other task-operand tool.
    """
    supplied: list[tuple[str, object]] = []
    for name, value in ((canonical_name, canonical_value), *aliases.items()):
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue  # empty/whitespace-only is "not supplied", not a value
        supplied.append((name, value))

    if not supplied:
        if not required:
            return None
        if aliases:
            spellings = ", ".join(aliases)
            label = "alias" if len(aliases) == 1 else "aliases"
            raise ToolError(f"{canonical_name} is required ({label}: {spellings})")
        raise ToolError(f"{canonical_name} is required")

    if len({value for _, value in supplied}) > 1:
        given = " and ".join(f"{name}={value!r}" for name, value in supplied)
        spellings = ", ".join([canonical_name, *aliases])
        raise ToolError(
            f"conflicting ids: {given} — {spellings} are different spellings of the "
            f"same argument, so they cannot name different items. Pass one of them "
            f"(canonical: {canonical_name}), or pass the same value for both."
        )

    return supplied[0][1]  # type: ignore[return-value]


def _raise_on_hub_error(result):
    """Convert ``hub/registry.py``'s in-band error reporting into a real error.

    ``registry.py`` reports failure *inside* its return value — a ``dict`` with
    a truthy ``error`` key, or a ``str`` beginning with ``error:`` — and the CLI
    depends on that contract.  So the conversion happens here, at the MCP
    boundary, rather than at the 27 return sites themselves: three call-site
    guards (``pm_push``, ``pm_push_all``, ``pm_repair``) cover all of them and
    leave the CLI untouched.  See docs/reference/error-paths-inventory.md 4.

    Why the three shapes below are the complete set for those 27 sites:

    * ``repair`` returns a bare string, ``error: not a hub project — ...``.
    * ``registry.pm_push`` puts ``error`` at the top level, and folds
      ``push_hub``'s error (which itself folds ``hub_push_with_rebase``'s) and
      ``_push_subproject``'s error up into that same key.
    * ``coordinated_push`` has no top-level ``error``; its "not a hub project"
      case is carried in ``report``, and a failed hub push in ``hub_result``.

    ``sub_result`` is deliberately *not* inspected.  A subproject failing while
    the hub push succeeds is a genuine partial success, and a caller must not
    lose the projects that did push — the same reasoning the inventory applies
    to multi-id results in 7.2.

    Returns *result* unchanged when it reports no failure, so it can be used
    inline.
    """
    if isinstance(result, str):
        stripped = result.lstrip()
        if stripped.startswith("error:"):
            raise ToolError(stripped[len("error:") :].strip())
        return result
    if isinstance(result, dict):
        if result.get("error"):
            raise ToolError(str(result["error"]))
        report = result.get("report")
        if isinstance(report, str) and report.lstrip().startswith("error:"):
            raise ToolError(report.lstrip()[len("error:") :].strip())
        hub_result = result.get("hub_result")
        if isinstance(hub_result, dict) and hub_result.get("error"):
            raise ToolError(str(hub_result["error"]))
    return result


def _no_such_malformed_file(malformed_dir: Path, filename: str) -> str:
    """Message for a mutation whose target file is not in the quarantine.

    A genuine failure, not a lookup that came back empty (inventory 5.3): the
    caller asserted the file exists by asking for it to be fixed or restored,
    so silently succeeding would let an orchestrator believe it had drained the
    malformed queue when it had not.  The current listing is included so the
    caller can recover in one turn instead of having to call ``pm_malformed``.
    """
    try:
        available = sorted(p.name for p in malformed_dir.iterdir() if p.is_file())
    except OSError:
        available = []
    listing = ", ".join(available) if available else "(none)"
    return f"{filename} not found in malformed/. Available: {listing}"


def _emit_status_change(
    store: Store, item_id: str, old_status: str, new_status: str, meta: object
) -> None:
    """Emit the appropriate event(s) for a status change."""
    from .models import TaskFrontmatter, StoryFrontmatter

    if isinstance(meta, TaskFrontmatter):
        _emit(
            "task.status_update",
            {
                "taskId": item_id,
                "oldStatus": old_status,
                "newStatus": new_status,
                "storyId": meta.story_id,
            },
        )
        # Check if all tasks in the story are now done
        if new_status == "done":
            # An archived sibling is abandoned work — it will never reach
            # "done", so waiting on it would keep the story open forever.
            siblings = store.list_tasks(story_id=meta.story_id, archived=False)
            if siblings and all(t.status.value == "done" for t in siblings):
                try:
                    story_meta, _ = store.get_story(meta.story_id)
                    _emit(
                        "story.completed",
                        {
                            "storyId": meta.story_id,
                            "epicId": story_meta.epic_id or "",
                            "title": story_meta.title,
                        },
                    )
                except FileNotFoundError:
                    pass
    elif isinstance(meta, StoryFrontmatter):
        _emit(
            "story.advanced",
            {
                "storyId": item_id,
                "oldStatus": old_status,
                "newStatus": new_status,
                "epicId": meta.epic_id or "",
            },
        )
    else:
        _emit(
            "project.updated",
            {"summary": f"Epic {item_id} status: {old_status} -> {new_status}"},
        )


def _yaml_dump(data) -> str:
    # allow_unicode avoids 6-char \uXXXX escapes; a large width avoids
    # backslash-continuation line wrapping — both waste client tokens
    return yaml.dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10000,
    )


#: Top-level sections of a ``pm_grab`` payload.  Named in a ``fields``
#: projection they are returned whole; unnamed ones are omitted.  Listed
#: explicitly (rather than read off the payload) so ``warnings`` — which is
#: omitted when there is nothing to warn about — is still a *valid* name.
GRAB_SECTIONS = (
    "task",
    "body",
    "story_context",
    "sibling_tasks",
    "sibling_tasks_total",
    "sibling_tasks_done",
    "dependency_status",
    "warnings",
)


#: The fixed ``brief=True`` projection for items — epics, stories and tasks
#: (US-PM-10-7).  These are the keys a planner or orchestrator scans a whole
#: backlog *for*: identity, state, size and wiring.  Everything heavy and
#: free-text — ``body``, ``acceptance_criteria``, any run log — is dropped,
#: which is where essentially all of the bytes are.  Not every key exists on
#: every type (an epic has no ``story_id``, a story no ``assignee``); the set
#: is intersected with the item, never demanded of it.
BRIEF_ITEM_FIELDS = (
    "id",
    "title",
    "status",
    "points",
    "priority",
    "story_id",
    "epic_id",
    "assignee",
    "tags",
    "depends_on",
)

#: The fixed ``brief=True`` projection for sprints (US-PM-10-7): identity,
#: state, dates, the points rollup and the planned story IDs.  ``goal`` is the
#: dropped one — it is a paragraph of prose per sprint, and a list of four
#: completed sprints is mostly goals by weight.
BRIEF_SPRINT_FIELDS = (
    "id",
    "name",
    "status",
    "start_date",
    "end_date",
    "planned_points",
    "completed_points",
    "planned_stories",
)


def _brief_item(item: dict, keys: tuple[str, ...]) -> dict:
    """Keep only the brief keys an item actually has, in the item's own order.

    Intersection, not selection: a missing key is simply absent from the
    result rather than an error, so one preset serves epics, stories and
    tasks alike.
    """
    wanted = set(keys)
    return {k: v for k, v in item.items() if k in wanted}


def _field_names(fields: Optional[str]) -> Optional[list[str]]:
    """Parse a comma-separated ``fields`` argument (US-PM-10-6).

    Returns ``None`` for "no projection requested" — ``None``, ``""`` and a
    string of nothing but separators and whitespace all mean the same thing,
    and all leave the response byte-identical to the unprojected one.
    Whitespace around each name is stripped; duplicates are harmless.
    """
    if fields is None:
        return None
    names = [n.strip() for n in fields.split(",") if n.strip()]
    return names or None


def _reject_unknown_fields(names: list[str], valid: list[str], label: str) -> None:
    """Fail loudly on a field name that does not exist (US-PM-10-6).

    A silent empty projection is the dangerous outcome here: the orchestrator's
    verification read exists to *distrust* a worker's self-report, and a typo'd
    field name that quietly returned nothing would make that check vacuous
    while still looking like it passed.  So an unknown name is a GENUINE
    FAILURE, and the message carries the valid names for the item at hand.
    """
    unknown = [n for n in dict.fromkeys(names) if n not in set(valid)]
    if unknown:
        raise ToolError(
            f"unknown field name(s) for {label}: {', '.join(unknown)} — "
            f"valid names: {', '.join(valid)}"
        )


def _project_item(
    item: dict,
    names: list[str],
    label: str,
    extra_valid: tuple[str, ...] = (),
) -> dict:
    """Keep only the requested keys of one serialized item.

    ``id`` is always kept so a multi-ID result stays addressable — a list of
    bare ``status`` values would not tell the caller which item each belonged
    to.  Key order follows the item, not the request.
    """
    valid = list(item.keys()) + [k for k in extra_valid if k not in item]
    _reject_unknown_fields(names, valid, label)
    keep = set(names) | {"id"}
    return {k: v for k, v in item.items() if k in keep}


def _project_grabbed(grabbed: dict, names: list[str]) -> dict:
    """Project a ``pm_grab`` payload: task keys by name, sections by name.

    A named section (``body``, ``story_context``, ``sibling_tasks``, …) comes
    back whole; an unnamed one is dropped.  Everything else is read as a key of
    the ``task`` dict, which is always present and always carries ``id``.  So
    ``fields="status,assignee"`` yields ``{task: {id, status, assignee}}`` and
    nothing more.  Projection is output-only — the claim itself already
    happened and is unaffected.
    """
    task = grabbed.get("task", {})
    valid = list(dict.fromkeys(list(GRAB_SECTIONS) + list(task.keys())))
    _reject_unknown_fields(names, valid, "pm_grab")
    wanted = set(names)
    if "task" in wanted:
        projected_task = task
    else:
        keep = wanted | {"id"}
        projected_task = {k: v for k, v in task.items() if k in keep}
    out = {"task": projected_task}
    for key, value in grabbed.items():
        if key != "task" and key in wanted:
            out[key] = value
    return out


#: Acceptance criteria are the one list-shaped input on this surface whose
#: entries are natural language, so — unlike tags, ids or field names — a
#: comma inside one is ordinary punctuation, not a separator.  US-PM-18: the
#: old ``.split(",")`` shredded "Given a user, when they log in, then the
#: dashboard loads" into three bogus criteria, and since every criterion
#: auto-generates a test task, into three bogus tasks as well.
def _criteria_list(
    value: Union[str, list[str], None],
) -> Optional[list[str]]:
    """Normalise an ``acceptance_criteria`` argument to a list of criteria.

    A list is one criterion per entry.  A bare string is exactly ONE
    criterion, whatever punctuation it contains — it is never split.

    Note on JSON-encoded strings: a client that sends a *string* holding a
    JSON array (``'["a", "b"]'``) never reaches here holding one — FastMCP's
    ``pre_parse_json`` decodes it into a real list before the tool is called,
    because the annotation is not a bare ``str``.  Called directly from
    Python, such a string is taken at face value: one criterion.

    Entries are stripped, and blank ones dropped: a blank criterion breeds
    an unparseable test-task body (see US-PM-5-8) and expresses nothing.  An
    empty string or empty list therefore means "no criteria" — on pm_update,
    that clears them.  ``None`` means "not supplied" and is passed through.
    """
    if value is None:
        return None
    entries = [value] if isinstance(value, str) else list(value)
    return [str(entry).strip() for entry in entries if str(entry).strip()]


# ─── Query Tools ────────────────────────────────────────────────


@mcp.tool(
    title="Project Status",
    annotations=ToolAnnotations(title="Project Status", readOnlyHint=True),
)
def pm_status(project: Optional[str] = None) -> str:
    """Get project status summary: story/task counts, points, completion percentage.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        index = build_index(store)
        pct = 0
        if index.total_points > 0:
            pct = round(index.completed_points / index.total_points * 100)

        # Group by status.  An archived task keeps the status it had when work
        # stopped, so reporting that status would file abandoned work under
        # "todo" (still owed) or "done" (delivered).  Neither is true.
        status_groups = {}
        for entry in index.entries:
            key = "archived" if entry.archived else entry.status
            status_groups.setdefault(key, []).append(entry)

        # Changeset summary
        changesets = store.list_changesets()
        cs_by_status = {}
        for cs in changesets:
            cs_by_status.setdefault(cs.status.value, 0)
            cs_by_status[cs.status.value] += 1

        result = {
            "project": store.config.name,
            "epics": index.epic_count,
            "stories": index.story_count,
            "tasks": index.task_count,
            "total_points": index.total_points,
            "completed_points": index.completed_points,
            "completion": f"{pct}%",
            "by_status": {k: len(v) for k, v in status_groups.items()},
            "changesets": len(changesets),
            "changesets_by_status": cs_by_status,
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Get Item", annotations=ToolAnnotations(title="Get Item", readOnlyHint=True)
)
def pm_get(
    id: Optional[str] = None,
    include_log: bool = False,
    project: Optional[str] = None,
    task_id: Optional[str] = None,
    fields: Optional[str] = None,
) -> str:
    """Get full details of epics, stories, or tasks by ID. Accepts multiple comma-separated IDs — always fetch related items in one call instead of repeated single-ID calls.

    Pass `fields` when you only need a few keys — a verification read after a
    worker reports done is `pm_get(task_id, fields="status,assignee")`, which
    costs a small fraction of the full item.

    Args:
        id: One or more comma-separated IDs — epic (e.g. EPIC-PRJ-1), story (e.g. US-PRJ-1), or task (e.g. US-PRJ-1-1,US-PRJ-1-2) (alias: task_id)
        include_log: Include the 3 most recent run-log entries per item (default false; use pm_run_log for full history)
        project: Optional project name (hub mode only)
        task_id: Alias for id — either spelling works; passing both with different values is an error
        fields: Comma-separated key names to return, e.g. "status,assignee" — everything else is omitted (`id` is always kept so multi-ID results stay addressable). Names are the item's own keys: status, assignee, points, title, story_id, depends_on, tags, body, acceptance_criteria, recent_run_log, … An unknown name is an error listing the valid ones. Omit for the full item — the default is unchanged.
    """
    try:
        id = _resolve_id("id", id, task_id=task_id)
        store = _store(project)
        names = _field_names(fields)

        def _fetch(item_id: str) -> dict:
            meta, body = store.get(item_id)
            result = meta.model_dump(mode="json")
            result["body"] = body
            # Don't pay for the run log and then project it away.
            if include_log and (names is None or "recent_run_log" in names):
                recent_log = store.get_run_log(item_id, limit=3)
                if recent_log:
                    # A compact marker, never the evidence object: pm_get is
                    # the high-frequency context call, and embedding evidence
                    # here spends the exact budget it was added to defend.
                    # Full detail is one pm_run_log away.
                    entries = []
                    for e in recent_log:
                        dumped = e.model_dump(mode="json", exclude={"evidence"})
                        dumped["has_evidence"] = e.evidence is not None
                        if e.evidence is not None:
                            dumped["evidence_summary"] = e.evidence.summary()
                        entries.append(dumped)
                    result["recent_run_log"] = entries
            if names is None:
                return result
            if store._is_epic_id(item_id):
                kind = "epic"
            elif store._is_task_id(item_id):
                kind = "task"
            else:
                kind = "story"
            return _project_item(
                result, names, kind, extra_valid=("recent_run_log",)
            )

        item_ids = [i.strip() for i in id.split(",") if i.strip()]
        if len(item_ids) == 1:
            return _yaml_dump(_fetch(item_ids[0]))
        items = []
        for item_id in item_ids:
            try:
                items.append(_fetch(item_id))
            except ToolError:
                # A bad field name is the caller's mistake about the whole
                # call, not a per-item "not found" — it must not be buried in
                # one item's `error` key while the others look fine.
                raise
            except Exception as e:
                items.append({"id": item_id, "error": str(e)})
        return _yaml_dump(items)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Batch Get Items",
    annotations=ToolAnnotations(title="Batch Get Items", readOnlyHint=True),
)
def pm_batch_get(
    type: Optional[str] = None,
    ids: Optional[str] = None,
    project: Optional[str] = None,
    brief: bool = False,
    fields: Optional[str] = None,
) -> str:
    """Get every item of a type (or a specific ID list) with full data in a single call.

    This is a list-*everything* call, so it is the most expensive read on the
    surface: a backlog of stories comes back with every body and every
    acceptance criterion. When you are scanning rather than reading, say so —
    `pm_batch_get(type="stories", brief=True)` returns identity, state, size
    and wiring only, a small fraction of the bytes. `fields` gives the same
    per-key control as `pm_get` when the preset is not the cut you want.

    Args:
        type: Fetch all items of a type: "epics", "stories", or "tasks"
        ids: Comma-separated item IDs to fetch (e.g. "US-PRJ-1,US-PRJ-2-3,EPIC-PRJ-1"). Takes precedence over type.
        project: Optional project name (hub mode only)
        brief: Drop the heavy free-text (default false). Keeps whichever of id, title, status, points, priority, story_id, epic_id, assignee, tags, depends_on the item type has, and omits body, acceptance_criteria and any run log. Use it to scan a backlog: pm_batch_get(type="stories", brief=True).
        fields: Comma-separated key names to return, e.g. "status,points" — everything else is omitted and `id` is always kept, exactly as on pm_get. An unknown name is an error listing the valid ones. If both are given, `fields` wins — explicit beats preset. Omit both for the full items; the default is unchanged.
    """
    try:
        store = _store(project)
        names = _field_names(fields)

        def _shape(item: dict, kind: str) -> dict:
            # Explicit beats preset: a caller who named keys gets exactly
            # those, whatever `brief` says.
            if names is not None:
                # Valid names are the item's own keys, exactly as on pm_get —
                # so `fields` means the same thing on both tools.
                return _project_item(item, names, kind)
            if brief:
                return _brief_item(item, BRIEF_ITEM_FIELDS)
            return item

        if ids:
            items = []
            for item_id in [i.strip() for i in ids.split(",") if i.strip()]:
                try:
                    meta, body = store.get(item_id)
                    item = meta.model_dump(mode="json")
                    item["body"] = body
                    if store._is_epic_id(item_id):
                        kind = "epic"
                    elif store._is_task_id(item_id):
                        kind = "task"
                    else:
                        kind = "story"
                    items.append(_shape(item, kind))
                except ToolError:
                    # A bad field name is the caller's mistake about the whole
                    # call, not one item's "not found" — it must not be buried
                    # in an `error` key while the other items look fine.
                    raise
                except Exception as e:
                    items.append({"id": item_id, "error": str(e)})
            return _yaml_dump(items)
        if not type:
            raise ToolError("provide ids or type")
        items = store.list_all(type)
        kind = {"epics": "epic", "stories": "story", "tasks": "task"}.get(
            type, "item"
        )
        return _yaml_dump([_shape(item, kind) for item in items])
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Read Documentation",
    annotations=ToolAnnotations(title="Read Documentation", readOnlyHint=True),
)
def pm_docs(doc: Optional[str] = None, project: Optional[str] = None) -> str:
    """Read project documentation files.

    Args:
        doc: Specific doc to read: "project", "infrastructure", "security", "vision", "architecture", or "decisions". Omit for a summary of all.
        project: Optional project name (hub mode only)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        doc_map = {
            "project": "PROJECT.md",
            "infrastructure": "INFRASTRUCTURE.md",
            "security": "SECURITY.md",
            "vision": "VISION.md",
            "architecture": "ARCHITECTURE.md",
            "decisions": "DECISIONS.md",
        }

        if doc:
            filename = doc_map.get(doc.lower())
            if not filename:
                raise ToolError(
                    f"unknown doc '{doc}'. Use: project, infrastructure, security, vision, architecture, or decisions"
                )
            path = proj_dir / filename
            if not path.exists():
                # Expected negative, not a failure: the six ProjectMan
                # documents are optional by design, so this is a lookup over
                # an optional set that legitimately came back empty.  (An
                # unknown *doc name* — the branch above — is a real argument
                # error and stays one.)
                return _expected_negative(
                    "not_created",
                    f"{filename} has not been created in this project",
                    doc=doc.lower(),
                    file=filename,
                )
            return path.read_text()

        # Summary mode: return all docs with their status
        import os
        from datetime import date as _date

        summary = {}
        for key, filename in doc_map.items():
            path = proj_dir / filename
            if path.exists():
                content = path.read_text()
                mtime = _date.fromtimestamp(os.path.getmtime(path))
                age = (_date.today() - mtime).days
                lines = [
                    l
                    for l in content.splitlines()
                    if l.strip()
                    and not l.strip().startswith("<!--")
                    and not l.strip().startswith("-->")
                ]
                summary[key] = {
                    "file": filename,
                    "last_modified": str(mtime),
                    "age_days": age,
                    "content_lines": len(lines),
                    "status": "stale" if age > 30 else "current",
                }
            else:
                summary[key] = {"file": filename, "status": "missing"}
        return _yaml_dump(summary)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Update Documentation",
    annotations=ToolAnnotations(
        title="Update Documentation", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_update_doc(
    doc: str,
    content: str,
    project: Optional[str] = None,
) -> str:
    """Update a project documentation file.

    Args:
        doc: Which doc to update: "project", "infrastructure", "security", "vision", "architecture", or "decisions"
        content: The full new content for the document
        project: Optional project name (hub mode only)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        doc_map = {
            "project": "PROJECT.md",
            "infrastructure": "INFRASTRUCTURE.md",
            "security": "SECURITY.md",
            "vision": "VISION.md",
            "architecture": "ARCHITECTURE.md",
            "decisions": "DECISIONS.md",
        }

        filename = doc_map.get(doc.lower())
        if not filename:
            raise ToolError(
                f"unknown doc '{doc}'. Use: project, infrastructure, security, vision, architecture, or decisions"
            )

        path = proj_dir / filename
        path.write_text(content)
        return f"updated: {filename}"
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Active Work",
    annotations=ToolAnnotations(title="Active Work", readOnlyHint=True),
)
def pm_active(
    project: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List active/in-progress stories and tasks.

    Args:
        project: Optional project name (hub mode only)
        tag: Filter to show only items (or their parent stories) with this tag
        limit: Max items per list (default 20)
        offset: Starting index for pagination (default 0)
    """
    try:
        store = _store(project)
        all_stories = store.list_stories(status="active")
        # Archived tasks keep the status they stopped at, so an abandoned
        # in-progress task would otherwise be reported as active work.
        all_tasks = store.list_tasks(status="in-progress", archived=False)

        if tag:
            all_stories = [s for s in all_stories if tag in s.tags]
            story_cache = {s.id: s for s in store.list_stories()}
            all_tasks = [
                t
                for t in all_tasks
                if tag in t.tags
                or (
                    story_cache.get(t.story_id) is not None
                    and tag in story_cache[t.story_id].tags
                )
            ]

        stories_page = all_stories[offset : offset + limit]
        tasks_page = all_tasks[offset : offset + limit]

        result = {
            "active_stories": [s.model_dump(mode="json") for s in stories_page],
            "active_stories_total": len(all_stories),
            "active_tasks": [t.model_dump(mode="json") for t in tasks_page],
            "active_tasks_total": len(all_tasks),
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < len(all_stories)
            or (offset + limit) < len(all_tasks),
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Search Items",
    annotations=ToolAnnotations(title="Search Items", readOnlyHint=True),
)
def pm_search(
    query: str, project: Optional[str] = None, tag: Optional[str] = None
) -> str:
    """Search stories and tasks by keyword or semantic similarity.

    Args:
        query: Search query string
        project: Optional project name (hub mode only)
        tag: Optional tag to filter results (only items with this tag are returned)
    """
    try:
        proj_dir = _resolve_project_dir(project)

        # Try embeddings first, fall back to keyword
        try:
            from .embeddings import EmbeddingStore

            emb_store = EmbeddingStore(proj_dir)
            results = emb_store.search(query, top_k=10)
            if results:
                # Post-filter by tag if specified
                if tag:
                    store = Store(proj_dir)
                    filtered = []
                    for r in results:
                        try:
                            meta, _ = store.get(r.id)
                            if tag in (meta.tags if hasattr(meta, "tags") else []):
                                filtered.append(r)
                        except Exception:
                            pass
                    results = filtered
                return _yaml_dump(
                    [
                        {
                            "id": r.id,
                            "title": r.title,
                            "type": r.type,
                            "score": round(r.score, 3),
                        }
                        for r in results
                    ]
                )
        except (ImportError, Exception):
            pass

        from .search import keyword_search

        results = keyword_search(query, proj_dir, tag=tag)
        return _yaml_dump(
            [
                {
                    "id": r.id,
                    "title": r.title,
                    "type": r.type,
                    "score": r.score,
                    "snippet": r.snippet,
                }
                for r in results
            ]
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Task Board",
    annotations=ToolAnnotations(title="Task Board", readOnlyHint=True),
)
def pm_board(
    project: Optional[str] = None,
    assignee: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Show the task board — available tasks grouped by status and readiness.

    Args:
        project: Optional project name (hub mode only)
        assignee: Filter to show only tasks for this assignee
        tag: Filter to show only tasks (or their parent stories) with this tag
        limit: Max items per board group (default 10). Totals are always shown.
    """
    try:
        from .readiness import check_readiness, compute_hints
        from .deps import topological_sort

        store = _store(project)
        # Archived tasks are abandoned, not workable.  Archival used to write
        # "done", which dropped them off the board as a side effect; now that
        # they keep their real status the exclusion has to be explicit.
        all_tasks = store.list_tasks(archived=False)

        # Build a story lookup for priority ordering and context
        story_cache = {}
        for story in store.list_stories():
            story_cache[story.id] = story

        # Build topological position map per story for dependency-aware ordering
        story_tasks: dict[str, list] = {}
        for task in all_tasks:
            story_tasks.setdefault(task.story_id, []).append(task)
        topo_position: dict[str, int] = {}
        for sid, tasks_in_story in story_tasks.items():
            try:
                sorted_tasks = topological_sort(tasks_in_story)
            except Exception:
                sorted_tasks = tasks_in_story
            for idx, t in enumerate(sorted_tasks):
                topo_position[t.id] = idx

        available = []
        not_ready = []
        in_progress = []
        in_review = []
        blocked = []

        for task in all_tasks:
            _, task_body = store.get_task(task.id)
            story = story_cache.get(task.story_id)
            story_label = f"{story.id} — {story.title}" if story else task.story_id

            if assignee and task.assignee != assignee:
                continue

            if tag:
                task_has_tag = tag in task.tags
                story_has_tag = story is not None and tag in story.tags
                if not task_has_tag and not story_has_tag:
                    continue

            if task.status.value == "in-progress":
                in_progress.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "assignee": task.assignee,
                        "story": story_label,
                    }
                )
            elif task.status.value == "review":
                in_review.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "assignee": task.assignee,
                        "story": story_label,
                    }
                )
            elif task.status.value == "blocked":
                blocked.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "points": task.points,
                        "assignee": task.assignee,
                        "story": story_label,
                    }
                )
            elif task.status.value == "todo" and not assignee:
                readiness = check_readiness(task, task_body, store)
                if readiness["ready"]:
                    hints = compute_hints(task, task_body)
                    priority_order = {"must": 0, "should": 1, "could": 2, "wont": 3}
                    story_priority = priority_order.get(
                        story.priority.value if story else "should", 1
                    )
                    available.append(
                        {
                            "id": task.id,
                            "title": task.title,
                            "points": task.points,
                            "story": story_label,
                            "hints": hints,
                            "_sort": (
                                story_priority,
                                task.story_id,
                                topo_position.get(task.id, 0),
                                task.points or 99,
                            ),
                        }
                    )
                else:
                    not_ready.append(
                        {
                            "id": task.id,
                            "title": task.title,
                            "points": task.points,
                            "story": story_label,
                            "blockers": readiness["blockers"],
                        }
                    )

        # Sort available tasks by priority > story > topological order > points
        available.sort(key=lambda t: t["_sort"])
        for t in available:
            del t["_sort"]

        result = {
            "board": {
                "available": available[:limit],
                "not_ready": not_ready[:limit],
                "in_progress": in_progress[:limit],
                "in_review": in_review[:limit],
                "blocked": blocked[:limit],
            },
            "summary": {
                "available": len(available),
                "not_ready": len(not_ready),
                "in_progress": len(in_progress),
                "in_review": len(in_review),
                "blocked": len(blocked),
            },
            "limit": limit,
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Burndown Data",
    annotations=ToolAnnotations(title="Burndown Data", readOnlyHint=True),
)
def pm_burndown(project: Optional[str] = None) -> str:
    """Get burndown data: total vs completed points.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        # Hub mode: aggregate across projects
        if config.hub and not project:
            try:
                from .hub.rollup import rollup

                data = rollup(root)
                return _yaml_dump(data)
            except (ImportError, Exception):
                pass

        store = _store(project)
        index = build_index(store)

        remaining = index.total_points - index.completed_points
        result = {
            "project": store.config.name,
            "total_points": index.total_points,
            "completed_points": index.completed_points,
            "remaining_points": remaining,
            "completion": f"{round(index.completed_points / max(index.total_points, 1) * 100)}%",
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


# ─── Write Tools ────────────────────────────────────────────────


@mcp.tool(
    title="Create Story",
    annotations=ToolAnnotations(
        title="Create Story", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_create_story(
    title: str,
    description: str,
    priority: Optional[str] = None,
    points: Optional[int] = None,
    epic_id: Optional[str] = None,
    acceptance_criteria: Optional[Union[str, list[str]]] = None,
    tags: Optional[str] = None,
    depends_on: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new user story.

    Args:
        title: Story title
        description: Story description ("As a [user], I want [goal] so that [benefit]")
        priority: Priority level: must, should, could, wont
        points: Story points (fibonacci: 1,2,3,5,8,13)
        epic_id: Optional parent epic ID (e.g. EPIC-PRJ-1)
        acceptance_criteria: List of acceptance criteria, one entry per criterion (e.g. ["Users can log in", "Error shown on invalid password"]). Pass a JSON list, never a comma-joined string: criteria are natural language and a comma inside one is punctuation, not a separator. A bare string is accepted and taken as exactly one criterion. Each criterion auto-generates a test task.
        tags: Comma-separated tags (e.g. "security,mvp")
        depends_on: Comma-separated dependency IDs (stories or tasks this story depends on)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        ac_list = _criteria_list(acceptance_criteria)
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        dep_list = [d.strip() for d in depends_on.split(",")] if depends_on else None
        meta, test_tasks = store.create_story(
            title,
            description,
            priority,
            points,
            tags=tag_list,
            acceptance_criteria=ac_list,
            depends_on=dep_list,
        )
        if epic_id:
            store.update(meta.id, epic_id=epic_id)
            meta, _ = store.get_story(meta.id)
        write_index(store)
        # Echo identity + non-empty settable fields, not the full object
        dumped = meta.model_dump(mode="json")
        created = {
            "id": meta.id,
            "title": meta.title,
            "status": dumped.get("status"),
        }
        for field in ("priority", "points", "epic_id", "tags", "depends_on"):
            value = dumped.get(field)
            if value:
                created[field] = value
        result = {"created": created}
        result["test_tasks"] = [
            {"id": t.id, "title": t.title} for t in (test_tasks or [])
        ]
        _emit("project.updated", {"summary": f"Story {meta.id} created"})
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Create Epic",
    annotations=ToolAnnotations(
        title="Create Epic", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_create_epic(
    title: str,
    description: str,
    priority: Optional[str] = None,
    target_date: Optional[str] = None,
    tags: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new epic for grouping related stories.

    Args:
        title: Epic title (short strategic name)
        description: Epic description (vision, success criteria, scope)
        priority: Priority level: must, should, could, wont
        target_date: Optional target date (YYYY-MM-DD)
        tags: Comma-separated tags (e.g. "security,mvp")
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        meta = store.create_epic(title, description, priority, target_date, tag_list)
        write_index(store)
        _emit("project.updated", {"summary": f"Epic {meta.id} created"})
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Epic Details",
    annotations=ToolAnnotations(title="Epic Details", readOnlyHint=True),
)
def pm_epic(
    id: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    epic_id: Optional[str] = None,
) -> str:
    """Get epic details with rollup of linked stories and tasks.

    Args:
        id: Epic ID (e.g. EPIC-PRJ-1) (alias: epic_id)
        project: Optional project name (hub mode only)
        limit: Max stories to return (default 10)
        offset: Starting index for story pagination (default 0)
        epic_id: Alias for id — either spelling works; passing both with different values is an error
    """
    try:
        id = _resolve_id("id", id, epic_id=epic_id)
        store = _store(project)
        meta, body = store.get_epic(id)

        # Find linked stories — compute rollup from ALL, paginate the detail list
        linked_stories = [s for s in store.list_stories() if s.epic_id == id]
        story_data = []
        total_points = 0
        completed_points = 0

        for i, story in enumerate(linked_stories):
            tasks = store.list_tasks(story_id=story.id)
            # Archived tasks are abandoned work: they leave the numerator and
            # the denominator alike, so the rollup neither claims them as
            # delivered nor keeps demanding them.
            counted = [t for t in tasks if not t.archived]
            story_points = sum(t.points or 0 for t in counted)
            done_points = sum(
                t.points or 0 for t in counted if t.status.value == "done"
            )
            total_points += story_points
            completed_points += done_points

            # Only include full detail for the current page
            if offset <= i < offset + limit:
                task_summary = [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status.value,
                        "points": t.points,
                    }
                    for t in tasks
                ]
                story_data.append(
                    {
                        "id": story.id,
                        "title": story.title,
                        "status": story.status.value,
                        "points": story.points,
                        "tasks": task_summary,
                        "task_points": story_points,
                        "done_points": done_points,
                    }
                )

        total_stories = len(linked_stories)
        has_more = (offset + limit) < total_stories

        result = {
            "epic": meta.model_dump(mode="json"),
            "body": body,
            "stories": story_data,
            "rollup": {
                "story_count": total_stories,
                "total_points": total_points,
                "completed_points": completed_points,
                "completion": f"{round(completed_points / max(total_points, 1) * 100)}%",
            },
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }
        if has_more:
            result["next_offset"] = offset + limit
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Project Context",
    annotations=ToolAnnotations(title="Project Context", readOnlyHint=True),
)
def pm_context(
    project: Optional[str] = None,
    limit: int = 20,
    max_doc_chars: int = 4000,
) -> str:
    """Get combined hub + project context for an agent starting work.

    Returns hub-level vision/architecture (if hub mode) plus project-specific
    docs, active epics, and active stories. Docs are truncated to max_doc_chars
    each — use pm_docs(doc=...) to read a full document.

    Args:
        project: Optional project name (hub mode only)
        limit: Max epics/stories to include (default 20)
        max_doc_chars: Max characters per embedded doc (default 4000; 0 = no limit)
    """
    try:
        hub_root = find_project_root()
        hub_config = load_config(hub_root)
        store = _store(project)
        proj_dir = store.project_dir

        def _doc_text(path, doc_key: str) -> str:
            text = path.read_text()
            if max_doc_chars and len(text) > max_doc_chars:
                return (
                    text[:max_doc_chars]
                    + f"\n…[truncated {len(text) - max_doc_chars} chars — "
                    + f'use pm_docs(doc="{doc_key}") for the full text]'
                )
            return text

        result = {}

        # Hub-level context (if hub mode)
        if hub_config.hub:
            hub_dir = hub_root / ".project"
            for doc_key, filename in [
                ("vision", "VISION.md"),
                ("architecture", "ARCHITECTURE.md"),
            ]:
                path = hub_dir / filename
                if path.exists():
                    result[f"hub_{doc_key}"] = _doc_text(path, doc_key)

        # Project-level context
        project_docs = {}
        for doc_key, filename in [
            ("project", "PROJECT.md"),
            ("infrastructure", "INFRASTRUCTURE.md"),
            ("security", "SECURITY.md"),
        ]:
            path = proj_dir / filename
            if path.exists():
                project_docs[doc_key] = _doc_text(path, doc_key)
        result["project_docs"] = project_docs

        # Active epics
        active_epics = store.list_epics(status="active")
        result["active_epics_total"] = len(active_epics)
        if active_epics:
            result["active_epics"] = [
                {"id": e.id, "title": e.title, "priority": e.priority.value}
                for e in active_epics[:limit]
            ]

        # Active stories
        active_stories = store.list_stories(status="active")
        result["active_stories_total"] = len(active_stories)
        if active_stories:
            result["active_stories"] = [
                {
                    "id": s.id,
                    "title": s.title,
                    "epic_id": s.epic_id,
                    "priority": s.priority.value,
                }
                for s in active_stories[:limit]
            ]

        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Create Task",
    annotations=ToolAnnotations(
        title="Create Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_create_task(
    story_id: str,
    title: str,
    description: str,
    points: Optional[int] = None,
    tags: Optional[str] = None,
    depends_on: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a new task under a story.

    Args:
        story_id: Parent story ID (e.g. US-PRJ-1)
        title: Task title
        description: Task description with implementation details
        points: Task points (fibonacci: 1,2,3,5,8,13)
        tags: Comma-separated tags (e.g. "backend,api")
        depends_on: Comma-separated task IDs this task depends on (e.g. "US-PRJ-1-1,US-PRJ-1-2")
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        dep_list = [d.strip() for d in depends_on.split(",")] if depends_on else None
        meta = store.create_task(
            story_id, title, description, points, tags=tag_list, depends_on=dep_list
        )
        write_index(store)
        _emit("task.created", {"taskId": meta.id, "storyId": story_id, "title": title})
        dumped = meta.model_dump(mode="json")
        created = {"id": meta.id, "title": meta.title, "story_id": story_id}
        for field in ("points", "tags", "depends_on"):
            value = dumped.get(field)
            if value:
                created[field] = value
        return _yaml_dump({"created": created})
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Batch Create Tasks",
    annotations=ToolAnnotations(
        title="Batch Create Tasks", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_create_tasks(
    story_id: str,
    tasks: list[dict],
    project: Optional[str] = None,
) -> str:
    """Create multiple tasks under a story in a single call.

    Args:
        story_id: Parent story ID (e.g. US-PRJ-1)
        tasks: List of task dicts, each with keys: title (str), description (str), points (int, optional), depends_on (list[str], optional)
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        created = store.create_tasks(story_id, tasks)
        write_index(store)
        for t in created:
            _emit(
                "task.created", {"taskId": t.id, "storyId": story_id, "title": t.title}
            )
        total_points = sum(t.points or 0 for t in created)
        created_list = []
        for t in created:
            dumped = t.model_dump(mode="json")
            entry = {"id": t.id, "title": t.title}
            for field in ("points", "tags", "depends_on"):
                value = dumped.get(field)
                if value:
                    entry[field] = value
            created_list.append(entry)
        return _yaml_dump(
            {
                "created": created_list,
                "count": len(created),
                "total_points": total_points,
            }
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Update Item",
    annotations=ToolAnnotations(
        title="Update Item", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_update(
    id: Optional[str] = None,
    status: Optional[str] = None,
    points: Optional[int] = None,
    title: Optional[str] = None,
    assignee: Optional[str] = None,
    unassign: bool = False,
    clear: Optional[str] = None,
    epic_id: Optional[str] = None,
    body: Optional[str] = None,
    acceptance_criteria: Optional[Union[str, list[str]]] = None,
    tags: Optional[str] = None,
    depends_on: Optional[str] = None,
    outcome: Optional[str] = None,
    note: Optional[str] = None,
    project: Optional[str] = None,
    task_id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Update an epic, story, or task.

    To hand a task back, prefer `pm_release(<id>)` — it clears the assignee,
    resets the status and logs the reason in one call.

    Args:
        id: Epic, story, or task ID (alias: task_id)
        status: New status (epics: draft/active/done/archived; stories: backlog/ready/active/done/archived; tasks: todo/in-progress/review/done/blocked)
        points: New point estimate (fibonacci: 1,2,3,5,8,13)
        title: New title
        assignee: Assignee name (tasks only). To remove one, pass unassign=true — never an empty assignee.
        unassign: Set true to remove the assignee (tasks only). Changes nothing else — no status reset, no run-log entry; use pm_release for that. Passing unassign=true together with a non-empty assignee is an error.
        clear: Comma-separated names of fields to reset to empty, e.g. "depends_on", "tags", "depends_on,tags". Valid names: assignee, depends_on, epic_id, points, tags. Clearing a field that is already empty succeeds. Naming a field here and also setting it in the same call is an error, as is an unknown name.
        epic_id: Link a story to an epic (stories only)
        body: New markdown body/description content
        acceptance_criteria: List of acceptance criteria, one entry per criterion (stories only, e.g. ["Users can log in", "Error shown on invalid password"]). Pass a JSON list, never a comma-joined string: criteria are natural language and a comma inside one is punctuation, not a separator. A bare string is accepted and taken as exactly one criterion; an empty list clears the criteria. Changing them reconciles the auto-generated test tasks: new criteria get a task, reworded criteria have their task retitled and rebodied, and tasks whose criterion was removed are archived if nothing has happened to them or flagged for a human if work has started. Nothing is ever deleted; archiving is reversible (Store.unarchive).
        tags: Comma-separated tags (e.g. "security,mvp,backend")
        depends_on: Comma-separated task IDs this task depends on (tasks only, e.g. "US-PRJ-1-1,US-PRJ-1-2")
        outcome: Run-log outcome (success/partial/blocked/failed/info). When provided with note, appends a run-log entry for tracking work attempts.
        note: Run-log note describing what was accomplished or what blocked progress. Longer notes are truncated server-side (4096 chars) with a visible marker, never rejected — the status/outcome write always lands. Requires outcome.
        project: Optional project name (hub mode only)
        task_id: Alias for id — either spelling works; passing both with different values is an error. Note epic_id is NOT an alias: it links a story to an epic.
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Evidence on its own appends an entry (outcome `info`, empty note) — no outcome required. Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    Response: always `updated: <item>`.  When — and only when — a supplied note
    had to be truncated, the response additionally carries `note_truncated:
    true`, `note_original_length`, `note_stored_length`, `note_dropped_chars`
    and `note_limit`, so a caller can detect truncation without string-matching.
    When editing acceptance_criteria moves test tasks, the response additionally
    carries `test_tasks:` with `created`, `resynced`, `archived` and `flagged`
    id lists, a `needs_attention` boolean (true iff `flagged` is non-empty),
    and `orphaned:` detailing each removed criterion's task — `action`
    (`archive` or `flag`) and `work_reasons` (codes such as `assigned`,
    `run-log-entries`, `status-not-todo`) so the caller branches without
    reading prose.  Nothing is ever deleted.
    """
    try:
        # epic_id is deliberately absent here — on this tool it is the epic a
        # story is being linked to, not another spelling of the item's own id.
        id = _resolve_id("id", id, task_id=task_id)
        store = _store(project)
        # Capture old status before update for event emission
        old_status_val = None
        if status is not None:
            try:
                old_meta, _ = store.get(id)
                old_status_val = (
                    old_meta.status.value
                    if hasattr(old_meta.status, "value")
                    else str(old_meta.status)
                )
            except Exception:
                pass

        kwargs = {}
        if status is not None:
            kwargs["status"] = status
        if points is not None:
            kwargs["points"] = points
        if title is not None:
            kwargs["title"] = title
        if assignee is not None:
            kwargs["assignee"] = assignee
        if unassign:
            # A contradiction, not a precedence question: silently letting one
            # win would turn a release into an assignment (or the reverse).
            if assignee:
                raise ToolError(
                    "conflicting instruction: unassign=true was given together with "
                    f"assignee={assignee!r}; pass one or the other"
                )
            # "" is normalised to None by Store.update — the legacy sentinel,
            # still accepted there, is now spelled by this boolean instead.
            kwargs["assignee"] = ""
        clear_fields = (
            [name.strip() for name in clear.split(",") if name.strip()] if clear else []
        )
        if epic_id is not None:
            kwargs["epic_id"] = epic_id
        if body is not None:
            kwargs["body"] = body
        if acceptance_criteria is not None:
            kwargs["acceptance_criteria"] = _criteria_list(acceptance_criteria)
        if tags is not None:
            kwargs["tags"] = [t.strip() for t in tags.split(",")]
        if depends_on is not None:
            kwargs["depends_on"] = [d.strip() for d in depends_on.split(",")]
        if outcome is not None:
            kwargs["outcome"] = outcome
        if note is not None:
            kwargs["note"] = note
        evidence_arg = _evidence_arg(evidence)
        if evidence_arg is not None:
            kwargs["evidence"] = evidence_arg

        meta = store.update(id, clear=clear_fields, **kwargs)
        # Read the reconciliation record straight after the update that
        # produced it — it is per-instance state on a cached Store, so a later
        # call would otherwise inherit it.
        reconciliation = (
            store.last_criteria_reconciliation if acceptance_criteria is not None else None
        )
        # Read (and clear) the truncation record straight after the update that
        # produced it, before any later call can overwrite or inherit it.
        truncation = _note_truncation_fields(store, note)
        clamp = _evidence_clamp_fields(store, evidence_arg)
        write_index(store)

        # Emit events for status changes
        if (
            status is not None
            and old_status_val is not None
            and old_status_val != status
        ):
            _emit_status_change(store, id, old_status_val, status, meta)

        # Echo only identity + the fields changed in this call (confirms how
        # list-shaped inputs were parsed) — not the full object
        dumped = meta.model_dump(mode="json")
        updated = {"id": meta.id, "status": dumped.get("status")}
        for field in (
            "points",
            "title",
            "assignee",
            "epic_id",
            "acceptance_criteria",
            "tags",
            "depends_on",
        ):
            # Cleared fields are echoed too — a caller that asked for a field
            # to be emptied gets to see that it is.
            if field in kwargs or field in clear_fields:
                updated[field] = dumped.get(field)
        if body is not None:
            updated["body_chars"] = len(body)
        if outcome is not None:
            updated["run_log"] = outcome
        elif evidence_arg is not None:
            # Evidence alone still lands an entry — `info`, empty note — so
            # the response says so rather than staying silent about a write.
            updated["run_log"] = "info"
        result = {"updated": updated}
        # Present only when the note was actually truncated; absence means the
        # note was stored whole.  See _note_truncation_fields for why.
        result.update(truncation)
        result.update(clamp)
        result.update(_note_length_fields(note, evidence_arg))
        # Present only when editing acceptance criteria actually moved test
        # tasks around, so the caller learns about tasks it did not ask for.
        if reconciliation and (
            reconciliation["created_task_ids"]
            or reconciliation["resynced_task_ids"]
            or reconciliation["orphaned"]
            or reconciliation["retired"]
        ):
            result["test_tasks"] = {
                "created": reconciliation["created_task_ids"],
                "resynced": reconciliation["resynced_task_ids"],
                # Criteria that got no new task because an *archived* test
                # task already covers them.  Nothing was un-archived: that
                # is a human decision (pm_restore), not the reconciler's.
                "retired": [
                    {"id": e["task_id"], "criterion": e["criterion"]}
                    for e in reconciliation["retired"]
                ],
                # US-PM-5-6's removal policy, as applied.  `archived` and
                # `flagged` partition `orphaned`, so a caller can branch on
                # list membership alone; `action` and `work_reasons` on each
                # orphan say why, in codes, never prose.
                "archived": reconciliation["archived_task_ids"],
                "flagged": reconciliation["flagged_task_ids"],
                "needs_attention": bool(reconciliation["flagged_task_ids"]),
                "orphaned": [
                    {
                        "id": o["task_id"],
                        "criterion": o["criterion"],
                        "status": o["status"],
                        "has_work": o["has_work"],
                        "action": o["action"],
                        "work_reasons": o["work_reasons"],
                    }
                    for o in reconciliation["orphaned"]
                ],
            }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Archive Item",
    annotations=ToolAnnotations(
        title="Archive Item", readOnlyHint=False, destructiveHint=True
    ),
)
def pm_archive(
    id: Optional[str] = None,
    project: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    """Archive an epic, story, or task.

    Args:
        id: Epic, story, or task ID to archive (alias: task_id)
        project: Optional project name (hub mode only)
        task_id: Alias for id — either spelling works; passing both with different values is an error
    """
    try:
        id = _resolve_id("id", id, task_id=task_id)
        store = _store(project)
        store.archive(id)
        write_index(store)
        return f"archived: {id}"
    except Exception as e:
        raise _failed(e) from e


def _do_grab(store, task_id: str, assignee: str, include_story: bool) -> dict:
    """Claim a task and build its context payload. Shared by pm_grab and pm_done_next.

    Returns a dict — either an expected-negative payload or {"grabbed": {...}}.
    """
    from .readiness import check_readiness

    task_meta, task_body = store.get_task(task_id)

    # Validate readiness (re-claiming your own task is idempotent)
    readiness = check_readiness(task_meta, task_body, store, reclaim_for=assignee)
    if not readiness["ready"]:
        # Expected negative, not a failure: the caller asked whether it
        # could take this task and got a valid, informative no.  The
        # blockers list is preserved verbatim — it is the recovery path.
        return _expected_negative_payload(
            "not_ready",
            "task is not ready to grab",
            blockers=readiness["blockers"],
        )

    # Claim: compare-and-swap on the on-disk assignee and status, under an
    # exclusive lock on the task file.  check_readiness above is advisory and
    # deliberately stays outside that lock — it is the expensive part, and a
    # task that passes it and then loses the swap gets `already_claimed`,
    # which is the correct and honest answer.
    old_status = task_meta.status.value
    won, current = store.claim_task(task_id, assignee)
    if not won:
        # Another worker got there first.  Expected negative, not a failure:
        # two workers racing for one task is the normal operation of a
        # parallel pool.  Classifying it as is_error would make routine
        # contention indistinguishable from real breakage in every
        # transport-level metric.  The task is left untouched; `holder` is
        # the recovery detail, exactly as `blockers` is `not_ready`'s.
        return _expected_negative_payload(
            "already_claimed",
            "task is already claimed",
            holder=current.assignee,
            task_id=task_id,
        )
    write_index(store)
    if old_status != "in-progress":
        _emit(
            "task.status_update",
            {
                "taskId": task_id,
                "oldStatus": old_status,
                "newStatus": "in-progress",
                "storyId": task_meta.story_id,
            },
        )

    # Re-read updated task
    task_meta, task_body = store.get_task(task_id)

    # Load parent story context (body only when requested — it is identical
    # for every grab within the same story)
    story_context = {}
    try:
        story_meta, story_body = store.get_story(task_meta.story_id)
        story_context = {
            "id": story_meta.id,
            "title": story_meta.title,
            "status": story_meta.status.value,
            "priority": story_meta.priority.value,
        }
        if include_story:
            story_context["body"] = story_body
    except FileNotFoundError:
        story_context = {"id": task_meta.story_id, "error": "not found"}

    # Load sibling tasks — only unfinished ones (cap at 20 to avoid bloat)
    siblings = store.list_tasks(story_id=task_meta.story_id)
    all_siblings = [s for s in siblings if s.id != task_id]
    open_siblings = [s for s in all_siblings if s.status.value != "done"]
    sibling_list = [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status.value,
            "assignee": s.assignee,
        }
        for s in open_siblings[:20]
    ]

    # Build dependency status (cross-story aware)
    dependency_status = []
    if task_meta.depends_on:
        # Build lookup maps for all tasks and stories
        all_tasks = store.list_tasks()
        all_stories = store.list_stories()
        task_map = {t.id: t for t in all_tasks}
        story_map = {s.id: s for s in all_stories}

        for dep_id in task_meta.depends_on:
            if dep_id in task_map:
                dep = task_map[dep_id]
                dependency_status.append(
                    {
                        "id": dep.id,
                        "title": dep.title,
                        "status": dep.status.value,
                        "type": "task",
                    }
                )
            elif dep_id in story_map:
                dep = story_map[dep_id]
                dependency_status.append(
                    {
                        "id": dep.id,
                        "title": dep.title,
                        "status": dep.status.value,
                        "type": "story",
                    }
                )

    grabbed = {
        "task": task_meta.model_dump(mode="json"),
        "body": task_body,
        "story_context": story_context,
        "sibling_tasks": sibling_list,
        "sibling_tasks_total": len(all_siblings),
        "sibling_tasks_done": len(all_siblings) - len(open_siblings),
        "dependency_status": dependency_status,
    }
    # Omit the key entirely when there is nothing to warn about — an empty
    # `warnings: []` costs bytes on every call and reads as a signal.  Its
    # presence now means "something genuinely applies to this task".
    if readiness["warnings"]:
        grabbed["warnings"] = readiness["warnings"]
    return {"grabbed": grabbed}


@mcp.tool(
    title="Grab Task",
    annotations=ToolAnnotations(
        title="Grab Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_grab(
    task_id: Optional[str] = None,
    assignee: str = "claude",
    include_story: bool = True,
    project: Optional[str] = None,
    id: Optional[str] = None,
    fields: Optional[str] = None,
) -> str:
    """Claim a task — validates readiness, assigns, sets in-progress, loads context.

    Claiming is a compare-and-swap on the on-disk assignee, so two concurrent
    workers can never both win the same task. The loser gets an expected
    negative (`status: already_claimed`, with `holder`) and the task is left
    untouched — take a different task; nothing is broken.

    Re-claiming a task already assigned to the same assignee (e.g. pre-claimed
    by an orchestrator via pm_done_next) succeeds and returns the same payload.

    Args:
        task_id: Task ID to claim (e.g. US-PRJ-1-1) (alias: id)
        assignee: Who is claiming (default "claude" for AI agents, or a human name)
        include_story: Include the parent story body (default true). Pass false when grabbing another task from a story whose context you already have.
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        fields: Comma-separated key names to return, e.g. "status,assignee" — a re-claim used only to verify state is `pm_grab(task_id, fields="status,assignee")` and comes back as `grabbed: {task: {id, status, assignee}}`. Names are either keys of the task (status, assignee, points, title, story_id, depends_on, …) or whole top-level sections (body, story_context, sibling_tasks, sibling_tasks_total, sibling_tasks_done, dependency_status, warnings); unnamed sections are omitted and `id` is always kept. Projection is output-only — the claim is identical either way, and expected negatives come back in full. An unknown name is an error listing the valid ones. Omit for the full payload — the default is unchanged.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        names = _field_names(fields)
        payload = _do_grab(store, task_id, assignee, include_story)
        # Expected negatives (`already_claimed`, `not_ready`) are returned
        # unprojected: they are already small, and their detail — `holder`,
        # `blockers` — is the caller's whole recovery path.
        if names is not None and "grabbed" in payload:
            payload = {"grabbed": _project_grabbed(payload["grabbed"], names)}
        return _yaml_dump(payload)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Release Task",
    annotations=ToolAnnotations(
        title="Release Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_release(
    task_id: Optional[str] = None,
    status: str = "todo",
    note: Optional[str] = None,
    outcome: Optional[str] = None,
    expected_assignee: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Release a task — hand it back to the pool. The exact inverse of pm_grab.

    Use this whenever a task must stop being yours: work stopped, the
    orchestrator is unwinding, a worker is going away. One call clears the
    assignee, resets the status to todo and records why:

        pm_release("US-PRJ-1-1", note="worker stopped before finishing")

    Never express this as an update with an empty assignee. There is no
    assignee parameter here — releasing is said by the verb, not by a value.

    Releasing a task nobody holds succeeds; `from_assignee` comes back null so
    a cleanup loop never has to branch on a condition it does not care about.

    Args:
        task_id: Task ID to release (e.g. US-PRJ-1-1) (alias: id)
        status: Status to leave the task in (default "todo", i.e. ready for anyone)
        note: Run-log note saying why it was released. Longer notes are truncated server-side, never rejected.
        outcome: Run-log outcome (success/partial/blocked/failed/info); defaults to info when a note is given
        expected_assignee: Release only if this name still holds the task. Omit for an unguarded release. A mismatch is an expected negative (`status: not_holder`) and the task is left untouched.
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error

    Response: `released:` with the full `task` and `from_assignee` — who held it
    before the call, or null if it was already unassigned.  When — and only when
    — a supplied note had to be truncated, the response additionally carries
    `note_truncated: true`, `note_original_length`, `note_stored_length`,
    `note_dropped_chars` and `note_limit`, exactly as `pm_update` does.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        # A genuine failure, not a negative: assignee is a task-only field, so
        # a story or epic id here means the caller meant something else.
        if store._is_epic_id(task_id) or not store._is_task_id(task_id):
            raise ToolError(
                f"pm_release applies to tasks only, got: {task_id} "
                "(assignee is a task-only field)"
            )
        current, _ = store.get_task(task_id)
        from_assignee = current.assignee
        old_status = current.status.value
        if expected_assignee is not None and from_assignee != expected_assignee:
            # Guarded release lost — the holder changed under the caller.
            # An informative no, not a fault; nothing is written.
            return _expected_negative(
                "not_holder",
                "task is held by another assignee",
                holder=from_assignee,
                expected=expected_assignee,
            )

        kwargs: dict = {}
        if note is not None:
            kwargs["note"] = note
        if note is not None or outcome is not None:
            kwargs["outcome"] = outcome or "info"

        meta = store.update(task_id, status=status, clear=["assignee"], **kwargs)
        truncation = _note_truncation_fields(store, note)
        write_index(store)
        if old_status != status:
            _emit_status_change(store, task_id, old_status, status, meta)

        result = {
            "released": {
                "task": meta.model_dump(mode="json"),
                "from_assignee": from_assignee,
            }
        }
        result.update(truncation)
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


# ─── Verdict verbs ──────────────────────────────────────────────
#
# docs/reference/verdict-verbs-contract.md is the binding design.  Its
# governing rule is the sibling of the claim/release one:
#
#     A verdict is said by the verb, never by a values triple the caller
#     must remember.
#
# pm-orchestrate step 19 has exactly four terminal moves — Accept, Retry,
# Park, Accept-as-review — and each used to be a generic `pm_update` where
# the model had to remember the right status + outcome + note triple.  The
# measured result: 13% of `status=done` writes carried no run-log entry at
# all, and the outcome vocabulary collapsed to ~90% `success`.  Here status
# and outcome are *not parameters*: there is no way to call `pm_park` and
# get `success`, nor to reach `done` without `success`, and because every
# verb passes a fixed outcome and a required note, `Store.update` appends a
# run-log entry unconditionally — the entry is structurally unavoidable.

#: Substituted as the run-log note when `pm_done_next` is called without
#: one (contract §3).  `pm_done_next` used to forward its outcome *only*
#: when a note was given, which is exactly the 13% of `done` writes with no
#: run log.  It now always forwards the outcome and logs this sentinel
#: instead, so the omission stays visible in the data rather than vanishing
#: — no signature change, and no rejected call.
DONE_NEXT_NO_NOTE = "completed via pm_done_next (no note given)"

#: status / outcome / response-key for the three non-accept verdicts.  The
#: table is the contract's §1 table; keeping it as data is what makes
#: "status and outcome are not parameters" true by construction.
_VERDICTS = {
    "pm_retry": ("todo", "failed", "retried"),
    "pm_park": ("review", "blocked", "parked"),
    "pm_review": ("review", "partial", "reviewed"),
}


def _require_note(verb: str, note: object) -> str:
    """A terminal verdict may not land without a run-log note.

    `note: str = ...` makes the parameter *required* in the tool schema, so
    FastMCP rejects an omitted note before the body runs and nothing
    half-written reaches disk.  This covers the two cases the schema cannot:
    a blank/whitespace note, and a direct Python call that never went
    through the schema at all (where the unfilled default arrives as
    `Ellipsis`).  Both raise before the first write, so status and run log
    are left untouched.
    """
    if note is None or note is ... or not str(note).strip():
        raise ToolError(
            f"{verb} requires a non-blank note — a verdict must leave a run-log "
            "entry saying why it was reached (the note is what makes the "
            "completion auditable). Pass note=\"...\"."
        )
    return str(note)


def _verdict_target(verb: str, store: Store, task_id: str) -> None:
    """A verdict applies to a task, never to a story or epic.

    A genuine failure rather than an expected negative, exactly as in
    `pm_release`: status *and* assignee are being set together here, and
    assignee is a task-only field, so a story or epic id means the caller
    meant something else entirely.
    """
    if store._is_epic_id(task_id) or not store._is_task_id(task_id):
        raise ToolError(
            f"{verb} applies to tasks only, got: {task_id} "
            "(a verdict is passed on a task, not a story or epic)"
        )


def _do_verdict(
    store: Store, verb: str, task_id: str, note: object, evidence: object = None
) -> dict:
    """Retry / park / review: one status+outcome write, assignee cleared.

    All three accept **any** starting status, including `done` — the common
    case is precisely a worker that self-reported done and failed
    validation, and refusing it would leave the orchestrator with no way to
    say so.  All three clear the assignee because the task is going back to
    the pool (`retry`) or waiting on a human (`park`, `review`), and a stale
    holder blocks the next `pm_grab`.  Only `pm_accept` guards.
    """
    status, outcome, key = _VERDICTS[verb]
    _verdict_target(verb, store, task_id)
    note = _require_note(verb, note)

    current, _ = store.get_task(task_id)
    from_assignee = current.assignee
    from_status = current.status.value

    evidence = _evidence_arg(evidence)
    meta = store.update(
        task_id,
        status=status,
        outcome=outcome,
        note=note,
        evidence=evidence,
        clear=["assignee"],
    )
    # Read (and clear) the truncation and clamp records straight after the
    # write — write_index and the event emit must not get between them.
    truncation = _note_truncation_fields(store, note)
    clamp = _evidence_clamp_fields(store, evidence)
    write_index(store)
    if from_status != status:
        _emit_status_change(store, task_id, from_status, status, meta)

    result = {
        key: {
            "task": meta.model_dump(mode="json"),
            "from_status": from_status,
            "from_assignee": from_assignee,
        }
    }
    result.update(truncation)
    result.update(clamp)
    result.update(_note_length_fields(note, evidence))
    return result


def _do_accept(
    store: Store,
    task_id: str,
    note: object,
    *,
    outcome: str = "success",
    next_task: bool = True,
    same_story_only: bool = True,
    assignee: str = "claude",
    guard_done: bool = False,
    evidence: object = None,
) -> dict:
    """Complete a task, close its story if it was the last, grab the next.

    The shared body behind `pm_accept` (the verdict-shaped front door) and
    `pm_done_next` (a thin wrapper that keeps its own signature forever).
    They are one call because they are one decision: "accepted" and "give me
    the next one" are the same beat of the orchestrator loop, and the
    measured failure is callers splitting them into `pm_grab` +
    `pm_update(done)` — 512 such pairs against 387 `pm_done_next` calls.

    `outcome` is internal, not a verdict parameter: `pm_accept` always fixes
    it to `success`, and only `pm_done_next` — whose published signature
    predates this contract — passes anything else.

    Returns a dict; the callers render it.
    """
    from .deps import topological_sort
    from .readiness import check_readiness

    task_meta, _ = store.get_task(task_id)
    story_id = task_meta.story_id
    old_status = task_meta.status.value

    if guard_done and old_status == "done":
        # Expected negative, not a failure: the caller asked for a verdict
        # that has already been recorded, and "it is already done" is a
        # valid answer.  Nothing is written — a second run-log entry would
        # double-count the completion, and a second story close or next
        # grab would take work the caller has not asked to start.
        return _expected_negative_payload(
            "already_done",
            f"{task_id} is already done",
            task_id=task_id,
        )

    # 1. Complete the task.  The outcome and the note are both always
    # present, so `Store.update` always appends a run-log entry — this is
    # the mechanism behind "completions lacking a run-log entry drops to
    # zero".  See DONE_NEXT_NO_NOTE for the pm_done_next case.
    evidence = _evidence_arg(evidence)
    meta = store.update(
        task_id, status="done", outcome=outcome, note=note, evidence=evidence
    )
    # Read (and clear) the truncation and clamp records before anything else
    # touches the Store: closing the parent story and grabbing the next task
    # both call ``store.update``, and each of those resets them.
    truncation = _note_truncation_fields(store, note)
    clamp = _evidence_clamp_fields(store, evidence)
    write_index(store)
    if old_status != "done":
        _emit_status_change(store, task_id, old_status, "done", meta)

    result = {"completed": {"id": task_id, "status": "done", "run_log": outcome}}
    # Present only when the note actually had to be truncated; absence
    # means it was stored whole.  Same fields, same rule, as pm_update.
    result.update(truncation)
    result.update(clamp)
    result.update(_note_length_fields(note, evidence))

    # 2. Close the parent story if this was its last open task
    siblings = store.list_tasks(story_id=story_id)
    open_siblings = [s for s in siblings if s.status.value != "done"]
    if not open_siblings:
        try:
            story_meta, _ = store.get_story(story_id)
            if story_meta.status.value not in ("done", "archived"):
                old_story_status = story_meta.status.value
                story_meta = store.update(story_id, status="done")
                write_index(store)
                _emit_status_change(
                    store, story_id, old_story_status, "done", story_meta
                )
            result["story_closed"] = story_id
        except Exception as e:
            result["story_close_error"] = str(e)

    if not next_task:
        # The non-orchestrator caller: complete, and claim nothing.  The
        # `next` key is absent entirely rather than null — null means "I
        # looked and there was none", which would be a lie here.
        return result

    # 3. Pick the next ready task: same story first (topological order),
    # then other stories by priority > story > topological order > points
    all_tasks = store.list_tasks()
    story_priority = {}
    priority_order = {"must": 0, "should": 1, "could": 2, "wont": 3}
    for s in store.list_stories():
        story_priority[s.id] = priority_order.get(s.priority.value, 1)

    story_tasks: dict[str, list] = {}
    for t in all_tasks:
        story_tasks.setdefault(t.story_id, []).append(t)
    topo_position: dict[str, int] = {}
    for sid, tasks_in_story in story_tasks.items():
        try:
            sorted_tasks = topological_sort(tasks_in_story)
        except Exception:
            sorted_tasks = tasks_in_story
        for idx, t in enumerate(sorted_tasks):
            topo_position[t.id] = idx

    candidates = [t for t in all_tasks if t.status.value == "todo" and not t.assignee]
    if same_story_only:
        candidates = [t for t in candidates if t.story_id == story_id]
    candidates.sort(
        key=lambda t: (
            t.story_id != story_id,  # same story first
            story_priority.get(t.story_id, 1),
            t.story_id,
            topo_position.get(t.id, 0),
            t.points or 99,
        )
    )

    # Readiness-check candidates lazily until one is grabbable
    next_grab = None
    not_ready_count = 0
    for candidate in candidates:
        _, cand_body = store.get_task(candidate.id)
        if check_readiness(candidate, cand_body, store)["ready"]:
            grab = _do_grab(
                store,
                candidate.id,
                assignee,
                include_story=candidate.story_id != story_id,
            )
            if "grabbed" in grab:
                next_grab = grab["grabbed"]
                break
            not_ready_count += 1
        else:
            not_ready_count += 1

    if next_grab:
        result["next"] = next_grab
    else:
        # Expected negative, not a failure: the task really was completed,
        # and "nothing follows it" is a valid answer to the second half of
        # the question — 22% of calls, the normal case rather than an edge.
        # The discriminator leads the payload so a caller branches on it
        # before reading anything else; the `next_info` hint is kept
        # verbatim as detail.  See _expected_negative.
        scope_note = "in this story" if same_story_only else "in this project"
        result = {
            **_expected_negative_payload(
                "no_next_task", f"no ready task follows {task_id}"
            ),
            **result,
            "next": None,
            "next_info": (
                f"no ready unassigned tasks {scope_note} "
                f"({len(candidates)} todo, {not_ready_count} blocked — see pm_board)"
            ),
        }
    return result


@mcp.tool(
    title="Accept Task",
    annotations=ToolAnnotations(
        title="Accept Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_accept(
    task_id: Optional[str] = None,
    note: str = ...,
    next_task: bool = True,
    same_story_only: bool = True,
    assignee: str = "claude",
    project: Optional[str] = None,
    id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Accept a task's work — marks it done, logs why, and claims the next one.

    The Accept verdict. Use this instead of pm_update(status="done") and
    instead of pm_grab afterwards — one call is the orchestrator's whole beat:

        pm_accept("US-PRJ-1-1", note="all DoD items met; 47 tests pass")

    Status and outcome are not parameters: this is always done + success.
    The note is required, so an accepted task can never land without a
    run-log entry saying what was delivered.

    The assignee is kept — a done task records who did it. Its siblings
    pm_retry / pm_park / pm_review clear it instead.

    Accepting an already-done task is an expected negative
    (`status: already_done`), not a failure: nothing is written twice.
    When nothing is ready to follow, the response is likewise an expected
    negative (`status: no_next_task`) — the completion still landed, and
    `next` is present and null with a `next_info` hint alongside it.

    Args:
        task_id: Task ID being accepted (e.g. US-PRJ-1-1) (alias: id)
        note: Run-log note saying what was delivered. Required — a blank note is an error. Longer notes are truncated server-side (4096 chars), never rejected.
        next_task: Claim the next ready task too (default true). Pass false to complete without claiming anything; the `next` key is then absent.
        same_story_only: Only take a next task from the same story (default true). Pass false to fall through to other stories.
        assignee: Who claims the next task (default "claude")
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    Response: `completed:` with the id, status and run_log outcome;
    `story_closed:` when this was the story's last open task; and `next:`
    with the newly claimed task. When — and only when — the note had to be
    truncated, the response additionally carries `note_truncated: true`,
    `note_original_length`, `note_stored_length`, `note_dropped_chars` and
    `note_limit`, exactly as pm_update does.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        _verdict_target("pm_accept", store, task_id)
        note = _require_note("pm_accept", note)
        return _yaml_dump(
            _do_accept(
                store,
                task_id,
                note,
                next_task=next_task,
                same_story_only=same_story_only,
                assignee=assignee,
                guard_done=True,
                evidence=evidence,
            )
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Retry Task",
    annotations=ToolAnnotations(
        title="Retry Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_retry(
    task_id: Optional[str] = None,
    note: str = ...,
    project: Optional[str] = None,
    id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Retry a task — the attempt failed, hand it back to the pool for another go.

    The Retry verdict. One call resets the status to todo, clears the
    assignee and records the failure:

        pm_retry("US-PRJ-1-1", note="tests still red — the fixture never loads")

    Status and outcome are not parameters: this is always todo + failed.
    The note is required, so the next worker inherits the reason.

    Any starting status is accepted, `done` included — the common case is
    precisely a worker that self-reported done and failed validation.

    Args:
        task_id: Task ID to retry (e.g. US-PRJ-1-1) (alias: id)
        note: Run-log note saying what failed. Required — a blank note is an error. Longer notes are truncated server-side, never rejected.
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    Response: `retried:` with the full `task`, `from_status` and
    `from_assignee` — the status and holder before the call. When — and only
    when — the note had to be truncated, the response additionally carries
    `note_truncated: true`, `note_original_length`, `note_stored_length`,
    `note_dropped_chars` and `note_limit`, exactly as pm_update does.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        return _yaml_dump(
            _do_verdict(store, "pm_retry", task_id, note, evidence=evidence)
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Park Task",
    annotations=ToolAnnotations(
        title="Park Task", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_park(
    task_id: Optional[str] = None,
    note: str = ...,
    project: Optional[str] = None,
    id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Park a task — it is blocked on something a human has to resolve.

    The Park verdict. One call moves the task to review, clears the assignee
    so it does not sit stale, and records the blocker:

        pm_park("US-PRJ-1-1", note="needs the staging DB credentials")

    Status and outcome are not parameters: this is always review + blocked.
    The note is required — it is the whole handover to whoever unblocks it.

    Any starting status is accepted, `done` included.

    Args:
        task_id: Task ID to park (e.g. US-PRJ-1-1) (alias: id)
        note: Run-log note saying what it is blocked on. Required — a blank note is an error. Longer notes are truncated server-side, never rejected.
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    Response: `parked:` with the full `task`, `from_status` and
    `from_assignee` — the status and holder before the call. When — and only
    when — the note had to be truncated, the response additionally carries
    `note_truncated: true`, `note_original_length`, `note_stored_length`,
    `note_dropped_chars` and `note_limit`, exactly as pm_update does.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        return _yaml_dump(
            _do_verdict(store, "pm_park", task_id, note, evidence=evidence)
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Accept Task As Review",
    annotations=ToolAnnotations(
        title="Accept Task As Review", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_review(
    task_id: Optional[str] = None,
    note: str = ...,
    project: Optional[str] = None,
    id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Send a task to review — the work partly landed and a human should look.

    The Accept-as-review verdict, the middle answer between pm_accept and
    pm_retry. One call moves the task to review, clears the assignee and
    records what is and is not there:

        pm_review("US-PRJ-1-1", note="endpoint works; error paths untested")

    Status and outcome are not parameters: this is always review + partial.
    `partial` is the outcome the vocabulary keeps losing — 90% of run-log
    entries say `success` — and this verb is how it gets said.

    Any starting status is accepted, `done` included — a worker that
    self-reported done and only half-delivered is exactly this verdict.

    Args:
        task_id: Task ID to send to review (e.g. US-PRJ-1-1) (alias: id)
        note: Run-log note saying what landed and what did not. Required — a blank note is an error. Longer notes are truncated server-side, never rejected.
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    Response: `reviewed:` with the full `task`, `from_status` and
    `from_assignee` — the status and holder before the call. When — and only
    when — the note had to be truncated, the response additionally carries
    `note_truncated: true`, `note_original_length`, `note_stored_length`,
    `note_dropped_chars` and `note_limit`, exactly as pm_update does.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        return _yaml_dump(
            _do_verdict(store, "pm_review", task_id, note, evidence=evidence)
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Complete Task & Grab Next",
    annotations=ToolAnnotations(
        title="Complete Task & Grab Next", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_done_next(
    task_id: Optional[str] = None,
    outcome: str = "success",
    note: Optional[str] = None,
    assignee: str = "claude",
    same_story_only: bool = False,
    project: Optional[str] = None,
    id: Optional[str] = None,
    evidence: Optional[Evidence] = None,
) -> str:
    """Complete a task and claim the next ready one in a single call — use this instead of pm_update + pm_grab when working through tasks.

    `pm_accept` is the same call with the verdict said by the verb: the note
    is required there, and status and outcome cannot be spelled wrong. This
    spelling stays supported forever and is not deprecated.

    Marks task_id done (always appending a run-log entry), closes the parent
    story automatically if this was its last open task, then grabs the next
    ready task — preferring siblings in the same story. The story body is only
    included when the next task belongs to a different story.

    When nothing is ready to follow, the response is an expected negative —
    `outcome: expected_negative` with `status: no_next_task` — not a failure:
    the call did complete the task, and "none left" is a valid answer. `next`
    is still present and null, with the `next_info` hint alongside it.

    Args:
        task_id: Task ID just finished (e.g. US-PRJ-1-1) (alias: id)
        outcome: Run-log outcome for the completed task: success/partial/info (default success)
        note: Run-log note describing what was accomplished. Longer notes are truncated server-side (4096 chars) with a visible marker, never rejected — the completion always lands. Omitting it — or passing a blank one, which counts as omitted — logs a placeholder note instead; prefer pm_accept, which requires a real one.
        assignee: Who claims the next task (default "claude")
        same_story_only: Only grab a next task from the same story; report and stop otherwise (default false)
        project: Optional project name (hub mode only)
        id: Alias for task_id — either spelling works; passing both with different values is an error
        evidence: Structured proof for the run-log entry — an object with `files` (paths changed), `tests` (objects with `command`, `passed`, optional `summary`), `dod_met` and `dod_unmet` (criteria). Put lists here, never in the note; the note stays a one-line summary (recommended <= 200 chars). Bounded and clamped, never rejected: files <= 40, tests <= 10, each DoD list <= 20, each string <= 160 chars; when a clamp fires the response carries `evidence_clamped` and `evidence_dropped`.

    When — and only when — a supplied note had to be truncated, the response
    additionally carries `note_truncated: true`, `note_original_length`,
    `note_stored_length`, `note_dropped_chars` and `note_limit`, exactly as
    `pm_update` does, so a caller detects truncation without string-matching.
    """
    try:
        task_id = _resolve_id("task_id", task_id, id=id)
        store = _store(project)
        return _yaml_dump(
            _do_accept(
                store,
                task_id,
                # The 13% hole, closed inside the wrapper: the outcome is now
                # always forwarded, and a caller who gave no note — or a blank
                # one, which is an omitted note by any reading — gets a fixed
                # placeholder rather than no run-log entry at all.  The
                # omission stays visible in the data instead of vanishing.
                note if note is not None and note.strip() else DONE_NEXT_NO_NOTE,
                outcome=outcome,
                next_task=True,
                same_story_only=same_story_only,
                assignee=assignee,
                evidence=evidence,
            )
        )
    except Exception as e:
        raise _failed(e) from e


# ─── Intelligence Tools ─────────────────────────────────────────


@mcp.tool(
    title="Estimation Context",
    annotations=ToolAnnotations(title="Estimation Context", readOnlyHint=True),
)
def pm_estimate(
    id: Optional[str] = None,
    project: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    """Get estimation context for a story or task — returns content + calibration guidelines.

    Args:
        id: Story or task ID to estimate (alias: task_id)
        project: Optional project name (hub mode only)
        task_id: Alias for id — either spelling works; passing both with different values is an error
    """
    try:
        from .estimator import estimate

        id = _resolve_id("id", id, task_id=task_id)
        store = _store(project)
        return estimate(store, id)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Scoping Context",
    annotations=ToolAnnotations(title="Scoping Context", readOnlyHint=True),
)
def pm_scope(
    id: Optional[str] = None,
    project: Optional[str] = None,
    story_id: Optional[str] = None,
) -> str:
    """Get scoping context for a story — returns story + existing tasks + decomposition guidance.

    Args:
        id: Story ID to scope into tasks (alias: story_id)
        project: Optional project name (hub mode only)
        story_id: Alias for id — either spelling works; passing both with different values is an error
    """
    try:
        from .scoper import scope

        id = _resolve_id("id", id, story_id=story_id)
        store = _store(project)
        return scope(store, id)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Project Audit",
    annotations=ToolAnnotations(title="Project Audit", readOnlyHint=True),
)
def pm_audit(include_info: bool = False, project: Optional[str] = None) -> str:
    """Run project audit — checks for drift, inconsistencies, stale items.

    Returns errors and warnings; info-level findings are summarized as a count
    unless include_info is true. The full report is always written to DRIFT.md.

    Args:
        include_info: Include info-level findings in the response (default false)
        project: Optional project name (hub mode only)
    """
    try:
        from .audit import run_audit

        root = find_project_root()
        if project:
            config = load_config(root)
            if config.hub:
                pm_dir = root / ".project" / "projects" / project
                if not (pm_dir / "config.yaml").exists():
                    raise ToolError(f"project '{project}' not found in hub")
                return run_audit(root, project_dir=pm_dir, include_info=include_info)
        return run_audit(root, include_info=include_info)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Hub Repair",
    annotations=ToolAnnotations(
        title="Hub Repair", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_repair() -> str:
    """Scan the hub for unregistered projects, initialize missing PM data
    directories (hub_root/.project/projects/{name}/), rebuild all indexes
    and embeddings, and regenerate dashboards.
    Hub mode only. Writes a REPAIR.md report."""
    try:
        config = load_config(find_project_root())
        if not config.hub:
            raise ToolError("not a hub project")
        from .hub.registry import repair

        return _raise_on_hub_error(repair())
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Validate Branches",
    annotations=ToolAnnotations(title="Validate Branches", readOnlyHint=True),
)
def pm_validate_branches() -> str:
    """Validate that each hub submodule is on its expected tracked branch.

    Returns structured data with aligned, misaligned, detached, and missing
    projects plus an overall ok flag and summary string.
    """
    try:
        from .hub.registry import validate_branches

        root = find_project_root()
        result = validate_branches(root=root)
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Next Malformed File",
    annotations=ToolAnnotations(title="Next Malformed File", readOnlyHint=True),
)
def pm_malformed(project: Optional[str] = None) -> str:
    """Get the next malformed file to fix. Returns one file at a time with its full
    content. Call pm_fix_malformed to fix it (which removes it from the queue),
    then call pm_malformed again to get the next one. Repeat until done.

    Args:
        project: Optional project name (hub mode only). Omit to scan all.
    """
    try:
        import frontmatter

        root = find_project_root()
        config = load_config(root)

        # Collect all malformed files across projects
        all_files = []  # list of (project_name, path)
        dirs_to_scan = []
        if project:
            proj_dir = _resolve_project_dir(project)
            malformed_dir = proj_dir / "malformed"
            if malformed_dir.exists():
                dirs_to_scan.append((project, malformed_dir))
        elif config.hub:
            hub_mal = root / ".project" / "malformed"
            if hub_mal.exists() and any(hub_mal.iterdir()):
                dirs_to_scan.append(("hub", hub_mal))
            for name in config.projects:
                mal = root / ".project" / "projects" / name / "malformed"
                if mal.exists() and any(mal.iterdir()):
                    dirs_to_scan.append((name, mal))
        else:
            malformed_dir = root / ".project" / "malformed"
            if malformed_dir.exists():
                dirs_to_scan.append((config.name, malformed_dir))

        for proj_name, mal_dir in dirs_to_scan:
            for path in sorted(mal_dir.glob("*.md")):
                all_files.append((proj_name, path))

        total = len(all_files)
        if total == 0:
            return "no malformed files"

        # Always return the first file — fixing removes it, so next call gets the next one
        proj_name, path = all_files[0]

        entry = {"file": path.name, "project": proj_name}
        try:
            post = frontmatter.load(str(path))
            entry["frontmatter"] = dict(post.metadata)
            entry["body"] = post.content
        except Exception:
            entry["raw_content"] = path.read_text()

        result = {
            "remaining": total,
            "item": entry,
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Fix Malformed File",
    annotations=ToolAnnotations(
        title="Fix Malformed File", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_fix_malformed(
    filename: str,
    id: str,
    title: str,
    item_type: str,
    body: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    points: Optional[int] = None,
    story_id: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Fix a malformed file by rewriting it with valid frontmatter, then restore it.

    Args:
        filename: The malformed filename (e.g. PRJ-1.md)
        id: Correct item ID (e.g. PRJ-1 for story, PRJ-1-1 for task)
        title: Correct title
        item_type: "story" or "task"
        body: New body content (keeps original if not provided)
        status: Status (stories: backlog/ready/active/done; tasks: todo/in-progress/review/done/blocked)
        priority: Priority for stories (must/should/could/wont)
        points: Story points
        story_id: Parent story ID (required for tasks)
        project: Optional project name (hub mode only)
    """
    try:
        import frontmatter as fm
        from datetime import date
        from .models import StoryFrontmatter, TaskFrontmatter

        proj_dir = _resolve_project_dir(project)
        malformed_dir = proj_dir / "malformed"
        source = malformed_dir / filename

        if not source.exists():
            raise ToolError(_no_such_malformed_file(malformed_dir, filename))

        # Read existing body if not provided
        if body is None:
            try:
                post = fm.load(str(source))
                body = post.content or ""
            except Exception:
                body = source.read_text()

        today = date.today()

        dest_filename = f"{id}.md"

        if item_type == "task":
            if not story_id:
                raise ToolError("story_id is required for tasks")
            meta = TaskFrontmatter(
                id=id,
                story_id=story_id,
                title=title,
                status=status or "todo",
                points=points,
                created=today,
                updated=today,
            )
            dest = proj_dir / "tasks" / dest_filename
        else:
            meta = StoryFrontmatter(
                id=id,
                title=title,
                status=status or "backlog",
                priority=priority or "should",
                points=points,
                tags=[],
                created=today,
                updated=today,
            )
            dest = proj_dir / "stories" / dest_filename

        # Write the fixed file to its correct location with ID-based filename
        post = fm.Post(content=body, **meta.model_dump(mode="json"))
        dest.write_text(fm.dumps(post))
        source.unlink()

        # Clean up empty malformed dir
        if not any(malformed_dir.iterdir()):
            malformed_dir.rmdir()

        store = _store(project)
        write_index(store)
        return _yaml_dump(
            {"fixed": meta.model_dump(mode="json"), "restored_to": str(dest)}
        )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Restore File",
    annotations=ToolAnnotations(
        title="Restore File", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_restore(filename: str, project: Optional[str] = None) -> str:
    """Restore a fixed file from the malformed quarantine back to stories/ or tasks/.

    Args:
        filename: The filename to restore (e.g. PRJ-1.md)
        project: Optional project name (hub mode only)
    """
    try:
        import frontmatter as fm
        from .models import StoryFrontmatter, TaskFrontmatter

        proj_dir = _resolve_project_dir(project)
        malformed_dir = proj_dir / "malformed"
        source = malformed_dir / filename

        if not source.exists():
            raise ToolError(_no_such_malformed_file(malformed_dir, filename))

        # Validate before restoring
        post = fm.load(str(source))
        stem = source.stem
        parts = stem.split("-")
        is_task = len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit()

        if is_task:
            TaskFrontmatter(**post.metadata)
            dest = proj_dir / "tasks" / filename
        else:
            StoryFrontmatter(**post.metadata)
            dest = proj_dir / "stories" / filename

        import shutil

        shutil.move(str(source), str(dest))

        # Clean up empty malformed dir
        if not any(malformed_dir.iterdir()):
            malformed_dir.rmdir()

        store = _store(project)
        write_index(store)
        return f"restored: {filename} → {'tasks' if is_task else 'stories'}/"
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Rebuild Index",
    annotations=ToolAnnotations(
        title="Rebuild Index", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_reindex(project: Optional[str] = None) -> str:
    """Rebuild the project index and optionally reindex embeddings.

    Args:
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        write_index(store)

        # Try to reindex embeddings too
        try:
            from .embeddings import EmbeddingStore

            emb = EmbeddingStore(store.project_dir)
            emb.reindex_all(store)
            return "reindexed: index.yaml + embeddings"
        except (ImportError, Exception):
            return "reindexed: index.yaml (embeddings not available)"
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Auto-Scope Discovery",
    annotations=ToolAnnotations(title="Auto-Scope Discovery", readOnlyHint=True),
)
def pm_auto_scope(
    mode: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> str:
    """Discover what needs scoping — returns codebase signals (full scan) or undecomposed stories (incremental).

    Auto-detects mode: full scan when no epics/stories exist, incremental when stories lack tasks.
    Use with /pm-autoscope skill for automated epic/story/task creation.

    Args:
        mode: Force mode: "full" (codebase scan for new projects) or "incremental" (scope existing stories). Auto-detected if omitted.
        project: Optional project name (hub mode only)
        limit: Max stories per batch in incremental mode (default 5)
        offset: Starting index for pagination in incremental mode (default 0)
    """
    try:
        from .scoper import auto_scope

        store = _store(project)
        return auto_scope(store, mode=mode, limit=limit, offset=offset)
    except Exception as e:
        raise _failed(e) from e


# ─── Git Tools ───────────────────────────────────────────────────


@mcp.tool(
    title="Git Status Dashboard",
    annotations=ToolAnnotations(title="Git Status Dashboard", readOnlyHint=True),
)
def pm_git_status(project: Optional[str] = None) -> str:
    """Show git status across all hub submodules — branch, dirty, ahead/behind, PRs.

    Returns the structured list from git_status_all() including PR data.
    Use this as the first thing to check before any coordinated operation.

    Args:
        project: Optional project name to check a single subproject instead of all
    """
    try:
        from .hub.registry import git_status_all

        root = find_project_root()
        data = git_status_all(root=root)

        if project:
            # Filter to a single project
            matched = [p for p in data.get("projects", []) if p["name"] == project]
            if not matched:
                raise ToolError(f"project '{project}' not found in hub status")
            return _yaml_dump(
                {
                    "projects": matched,
                    "total": 1,
                    "issues": 1 if matched[0].get("issues") else 0,
                    "ok": not matched[0].get("issues"),
                    "summary": f"Status for {project}",
                }
            )

        return _yaml_dump(data)
    except Exception as e:
        raise _failed(e) from e


def _nothing_to_commit() -> str:
    """The one ``pm_commit`` expected negative, shared by both commit routes.

    Idempotent no-op: the caller asked for ``.project/`` to be committed and it
    already is, so there is nothing to fix and nothing to retry.  Raising here
    would make every clean loop of an orchestrator that commits after each task
    look like a failure.
    """
    return _expected_negative("nothing_to_commit", "No .project/ changes to commit")


@mcp.tool(
    title="Commit PM Changes",
    annotations=ToolAnnotations(
        title="Commit PM Changes", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_commit(
    scope: str = "all",
    message: Optional[str] = None,
) -> str:
    """Commit .project/ changes with an auto-generated message.

    Stages changes under .project/ filtered by scope and commits them.
    If no message is provided, one is generated from the changed files
    (e.g. "pm: update US-PRJ-5, US-PRJ-3-1").

    Args:
        scope: Commit scope — "hub" (hub-level only, excludes subprojects), "project:<name>" (specific subproject), or "all" (everything under .project/)
        message: Optional commit message (auto-generated if omitted)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        if config.hub:
            from .hub.registry import pm_commit as _hub_commit

            result = _hub_commit(scope=scope, message=message, root=root)
        else:
            # Non-hub: scope is ignored (single project)
            store = Store(root)
            result = store.commit_project_changes(message=message)
            # Normalize key name to match hub format
            if "files_changed" in result:
                result["files_committed"] = result.pop("files_changed")

        if isinstance(result, dict) and result.get("nothing_to_commit"):
            return _nothing_to_commit()
        if isinstance(result, dict):
            # Return a file count, not the full path list; echo the message
            # only when auto-generated (the caller already knows their own)
            files = result.pop("files_committed", None)
            if files is not None:
                result["files_committed"] = len(files)
            if message is not None:
                result.pop("message", None)
        return _yaml_dump({"committed": result})
    except NothingToCommit:
        # The non-hub route reports this by raising rather than by returning a
        # dict, so it has to be intercepted here — *before* the handlers below,
        # which US-PM-2-3 converts into real errors.  Both routes produce the
        # identical expected-negative response.
        return _nothing_to_commit()
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise _failed(e) from e
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Push PM Changes",
    annotations=ToolAnnotations(
        title="Push PM Changes", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_push(
    scope: str = "hub",
) -> str:
    """Push committed .project/ changes to the remote.

    Validates branch alignment before pushing.  In hub mode, uses
    scope-aware routing with auto-rebase on conflict.

    Args:
        scope: Push scope — "hub" (hub repo on main), "project:<name>" (specific subproject), or "all" (coordinated push)
    """
    try:
        root = find_project_root()
        config = load_config(root)

        if config.hub:
            from .hub.registry import pm_push as _hub_push

            result = _raise_on_hub_error(_hub_push(scope=scope, root=root))
            return _yaml_dump({"pushed": result})
        else:
            # Non-hub: push normally
            store = Store(root)
            result = store.push_project_changes()
            return _yaml_dump({"pushed": result})
    except RuntimeError as e:
        raise _failed(e) from e
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Coordinated Push All",
    annotations=ToolAnnotations(
        title="Coordinated Push All", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_push_all(
    dry_run: bool = False,
    projects: Optional[str] = None,
) -> str:
    """Coordinated push: preflight, push subprojects, then push hub.

    Discovers dirty projects automatically (or uses explicit list),
    runs preflight validation, pushes subprojects in order, then pushes
    the hub with auto-rebase.

    Args:
        dry_run: If True, show what would be pushed without executing
        projects: Optional comma-separated project names (e.g. "api,web"). Omit to auto-discover dirty projects.
    """
    try:
        from .hub.registry import coordinated_push

        root = find_project_root()

        project_list = (
            [p.strip() for p in projects.split(",") if p.strip()] if projects else None
        )

        result = _raise_on_hub_error(
            coordinated_push(
                projects=project_list,
                dry_run=dry_run,
                root=root,
            )
        )
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


# ─── Changeset Tools ────────────────────────────────────────────


@mcp.tool(
    title="Create Changeset",
    annotations=ToolAnnotations(
        title="Create Changeset", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_changeset_create(
    title: str,
    projects: str,
    description: str = "",
    project: Optional[str] = None,
) -> str:
    """Create a changeset grouping related changes across multiple projects.

    Args:
        title: Changeset name (e.g. "add-auth")
        projects: Comma-separated project names (e.g. "api,web,worker")
        description: Optional description of the changeset
        project: Optional project name (hub mode only)
    """
    try:
        store = _store(project)
        project_list = [p.strip() for p in projects.split(",") if p.strip()]
        if not project_list:
            raise ToolError("at least one project is required")
        meta = store.create_changeset(title, project_list, description)
        write_index(store)
        return _yaml_dump({"created": meta.model_dump(mode="json")})
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Changeset Status",
    annotations=ToolAnnotations(title="Changeset Status", readOnlyHint=True),
)
def pm_changeset_status(
    changeset_id: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Get changeset status — one changeset by ID, or list all open changesets.

    Args:
        changeset_id: Optional changeset ID (e.g. CS-PRJ-1). Omit to list all. (alias: id)
        project: Optional project name (hub mode only)
        id: Alias for changeset_id — either spelling works; passing both with different values is an error
    """
    try:
        # Optional filter, so "neither" means "list all" rather than an error.
        changeset_id = _resolve_id(
            "changeset_id", changeset_id, required=False, id=id
        )
        store = _store(project)
        if changeset_id:
            meta, body = store.get_changeset(changeset_id)
            result = meta.model_dump(mode="json")
            result["body"] = body
            return _yaml_dump(result)
        else:
            changesets = store.list_changesets()
            return _yaml_dump(
                {
                    "changesets": [cs.model_dump(mode="json") for cs in changesets],
                    "count": len(changesets),
                }
            )
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Add Project to Changeset",
    annotations=ToolAnnotations(
        title="Add Project to Changeset", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_changeset_add_project(
    name: str,
    changeset_id: Optional[str] = None,
    ref: str = "",
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Add a project entry to an existing changeset.

    Args:
        name: Project name to add
        changeset_id: Changeset ID (e.g. CS-PRJ-1) (alias: id)
        ref: Optional git ref/branch for this project
        project: Optional project name (hub mode only)
        id: Alias for changeset_id — either spelling works; passing both with different values is an error
    """
    try:
        changeset_id = _resolve_id("changeset_id", changeset_id, id=id)
        store = _store(project)
        meta = store.add_changeset_entry(changeset_id, name, ref=ref)
        return _yaml_dump({"updated": meta.model_dump(mode="json")})
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Changeset Create PRs",
    annotations=ToolAnnotations(title="Changeset Create PRs", readOnlyHint=True),
)
def pm_changeset_create_prs(
    changeset_id: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Generate PR creation commands for all projects in a changeset.

    Returns the gh CLI commands to create cross-referenced PRs for each project
    in the changeset. Does not execute them — the caller should review and run.

    Args:
        changeset_id: Changeset ID (e.g. CS-PRJ-1) (alias: id)
        project: Optional project name (hub mode only)
        id: Alias for changeset_id — either spelling works; passing both with different values is an error
    """
    try:
        from .changesets import changeset_create_prs

        changeset_id = _resolve_id("changeset_id", changeset_id, id=id)
        store = _store(project)
        result = changeset_create_prs(store, changeset_id)
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Changeset Push",
    annotations=ToolAnnotations(
        title="Changeset Push", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_changeset_push(
    changeset_id: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Mark a changeset as merged and report status for hub ref updates.

    Checks all entries — if all are merged, marks the changeset as merged.
    If some are still pending, marks as partial and reports what's outstanding.

    Args:
        changeset_id: Changeset ID (e.g. CS-PRJ-1) (alias: id)
        project: Optional project name (hub mode only)
        id: Alias for changeset_id — either spelling works; passing both with different values is an error
    """
    try:
        changeset_id = _resolve_id("changeset_id", changeset_id, id=id)
        store = _store(project)
        meta, body = store.get_changeset(changeset_id)

        from datetime import date as _date

        merged = [e for e in meta.entries if e.status == "merged"]
        pending = [e for e in meta.entries if e.status != "merged"]

        if not pending:
            # All merged — update changeset status
            meta.status = ChangesetStatus.merged
            meta.updated = _date.today()
            post = frontmatter.Post(
                content=body,
                **meta.model_dump(mode="json"),
            )
            store._changeset_path(changeset_id).write_text(frontmatter.dumps(post))
            return _yaml_dump(
                {
                    "changeset": meta.id,
                    "status": "merged",
                    "message": "All PRs merged — safe to update hub submodule refs.",
                    "projects": [e.project for e in meta.entries],
                }
            )
        else:
            # Partial — update status
            if merged:
                meta.status = ChangesetStatus.partial
                meta.updated = _date.today()
                post = frontmatter.Post(
                    content=body,
                    **meta.model_dump(mode="json"),
                )
                store._changeset_path(changeset_id).write_text(frontmatter.dumps(post))

            return _yaml_dump(
                {
                    "changeset": meta.id,
                    "status": "partial",
                    "merged": [e.project for e in merged],
                    "pending": [
                        {"project": e.project, "ref": e.ref, "status": e.status}
                        for e in pending
                    ],
                    "message": "Not all PRs merged — do NOT update hub refs yet.",
                }
            )
    except Exception as e:
        raise _failed(e) from e


# ─── Sprint Tools ────────────────────────────────────────────────


@mcp.tool(
    title="Create Sprint",
    annotations=ToolAnnotations(
        title="Create Sprint", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_create_sprint(
    name: str,
    goal: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    planned_stories: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Create a sprint with a name, goal, dates, and planned stories.

    Args:
        name: Sprint name (e.g. "Sprint 1 — Auth & Onboarding")
        goal: Sprint goal summary
        start_date: Optional start date (YYYY-MM-DD)
        end_date: Optional end date (YYYY-MM-DD)
        planned_stories: Comma-separated story IDs (e.g. "US-PRJ-1,US-PRJ-2")
        project: Optional project name (hub mode only)

    Returns dependency warnings if planned stories have unmet external dependencies.
    """
    try:
        store = _store(project)
        story_list = (
            [s.strip() for s in planned_stories.split(",") if s.strip()]
            if planned_stories
            else []
        )

        # Check for dependency issues
        warnings = []
        if story_list:
            from .deps import incomplete_story_dependencies

            all_tasks = store.list_tasks()
            all_stories = store.list_stories()
            planned_set = set(story_list)

            for sid in story_list:
                try:
                    story_meta, _ = store.get_story(sid)
                    incomplete = incomplete_story_dependencies(
                        story_meta, all_tasks, all_stories
                    )
                    # Filter to external dependencies (not in this sprint)
                    external_deps = [d for d in incomplete if d not in planned_set]
                    if external_deps:
                        warnings.append(
                            f"{sid} has unmet dependencies: {', '.join(external_deps)}"
                        )
                except FileNotFoundError:
                    warnings.append(f"{sid} not found")

        meta = store.create_sprint(
            name=name,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
            planned_stories=story_list,
        )
        result = {"created": meta.model_dump(mode="json")}
        if warnings:
            result["dependency_warnings"] = warnings
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Get Sprint",
    annotations=ToolAnnotations(title="Get Sprint", readOnlyHint=True),
)
def pm_get_sprint(
    sprint_id: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """View sprint details with live progress per story.

    Shows each planned story's status, task completion ratio, and dependency status.

    Args:
        sprint_id: Sprint ID (e.g. SPRINT-PRJ-1) (alias: id)
        project: Optional project name (hub mode only)
        id: Alias for sprint_id — either spelling works; passing both with different values is an error
    """
    try:
        sprint_id = _resolve_id("sprint_id", sprint_id, id=id)
        store = _store(project)
        meta, body = store.get_sprint(sprint_id)
        result = meta.model_dump(mode="json")

        # Load all data for dependency checks
        from .deps import incomplete_story_dependencies

        all_tasks = store.list_tasks()
        all_stories = store.list_stories()
        planned_set = set(meta.planned_stories)

        # Compute live progress per story with dependency status
        story_progress = []
        for sid in meta.planned_stories:
            try:
                story_meta, _ = store.get_story(sid)
                # Archived tasks were abandoned mid-sprint: they are neither
                # done nor still owed, so they drop out of the ratio entirely.
                tasks = store.list_tasks(story_id=sid, archived=False)
                done_tasks = [t for t in tasks if t.status.value == "done"]

                # Check dependencies
                incomplete = incomplete_story_dependencies(
                    story_meta, all_tasks, all_stories
                )
                # Split into internal (in sprint) and external (outside sprint)
                internal_deps = [d for d in incomplete if d in planned_set]
                external_deps = [d for d in incomplete if d not in planned_set]

                entry = {
                    "story_id": sid,
                    "title": story_meta.title,
                    "status": story_meta.status.value,
                    "tasks_done": len(done_tasks),
                    "tasks_total": len(tasks),
                    "points": story_meta.points,
                }
                if story_meta.depends_on:
                    entry["depends_on"] = story_meta.depends_on
                if internal_deps:
                    entry["blocked_by_in_sprint"] = internal_deps
                if external_deps:
                    entry["blocked_by_external"] = external_deps

                story_progress.append(entry)
            except Exception:
                story_progress.append(
                    {
                        "story_id": sid,
                        "status": "removed",
                        "tasks_done": 0,
                        "tasks_total": 0,
                    }
                )

        # Compute suggested execution order based on dependencies
        # Stories with no incomplete deps come first
        ready_stories = [
            s
            for s in story_progress
            if not s.get("blocked_by_in_sprint") and s.get("status") != "done"
        ]
        blocked_stories = [s for s in story_progress if s.get("blocked_by_in_sprint")]

        result["story_progress"] = story_progress
        if ready_stories:
            result["ready_to_work"] = [s["story_id"] for s in ready_stories]
        if blocked_stories:
            result["blocked_in_sprint"] = [
                {"story_id": s["story_id"], "waiting_on": s["blocked_by_in_sprint"]}
                for s in blocked_stories
            ]
        result["body"] = body
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="List Sprints",
    annotations=ToolAnnotations(title="List Sprints", readOnlyHint=True),
)
def pm_list_sprints(
    status: Optional[str] = None,
    project: Optional[str] = None,
    brief: bool = False,
    fields: Optional[str] = None,
) -> str:
    """List sprints, optionally filtered by status.

    Every sprint comes back with its full goal, which on a long history is
    most of the payload by weight. When you want the shape of the history
    rather than its prose — `pm_list_sprints(status="completed", brief=True)`
    returns dates, points and planned stories without the goals. `fields`
    gives the same per-key control as `pm_get` when the preset is not the cut
    you want.

    Args:
        status: Optional filter: planning, active, completed, cancelled
        project: Optional project name (hub mode only)
        brief: Drop the free-text (default false). Keeps id, name, status, start_date, end_date, planned_points, completed_points and planned_stories, and omits goal. Use it to scan a sprint history: pm_list_sprints(status="completed", brief=True).
        fields: Comma-separated key names to return, e.g. "status,completed_points" — everything else is omitted and `id` is always kept, exactly as on pm_get. An unknown name is an error listing the valid ones. If both are given, `fields` wins — explicit beats preset. Omit both for the full sprints; `count` is always present and the default is unchanged.
    """
    try:
        store = _store(project)
        names = _field_names(fields)
        sprints = [s.model_dump(mode="json") for s in store.list_sprints(status=status)]
        if names is not None:
            # Explicit beats preset: `fields` wins over `brief`.
            sprints = [
                _project_item(s, names, "sprint") for s in sprints
            ]
        elif brief:
            sprints = [_brief_item(s, BRIEF_SPRINT_FIELDS) for s in sprints]
        return _yaml_dump({"sprints": sprints, "count": len(sprints)})
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Update Sprint",
    annotations=ToolAnnotations(
        title="Update Sprint", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_update_sprint(
    sprint_id: Optional[str] = None,
    name: Optional[str] = None,
    status: Optional[str] = None,
    goal: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    planned_stories: Optional[str] = None,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Update sprint fields (status, stories, dates, etc.).

    When status is set to 'completed', completed_points is auto-computed from done stories.

    Args:
        sprint_id: Sprint ID (e.g. SPRINT-PRJ-1) (alias: id)
        name: New sprint name
        status: New status: planning, active, completed, cancelled
        goal: Updated sprint goal
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        planned_stories: Comma-separated story IDs (replaces current list)
        project: Optional project name (hub mode only)
        id: Alias for sprint_id — either spelling works; passing both with different values is an error

    Returns dependency warnings if new planned stories have unmet dependencies.
    """
    try:
        sprint_id = _resolve_id("sprint_id", sprint_id, id=id)
        store = _store(project)
        kwargs = {}
        if name is not None:
            kwargs["name"] = name
        if status is not None:
            kwargs["status"] = status
        if goal is not None:
            kwargs["goal"] = goal
        if start_date is not None:
            kwargs["start_date"] = start_date
        if end_date is not None:
            kwargs["end_date"] = end_date

        story_list = None
        if planned_stories is not None:
            story_list = [s.strip() for s in planned_stories.split(",") if s.strip()]
            kwargs["planned_stories"] = story_list

        meta = store.update_sprint(sprint_id, **kwargs)
        result = {"updated": meta.model_dump(mode="json")}

        # Check for dependency issues if stories were updated
        if story_list:
            from .deps import incomplete_story_dependencies

            all_tasks = store.list_tasks()
            all_stories = store.list_stories()
            planned_set = set(story_list)
            warnings = []

            for sid in story_list:
                try:
                    story_meta, _ = store.get_story(sid)
                    incomplete = incomplete_story_dependencies(
                        story_meta, all_tasks, all_stories
                    )
                    external_deps = [d for d in incomplete if d not in planned_set]
                    if external_deps:
                        warnings.append(
                            f"{sid} has unmet dependencies: {', '.join(external_deps)}"
                        )
                except FileNotFoundError:
                    pass

            if warnings:
                result["dependency_warnings"] = warnings

        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


# ─── Web Server Tools ───────────────────────────────────────────

import subprocess
import socket

_web_process: Optional[subprocess.Popen] = None
_web_host: Optional[str] = None
_web_port: Optional[int] = None


def _port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


@mcp.tool(
    title="Start Web UI",
    annotations=ToolAnnotations(
        title="Start Web UI", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_web_start(host: str = "127.0.0.1", port: int = 8000) -> str:
    """Start the ProjectMan web dashboard as a background server.

    Returns the URL on success, or an error if the port is in use (try a different port).

    Args:
        host: Host/IP to bind to (default 127.0.0.1, use 0.0.0.0 for all interfaces)
        port: Port to listen on (default 8000, try another if this is taken)
    """
    global _web_process, _web_host, _web_port

    # Already running?
    if _web_process is not None and _web_process.poll() is None:
        return _yaml_dump(
            {
                "status": "already_running",
                "url": f"http://{_web_host}:{_web_port}",
                "pid": _web_process.pid,
            }
        )

    # Check port availability
    if not _port_available(host, port):
        raise ToolError(
            f"Port {port} is already in use. "
            f"Try port {port + 1} or another available port"
        )

    # Check web dependencies
    try:
        import uvicorn  # noqa: F401
        import fastapi  # noqa: F401
    except ImportError as e:
        raise ToolError(
            "Web dependencies not installed. Install with: pip install projectman[web]"
        ) from e

    # Find project root for the working directory
    try:
        root = find_project_root()
    except Exception as e:
        raise ToolError(f"No project found: {e}") from e

    # Start uvicorn as a subprocess
    try:
        import sys

        _web_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "projectman.web.app:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _web_host = host
        _web_port = port

        return _yaml_dump(
            {
                "status": "started",
                "url": f"http://{host}:{port}",
                "pid": _web_process.pid,
            }
        )
    except Exception as e:
        _web_process = None
        raise _failed(e) from e


@mcp.tool(
    title="Stop Web UI",
    annotations=ToolAnnotations(
        title="Stop Web UI", readOnlyHint=False, destructiveHint=False
    ),
)
def pm_web_stop() -> str:
    """Stop the running ProjectMan web server."""
    global _web_process, _web_host, _web_port

    if _web_process is None or _web_process.poll() is not None:
        _web_process = None
        _web_host = None
        _web_port = None
        return _yaml_dump({"status": "not_running"})

    pid = _web_process.pid
    try:
        _web_process.terminate()
        try:
            _web_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _web_process.kill()
            _web_process.wait(timeout=3)
    except Exception as e:
        raise _failed(e) from e
    finally:
        _web_process = None
        _web_host = None
        _web_port = None

    return _yaml_dump({"status": "stopped", "pid": pid})


@mcp.tool(
    title="Web UI Status",
    annotations=ToolAnnotations(title="Web UI Status", readOnlyHint=True),
)
def pm_web_status() -> str:
    """Check if the ProjectMan web server is running and on what host/port."""
    global _web_process, _web_host, _web_port

    if _web_process is None:
        return _yaml_dump({"running": False})

    if _web_process.poll() is not None:
        # Process exited
        exit_code = _web_process.returncode
        _web_process = None
        _web_host = None
        _web_port = None
        return _yaml_dump({"running": False, "exited_with": exit_code})

    return _yaml_dump(
        {
            "running": True,
            "url": f"http://{_web_host}:{_web_port}",
            "pid": _web_process.pid,
            "host": _web_host,
            "port": _web_port,
        }
    )


# ─── Activity Log ───────────────────────────────────────────────


@mcp.tool(
    title="Activity Log",
    annotations=ToolAnnotations(title="Activity Log", readOnlyHint=True),
)
def pm_activity(
    item_id: Optional[str] = None,
    event_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    project: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    """Query the activity log for project mutations.

    Args:
        item_id: Filter by item ID (e.g. US-PRJ-1) (alias: id)
        event_type: Filter by event type: create, update, delete, archive
        from_date: Filter from date (ISO 8601, e.g. 2026-01-01)
        to_date: Filter to date (ISO 8601, e.g. 2026-12-31)
        actor: Filter by actor name
        limit: Max entries to return (default 20)
        offset: Starting index for pagination (default 0)
        project: Optional project name (hub mode only)
        id: Alias for item_id — either spelling works; passing both with different values is an error
    """
    import json
    from datetime import datetime

    try:
        # Optional filter, so "neither" means "no filter" rather than an error.
        item_id = _resolve_id("item_id", item_id, required=False, id=id)
        pm_dir = _resolve_project_dir(project)
        log_path = pm_dir / "activity.jsonl"

        if not log_path.exists():
            return _yaml_dump(
                {"entries": [], "total": 0, "message": "No activity log found"}
            )

        # Parse all entries
        entries = []
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # Apply filters
        if item_id:
            entries = [e for e in entries if e.get("item_id") == item_id]
        if event_type:
            entries = [e for e in entries if e.get("event_type") == event_type]
        if actor:
            entries = [e for e in entries if e.get("actor") == actor]
        if from_date:
            from_dt = datetime.fromisoformat(from_date)
            entries = [
                e for e in entries if datetime.fromisoformat(e["timestamp"]) >= from_dt
            ]
        if to_date:
            to_dt = datetime.fromisoformat(to_date)
            entries = [
                e for e in entries if datetime.fromisoformat(e["timestamp"]) <= to_dt
            ]

        total = len(entries)

        # Most recent first, then paginate
        entries = list(reversed(entries))
        entries = entries[offset : offset + limit]

        # Format human-readable output
        formatted = []
        for e in entries:
            ts = e.get("timestamp", "?")
            line_parts = [
                f"[{ts}]",
                e.get("event_type", "?").upper(),
                e.get("item_type", "?"),
                e.get("item_id", "?"),
            ]
            if e.get("actor"):
                line_parts.append(f"by {e['actor']}")
            changes = e.get("changes", {})
            if changes:
                change_strs = []
                for field, val in changes.items():
                    if isinstance(val, dict) and "before" in val and "after" in val:
                        change_strs.append(f"{field}: {val['before']} → {val['after']}")
                    else:
                        change_strs.append(f"{field}: {val}")
                if change_strs:
                    line_parts.append(f"({', '.join(change_strs)})")
            formatted.append(" ".join(line_parts))

        result = {
            "total": total,
            "showing": f"{offset + 1}-{offset + len(entries)} of {total}"
            if entries
            else "0 of 0",
            "entries": formatted,
        }
        return _yaml_dump(result)
    except Exception as e:
        raise _failed(e) from e


@mcp.tool(
    title="Run Log", annotations=ToolAnnotations(title="Run Log", readOnlyHint=True)
)
def pm_run_log(
    id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    project: Optional[str] = None,
    task_id: Optional[str] = None,
    has_evidence: Optional[bool] = None,
) -> str:
    """Read the run log for an epic, story, or task. Returns a JSON array of log entries
    showing previous work attempts, outcomes, notes and any structured evidence.

    Args:
        id: Epic, story, or task ID (alias: task_id)
        limit: Max entries to return (default 20, most recent first)
        offset: Number of entries to skip
        project: Optional project name (hub mode only)
        task_id: Alias for id — either spelling works; passing both with different values is an error
        has_evidence: Filter by structured evidence — true returns only entries carrying an `evidence` object, false only those without, omitted returns everything. "Did this completion prove anything" is this one call. An `evidence` present but with all lists empty counts as evidence: it explicitly says "nothing to show".

    Each entry carries its `evidence` verbatim when it has one, and omits the
    key entirely when it does not.
    """
    try:
        import json

        id = _resolve_id("id", id, task_id=task_id)
        store = _store(project)
        entries = store.get_run_log(
            id, limit=limit, offset=offset, has_evidence=has_evidence
        )
        # Every pre-existing key keeps its place and its null; only the new
        # `evidence` key is dropped when absent, so an entry without evidence
        # is byte-for-byte the response it was before this field existed.
        result = []
        for e in entries:
            dumped = e.model_dump(mode="json")
            if dumped.get("evidence") is None:
                dumped.pop("evidence", None)
            result.append(dumped)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        raise _failed(e) from e


def run_server(
    transport: str = "stdio", host: str = "127.0.0.1", port: int = 22001
) -> None:
    """Run the MCP server with the specified transport.

    Args:
        transport: "stdio" or "sse"
        host: Host to bind to (SSE mode only)
        port: Port to bind to (SSE mode only)
    """
    global _event_bus

    if transport == "sse":
        mcp.settings.host = host
        mcp.settings.port = port

        # Activate real event bus and register orchestrator REST/SSE routes
        _event_bus = EventBus()
        from .orchestrator_api import register_routes

        register_routes(mcp, _event_bus, _store)

        # Also serve the full Web UI + REST API on the same port. The web app
        # is mounted with lowest precedence, so the MCP transport routes
        # (/sse, /messages/) and the orchestrator routes registered above win
        # for their exact paths; the web app handles everything else.
        from starlette.routing import Mount

        from .web.app import app as web_app

        root = find_project_root()
        web_app.state.root = root
        web_app.state.store = Store(root)
        mcp._custom_starlette_routes.append(Mount("/", app=web_app))

    mcp.run(transport=transport)
