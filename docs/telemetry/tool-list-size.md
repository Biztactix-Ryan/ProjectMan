# Tool-list payload size

US-PM-15 gates three tool families behind config flags. This file is the
**measured** saving, so the context claim in
[`reference/mcp-tools.md`](../reference/mcp-tools.md) is a number and not an
assumption.

- Measured: **2026-09-05**
- Commit basis: **10610849baf0f8fe3edcd41a19dd800c752ad5f1 (working tree dirty)**
- Command: `python -m tools.usage_telemetry.tool_list_size --markdown` (run from the repo root)
- Serialisation: `mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)` — exactly what the MCP
  session writes as the `result` of a `tools/list` request, so this moves if
  and only if the real payload moves.

## Headline

| configuration | tools | `tools/list` bytes |
| --- | ---: | ---: |
| all families enabled | 50 | 97,449 |
| default (`maintenance`, `web` all off) | 42 | 91,084 |
| **saved** | **8** | **6,365 (6.53%)** |

## Per family

`schema B` is the sum of the family's own tool JSON objects. `payload B` is
what the whole payload shrinks by when only that family is turned off — the
same bytes plus one framing comma per tool.

| family | tools | schema B | payload B |
| --- | ---: | ---: | ---: |
| `maintenance` | 5 | 4,714 | 4,719 |
| `web` | 3 | 1,643 | 1,646 |

## Keeping it honest

`tests/test_tool_list_size.py` re-runs the measurement and compares it to the
block below. If it fails, the payload moved: re-run the command above and
commit the regenerated file.

<!-- tool-list-size:measurement -->

```json
{
  "all_families": {
    "bytes": 97449,
    "tools": 50
  },
  "command": "python -m tools.usage_telemetry.tool_list_size --markdown",
  "default": {
    "bytes": 91084,
    "tools": 42
  },
  "families": {
    "maintenance": {
      "payload_delta_bytes": 4719,
      "schema_bytes": 4714,
      "tools": 5
    },
    "web": {
      "payload_delta_bytes": 1646,
      "schema_bytes": 1643,
      "tools": 3
    }
  },
  "reduction": {
    "bytes": 6365,
    "pct": 6.53,
    "tools": 8
  },
  "schema": "projectman.tool-list-size/1",
  "serialisation": "mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)"
}
```
