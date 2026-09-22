---
assignee: claude
created: '2026-02-17'
id: US-PRJ-8-7
points: 2
status: done
story_id: US-PRJ-8
title: Add formatted CLI output with attention-priority sorting
updated: '2026-02-28'
---

Add `projectman git-status` CLI command with a compact, scannable table.

Output format (one line per project, sorted by severity):
```
Hub Git Status (5 projects)

  Project     Branch        Deploy    Dirty  Ahead/Behind  PRs  Issues
  api         pm/US-1/auth  main      2 mod  3/0           1    
  web         main          main             0/5                behind remote
  worker      feature-x     main                                bad branch name
  shared      main          main             0/0           0    
  docs        (detached)    main                                detached HEAD

3 issues found. Run `projectman git-status --verbose` for details.
```

Sorting priority: issues first (misaligned > detached > dirty > behind), clean repos last.

`--verbose` flag shows: full last commit info, PR titles, dirty file list.
`--json` flag outputs raw structured data (for MCP tool consumption).

Files: src/projectman/cli.py