---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-10-07'
depends_on:
- US-PM-56-7
id: US-PM-59-6
points: 2
status: done
story_id: US-PM-59
tags: []
title: Add the mod skeleton to the plugin
updated: '2026-10-07'
---

hooks/hooks.json gains a modules entry pointing at hooks/register.ts; add types/index.d.ts contract, tsconfig extending the engine-laid one, and one *.test.ts. `claude plugin validate` and `claude plugin test` pass. Python-only CI keeps passing (mod tests run in a separate step).