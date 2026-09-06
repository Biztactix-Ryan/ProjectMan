---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-38-4
points: 1
status: todo
story_id: US-PM-38
tags: []
title: Pin the pre-rewrite orchestrate template to commit 1061084 in both history
  tests
updated: '2026-09-06'
---

In tests/test_orchestrate_design_doc.py (head_template) and tests/test_orchestrate_skill_size.py (test_the_size_check_would_have_failed_on_the_pre_rewrite_template) replace `git show HEAD:...` with `git show 1061084:src/projectman/templates/skill_pm_orchestrate.md.j2`, the last commit before the US-PM-25-6 rewrite (31,731 bytes). Put the SHA in one named constant per file with a comment saying why it is a SHA and not HEAD. When git cannot show that object (tarball, shallow clone) the design-doc tests pytest.skip with a reason; the size guard keeps its existing padding fallback. Rename head_template to pre_rewrite_template and update docstrings that say HEAD. Run both files: 0 failures.