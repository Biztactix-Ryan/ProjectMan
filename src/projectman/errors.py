"""Coded exception taxonomy for ProjectMan.

Every failure ProjectMan raises deliberately should carry a *machine-readable*
code alongside its human-readable message, so an MCP client can branch on the
kind of failure instead of pattern-matching English prose.

Backwards compatibility is the design constraint.  Callers (and a large body
of tests) already catch builtin exception types — ``except FileNotFoundError``,
``except ValueError``, ``except RuntimeError`` — and compare ``str(exc)``
against exact message text.  So each class here inherits *both* from
:class:`ProjectManError` (which supplies ``.code`` and ``.message``) *and* from
the builtin type that callers already catch.  Replacing a bare
``raise ValueError("...")`` with ``raise ValidationError("...")`` therefore
changes nothing an existing caller can observe, except that the exception now
also answers ``.code``.

This module must not import anything from the rest of the package: it is the
bottom of the dependency graph, so any module (``deps``, ``store``,
``worktree``, ``server``) can import it without a cycle.
"""

from __future__ import annotations

__all__ = [
    "ProjectManError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "StoreError",
    "PermissionDeniedError",
    "InternalError",
    "BUILTIN_ERROR_CODES",
    "ERROR_CODES",
    "ERROR_CLASSES",
    "GENERIC_ERROR_CODE",
    "code_for",
    "wire_code_for",
]


class ProjectManError(Exception):
    """Base class for every ProjectMan error that carries a code.

    Attributes:
        code: Short machine-readable identifier for the *kind* of failure
            (e.g. ``"not_found"``).  Defined per subclass as a class
            attribute, and overridable per instance via the keyword-only
            ``code`` argument.
        message: The human-readable message.  ``str(exc)`` is exactly this
            string — no code prefix, no decoration — because callers and
            tests compare message text directly.
    """

    #: Default code, used by any subclass that does not set its own.
    code: str = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(ProjectManError, FileNotFoundError):
    """A requested item (epic, story, task, sprint, doc, path) does not exist.

    Also a :class:`FileNotFoundError`, so existing
    ``except FileNotFoundError`` handlers keep working.
    """

    code = "not_found"


class ValidationError(ProjectManError, ValueError):
    """Caller input was malformed, out of range, or self-contradictory.

    Also a :class:`ValueError`, so existing ``except ValueError`` handlers
    keep working.
    """

    code = "invalid"


class ConflictError(ProjectManError, RuntimeError):
    """The request clashes with the current state of the project.

    Covers *expected negatives* — a task already claimed by someone else,
    a dependency cycle that blocks the requested ordering, nothing left to
    commit.  Also a :class:`RuntimeError`, so existing ``except RuntimeError``
    handlers keep working.
    """

    code = "conflict"


class StoreError(ProjectManError, RuntimeError):
    """The on-disk store or a git operation against it failed.

    Also a :class:`RuntimeError`, so existing ``except RuntimeError``
    handlers keep working.
    """

    code = "store"


class PermissionDeniedError(ProjectManError, PermissionError):
    """The filesystem (or the OS) refused the access the operation needed.

    Also a :class:`PermissionError`, so existing ``except PermissionError``
    handlers keep working.
    """

    code = "permission"


class InternalError(ProjectManError):
    """An unclassified failure — a bug, or an exception from a dependency.

    This is the *generic fallback* of the wire taxonomy: what
    :func:`wire_code_for` reports when nothing more specific applies, so a
    caller branching on codes always gets one it can recognise.
    """

    code = "internal"


#: Code reported for any exception that is not a :class:`ProjectManError`.
GENERIC_ERROR_CODE = ProjectManError.code

#: Every class in the taxonomy, in most-general-first order.
ERROR_CLASSES: tuple[type[ProjectManError], ...] = (
    ProjectManError,
    NotFoundError,
    ValidationError,
    ConflictError,
    StoreError,
    PermissionDeniedError,
    InternalError,
)

#: Every code the taxonomy can emit.  Iterable by callers that need to
#: document, validate, or exhaustively handle the set (e.g. the MCP error
#: envelope).  Order matches :data:`ERROR_CLASSES`.
ERROR_CODES: tuple[str, ...] = tuple(cls.code for cls in ERROR_CLASSES)


def code_for(exc: BaseException) -> str:
    """Return the error code for *exc*.

    A :class:`ProjectManError` answers its own ``.code``; anything else —
    a builtin, a third-party exception, a bug — falls back to
    :data:`GENERIC_ERROR_CODE`, so this never raises and always yields a
    code from :data:`ERROR_CODES`.
    """
    code = getattr(exc, "code", None)
    if isinstance(exc, ProjectManError) and isinstance(code, str) and code:
        return code
    return GENERIC_ERROR_CODE


#: Builtin exception types that map onto a taxonomy code, checked in order.
#: These are the types raised by code that predates the taxonomy (and by the
#: standard library itself), so a plain ``FileNotFoundError`` from ``open()``
#: still reaches the caller as ``not_found`` rather than as the fallback.
BUILTIN_ERROR_CODES: tuple[tuple[type[BaseException], str], ...] = (
    (FileNotFoundError, NotFoundError.code),
    (PermissionError, PermissionDeniedError.code),
    (ValueError, ValidationError.code),
)


def wire_code_for(exc: BaseException) -> str:
    """Return the code to put *on the wire* for *exc*.

    The difference from :func:`code_for`: that function answers "what code did
    this exception declare?" and deliberately refuses to guess for anything
    outside the taxonomy.  This one must always produce a *useful* code,
    because the caller sees it instead of the exception's type — so it also
    maps the builtins the pre-taxonomy code still raises, and falls back to
    :class:`InternalError`'s ``"internal"`` rather than the bare ``"error"``.

    Never raises; the result is always a member of :data:`ERROR_CODES`.
    """
    if isinstance(exc, ProjectManError):
        return code_for(exc)
    for builtin, code in BUILTIN_ERROR_CODES:
        if isinstance(exc, builtin):
            return code
    return InternalError.code
