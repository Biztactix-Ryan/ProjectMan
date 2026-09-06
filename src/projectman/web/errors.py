"""HTTP mapping for ProjectMan's coded errors (US-PM-33).

The MCP layer turns an exception into a wire ``code`` with
:func:`projectman.errors.wire_code_for`.  The web layer needs the same
vocabulary *plus* an HTTP status, so a create that refuses because the target
ID is taken comes back as ``409 Conflict`` rather than as a 500 traceback.

Every mapped response carries the same body shape::

    {"detail": {"error": "<code>", "message": "<str(exc)>"}}

so a client can branch on ``detail.error`` exactly as an MCP client branches
on the tool error's code.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from projectman.errors import (
    ConflictError,
    ProjectManError,
    ValidationError,
    wire_code_for,
)

__all__ = [
    "STATUS_BY_CODE",
    "DEFAULT_STATUS",
    "http_code_for",
    "http_error",
    "coded_errors",
    "require_id_shape",
]

#: Error code -> HTTP status.  Anything not named here is a bug or an
#: unclassified failure and gets :data:`DEFAULT_STATUS`.
STATUS_BY_CODE: dict[str, int] = {
    "conflict": 409,
    "not_found": 404,
    "invalid": 422,
    "permission": 403,
}

#: Status for a code with no entry in :data:`STATUS_BY_CODE` (``store``,
#: ``internal``, ``error``).
DEFAULT_STATUS = 500


def http_code_for(exc: BaseException) -> str:
    """Return the error code the web layer reports for *exc*.

    Identical to :func:`projectman.errors.wire_code_for` except for one
    builtin it does not cover: ``Store.create_*`` refuses an already-occupied
    target with :class:`FileExistsError` (the contract US-PM-24 pinned, and
    the one ``tests/test_creates_never_overwrite.py`` asserts).  That is a
    clash with existing state, so it reports ``conflict``.
    """
    if isinstance(exc, ProjectManError):
        return wire_code_for(exc)
    if isinstance(exc, FileExistsError):
        return ConflictError.code
    return wire_code_for(exc)


def http_error(exc: BaseException) -> HTTPException:
    """Build the :class:`HTTPException` that represents *exc*."""
    code = http_code_for(exc)
    return HTTPException(
        status_code=STATUS_BY_CODE.get(code, DEFAULT_STATUS),
        detail={"error": code, "message": str(exc)},
    )


@contextmanager
def coded_errors() -> Iterator[None]:
    """Translate ProjectMan's coded errors into HTTP responses.

    Pydantic's own :class:`ValidationError` is deliberately let through: it is
    a :class:`ValueError`, but the app already installs a handler that renders
    its per-field ``errors()`` as a 422, and that detail is more useful than a
    flattened message.
    """
    try:
        yield
    except HTTPException:
        raise
    except PydanticValidationError:
        raise
    except (ProjectManError, OSError, ValueError) as exc:
        raise http_error(exc) from exc


def require_id_shape(value: str, pattern: re.Pattern[str], kind: str) -> str:
    """Return *value*, or raise ``invalid`` if it is not a well-formed ID.

    The store answers a *malformed* ID the same way it answers an unknown one
    — "not found" — because it only ever asks whether the file exists.  That
    conflates "you typed nonsense" with "it isn't here", so the shape is
    checked here first, against the one set of patterns in ``models.py``.
    """
    if not isinstance(value, str) or not pattern.match(value):
        raise ValidationError(
            f"malformed {kind} id {value!r} — expected {pattern.pattern}"
        )
    return value
