---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-53-8
id: US-PM-53-9
points: 2
status: done
story_id: US-PM-53
tags: []
title: Document lanes in orchestrate-design.md, update tests and rendered copies
updated: '2026-09-09'
---

orchestrate-design.md gains a Lanes section: why two lanes and not more (one validator context at a time, and merge conflicts grow with the number of concurrent branches), the compatibility rule and where it is computed, the merge-order rule and what the retry-then-park path protects. Update docs/reference/skills.md, adjust the skill-content tests for --lanes wording, regenerate rendered copies via scratchpad + cp.