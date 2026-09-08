---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-38-5
points: 1
status: done
story_id: US-PM-38
tags: []
title: Make the --apply default assertion hold across click versions
updated: '2026-09-07'
---

In tests/test_migrate_archived_as_done.py::TestTheDocstringMatchesTheCode::test_report_is_the_default_at_every_entry_point the check `apply_opt.default is False` fails because the installed click reports Sentinel.UNSET for an is_flag option. Prove the claim behaviourally instead: invoke `migrate-archived` through click's CliRunner on a tmp store without --apply and assert the report path ran and no task file changed, or resolve the option's effective default via click's own API (`apply_opt.get_default(ctx)` / `flag_value`) and assert it is falsy. Keep the inspect.signature check on migrate_archived_as_done itself. Run the file: 0 failures.