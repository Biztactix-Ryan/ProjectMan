// Which projectman MCP calls move the sprint band (US-PM-62-7). After one of
// them answers without error, register.ts re-reads the band so the person
// sees the new status without waiting for the turn to end.
//
// The tool names the model calls carry the server's prefix: a plugin install
// names the server `plugin_projectman_projectman`, so its tools are
// `mcp__plugin_projectman_projectman__pm_*`; a bare `projectman` server (an
// old install, or a dev checkout) gives `mcp__projectman__pm_*`. Both match.

/** Any projectman tool, under either server name; the name after the prefix is captured. */
export const PM_TOOL = /^mcp__(?:plugin_projectman_)?projectman__(pm_\w+)$/

/**
 * Every projectman tool that writes: those its server does not declare
 * `readOnlyHint=True`. tests/test_band_refresh.py holds this list equal to
 * the server's registry, so a new writing tool cannot be left out.
 */
// BEGIN PM_WRITE_TOOLS
export const PM_WRITE_TOOLS: readonly string[] = [
  'pm_accept',
  'pm_answer_decision',
  'pm_archive',
  'pm_archive_many',
  'pm_commit',
  'pm_create_decision',
  'pm_create_epic',
  'pm_create_sprint',
  'pm_create_story',
  'pm_create_task',
  'pm_create_tasks',
  'pm_done_next',
  'pm_grab',
  'pm_next',
  'pm_park',
  'pm_push',
  'pm_reindex',
  'pm_release',
  'pm_retry',
  'pm_review',
  'pm_update',
  'pm_update_doc',
  'pm_update_many',
  'pm_update_sprint',
]
// END PM_WRITE_TOOLS

const WRITES = new Set(PM_WRITE_TOOLS)

/** The pm tool a call names (`pm_update`), under either prefix; undefined for any other tool. */
export function pmToolName(tool: string): string | undefined {
  return PM_TOOL.exec(tool)?.[1]
}

/**
 * Whether a call, as sent, can change what the band shows: a writing pm
 * tool. `pm_next` writes only with `text` or `clear`; with neither it reads.
 */
export function movesBand(call: { tool: string } & Record<string, unknown>): boolean {
  const name = pmToolName(call.tool)
  if (name === undefined || !WRITES.has(name)) return false
  if (name === 'pm_next') return (call.text !== undefined && call.text !== null) || call.clear === true
  return true
}
