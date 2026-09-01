"""Repeatable usage-telemetry analysis for ProjectMan MCP tool calls.

The four studies in `the original usage studies` were run as throwaway scratchpad scripts. This
package is the repo-resident port of that methodology so the numbers can be
reproduced and compared across fixes.

Currently implemented: the extraction pass (:mod:`tools.usage_telemetry.extract`),
failure classification (:mod:`tools.usage_telemetry.classify`), the usage
metrics report (:mod:`tools.usage_telemetry.report`) and the provenance-stamped
baseline capture/compare (:mod:`tools.usage_telemetry.baseline`) and the
``tools/list`` payload measurement (:mod:`tools.usage_telemetry.tool_list_size`). The baseline
lands on top of the other three without changing any of them -- see
``docs/telemetry/README.md`` for the capture and comparison procedure.

The single-call ``classify()`` function is deliberately *not* re-exported here:
binding it on the package would shadow the :mod:`tools.usage_telemetry.classify`
submodule, so ``from tools.usage_telemetry import classify`` always gives you
the module. Use ``classify.classify(call)`` or :func:`classify_all`. The same
applies to ``report``: the module wins, and the builder is :func:`build_report`.

The rest of the classification and report APIs are re-exported lazily (PEP 562).
Importing them eagerly here would make ``python -m tools.usage_telemetry.classify``
load the module twice and warn -- the CLIs are supported entry points, so the
convenience import gives way to them.
"""

import importlib
from typing import Any

from tools.usage_telemetry.extract import (
    DEFAULT_MIN_MATCH_RATE,
    TOOL_PREFIX,
    Extraction,
    MatchRateError,
    ScanStats,
    ToolCall,
    ToolResult,
    default_transcript_root,
    iter_transcript_files,
    scan,
    write_jsonl,
)

__all__ = [
    "DEFAULT_MIN_MATCH_RATE",
    "FAILURE_CLASSES",
    "HARD_ERROR",
    "MALFORMED_INPUT",
    "MALFORMED_INPUT_KEY",
    "PRECEDENCE",
    "SOFT_ERROR",
    "SOFT_ERROR_PATTERNS",
    "SUCCESS",
    "TOOL_PREFIX",
    "UNMATCHED",
    "CallClass",
    "Classification",
    "Distribution",
    "Extraction",
    "MatchRateError",
    "Run",
    "RunProfile",
    "ScanStats",
    "ToolBreakdown",
    "ToolCall",
    "ToolResult",
    "ToolUsage",
    "UsageReport",
    "build_report",
    "classify_all",
    "default_transcript_root",
    "format_report",
    "format_usage_report",
    "group_by_session",
    "is_hard_error",
    "is_malformed_input",
    "is_soft_error",
    "iter_bigrams",
    "iter_runs",
    "iter_transcript_files",
    "percentile",
    "report_from_extraction",
    "scan",
    "soft_error_message",
    "soft_error_pattern",
    "write_jsonl",
]

#: Names served from :mod:`tools.usage_telemetry.classify` on first access.
_LAZY_CLASSIFY = frozenset(
    {
        "FAILURE_CLASSES",
        "HARD_ERROR",
        "MALFORMED_INPUT",
        "MALFORMED_INPUT_KEY",
        "PRECEDENCE",
        "SOFT_ERROR",
        "SOFT_ERROR_PATTERNS",
        "SUCCESS",
        "UNMATCHED",
        "CallClass",
        "Classification",
        "ToolBreakdown",
        "classify_all",
        "format_report",
        "is_hard_error",
        "is_malformed_input",
        "is_soft_error",
        "soft_error_message",
        "soft_error_pattern",
    }
)

#: Names served from :mod:`tools.usage_telemetry.report` on first access.
_LAZY_REPORT = frozenset(
    {
        "Distribution",
        "Run",
        "RunProfile",
        "ToolUsage",
        "UsageReport",
        "build_report",
        "format_usage_report",
        "group_by_session",
        "iter_bigrams",
        "iter_runs",
        "percentile",
        "report_from_extraction",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_CLASSIFY:
        return getattr(importlib.import_module(f"{__name__}.classify"), name)
    if name in _LAZY_REPORT:
        return getattr(importlib.import_module(f"{__name__}.report"), name)
    # The submodules, never a same-named function from inside them.
    if name in ("baseline", "classify", "report"):
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | {"baseline", "classify", "extract", "report"})
