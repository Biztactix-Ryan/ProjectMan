# Tool-list payload size

US-PM-15 gates three tool families behind config flags. This file is the
**measured** saving, so the context claim in
[`reference/mcp-tools.md`](../reference/mcp-tools.md) is a number and not an
assumption.

- Measured: **2026-09-06**
- Commit basis: **0930a7bdc59b9b41daf4e98c0e2d18e4efedaa5f (working tree dirty)**
- Command: `python -m tools.usage_telemetry.tool_list_size --markdown` (run from the repo root)
- Serialisation: `mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)` — exactly what the MCP
  session writes as the `result` of a `tools/list` request, so this moves if
  and only if the real payload moves.

## Headline

| configuration | tools | `tools/list` bytes |
| --- | ---: | ---: |
| all families enabled | 47 | 92,596 |
| default (`maintenance`, `web` all off) | 42 | 88,385 |
| **saved** | **5** | **4,211 (4.55%)** |

## Per family

`schema B` is the sum of the family's own tool JSON objects. `payload B` is
what the whole payload shrinks by when only that family is turned off — the
same bytes plus one framing comma per tool.

| family | tools | schema B | payload B |
| --- | ---: | ---: | ---: |
| `maintenance` | 2 | 2,563 | 2,565 |
| `web` | 3 | 1,643 | 1,646 |

## Keeping it honest

`tests/test_tool_list_size.py` re-runs the measurement and compares it to the
block below. If it fails, the payload moved: re-run the command above and
commit the regenerated file.

<!-- tool-list-size:measurement -->

```json
{
  "all_families": {
    "bytes": 92596,
    "tools": 47
  },
  "command": "python -m tools.usage_telemetry.tool_list_size --markdown",
  "default": {
    "bytes": 88385,
    "tools": 42
  },
  "families": {
    "maintenance": {
      "payload_delta_bytes": 2565,
      "schema_bytes": 2563,
      "tools": 2
    },
    "web": {
      "payload_delta_bytes": 1646,
      "schema_bytes": 1643,
      "tools": 3
    }
  },
  "reduction": {
    "bytes": 4211,
    "pct": 4.55,
    "tools": 5
  },
  "schema": "projectman.tool-list-size/1",
  "serialisation": "mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)"
}
```
