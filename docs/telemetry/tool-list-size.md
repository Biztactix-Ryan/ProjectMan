# Tool-list payload size

US-PM-15 gates three tool families behind config flags. This file is the
**measured** saving, so the context claim in
[`reference/mcp-tools.md`](../reference/mcp-tools.md) is a number and not an
assumption.

- Measured: **2026-10-20**
- Commit basis: **ab27c8f4493574d455724139aec94514e9625db2 (working tree dirty)**
- Command: `python -m tools.usage_telemetry.tool_list_size --markdown` (run from the repo root)
- Serialisation: `mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)` — exactly what the MCP
  session writes as the `result` of a `tools/list` request, so this moves if
  and only if the real payload moves.

## Headline

| configuration | tools | `tools/list` bytes |
| --- | ---: | ---: |
| all families enabled | 50 | 99,614 |
| default (`maintenance`, `web` all off) | 45 | 95,701 |
| **saved** | **5** | **3,913 (3.93%)** |

## Per family

`schema B` is the sum of the family's own tool JSON objects. `payload B` is
what the whole payload shrinks by when only that family is turned off — the
same bytes plus one framing comma per tool.

| family | tools | schema B | payload B |
| --- | ---: | ---: | ---: |
| `maintenance` | 2 | 2,265 | 2,267 |
| `web` | 3 | 1,643 | 1,646 |

## Keeping it honest

`tests/test_tool_list_size.py` re-runs the measurement and compares it to the
block below. If it fails, the payload moved: re-run the command above and
commit the regenerated file.

<!-- tool-list-size:measurement -->

```json
{
  "all_families": {
    "bytes": 99614,
    "tools": 50
  },
  "command": "python -m tools.usage_telemetry.tool_list_size --markdown",
  "default": {
    "bytes": 95701,
    "tools": 45
  },
  "families": {
    "maintenance": {
      "payload_delta_bytes": 2267,
      "schema_bytes": 2265,
      "tools": 2
    },
    "web": {
      "payload_delta_bytes": 1646,
      "schema_bytes": 1643,
      "tools": 3
    }
  },
  "reduction": {
    "bytes": 3913,
    "pct": 3.93,
    "tools": 5
  },
  "schema": "projectman.tool-list-size/1",
  "serialisation": "mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)"
}
```
