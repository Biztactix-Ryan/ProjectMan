# Tool-list payload size

US-PM-15 gates three tool families behind config flags. This file is the
**measured** saving, so the context claim in
[`reference/mcp-tools.md`](../reference/mcp-tools.md) is a number and not an
assumption.

- Measured: **2026-08-21**
- Commit basis: **c7b69d927aa7249fc3d0bbf6d7a6907381a24d5c (working tree dirty)**
- Command: `python -m tools.usage_telemetry.tool_list_size --markdown` (run from the repo root)
- Serialisation: `mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)` — exactly what the MCP
  session writes as the `result` of a `tools/list` request, so this moves if
  and only if the real payload moves.

## Headline

| configuration | tools | `tools/list` bytes |
| --- | ---: | ---: |
| all families enabled | 54 | 98,175 |
| default (`changesets`, `maintenance`, `web` all off) | 41 | 86,347 |
| **saved** | **13** | **11,828 (12.05%)** |

## Per family

`schema B` is the sum of the family's own tool JSON objects. `payload B` is
what the whole payload shrinks by when only that family is turned off — the
same bytes plus one framing comma per tool.

| family | tools | schema B | payload B |
| --- | ---: | ---: | ---: |
| `changesets` | 5 | 5,455 | 5,460 |
| `maintenance` | 5 | 4,717 | 4,722 |
| `web` | 3 | 1,643 | 1,646 |

## Keeping it honest

`tests/test_tool_list_size.py` re-runs the measurement and compares it to the
block below. If it fails, the payload moved: re-run the command above and
commit the regenerated file.

<!-- tool-list-size:measurement -->

```json
{
  "all_families": {
    "bytes": 98175,
    "tools": 54
  },
  "command": "python -m tools.usage_telemetry.tool_list_size --markdown",
  "default": {
    "bytes": 86347,
    "tools": 41
  },
  "families": {
    "changesets": {
      "payload_delta_bytes": 5460,
      "schema_bytes": 5455,
      "tools": 5
    },
    "maintenance": {
      "payload_delta_bytes": 4722,
      "schema_bytes": 4717,
      "tools": 5
    },
    "web": {
      "payload_delta_bytes": 1646,
      "schema_bytes": 1643,
      "tools": 3
    }
  },
  "reduction": {
    "bytes": 11828,
    "pct": 12.05,
    "tools": 13
  },
  "schema": "projectman.tool-list-size/1",
  "serialisation": "mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)"
}
```
