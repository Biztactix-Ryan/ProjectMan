import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ToolCallInput } from 'claude-code'
import type { ProjectmanBoardView, ProjectmanGuardDenial } from '../types'
import { BOARD_OPENED, BOARD_PANE, BOARD_PANE_TITLE, boardPane } from './board-pane.tsx'
import { findBannedGit, GIT_RULE_REASON } from './git-guard.ts'
import { absolutize, mentionsStore, STORE_RULE_REASON, storeHit, storeRoots, targetOf } from './store-guard.ts'
import type { ResolveFn } from './store-guard.ts'
import {
  boardColumns,
  formatCommand,
  MCP_SERVER_KEY,
  parseYaml,
  PM_BOARD,
  PM_COMMANDS,
  resultText,
  summarizeCommand,
} from './pm-views.ts'
import type { PmCommand, Yaml } from './pm-views.ts'
import { viewMode } from './surface.ts'

/** What the board pane draws (US-PM-60-7): null until the board is first read. */
const board = atom({ plugin: 'projectman', key: 'board' } as const, null as ProjectmanBoardView | null)

/** A command's MCP answers, parsed and in order, or why they could not be had. */
type Fetched = { results: Yaml[] } | { error: string }

/** Calls a command's projectman MCP tools straight from the mod: no model request. */
async function fetchCommand($: EngineInterface, command: PmCommand): Promise<Fetched> {
  const connected = await $.mcp.connect(MCP_SERVER_KEY)
  if (!connected.isConnected) {
    return { error: `ProjectMan: the projectman MCP server is not connected (${connected.message})` }
  }
  const results: Yaml[] = []
  for (const call of command.calls) {
    const answer = await $.mcp.call(connected.server, call.tool, call.args)
    const text = resultText(answer)
    if (answer.isError) return { error: `ProjectMan: ${call.tool} failed: ${text.trim() || 'no detail'}` }
    results.push(parseYaml(text))
  }
  return { results }
}

/** The board as read: columns from `pm_board`, one more load counted. */
function loaded(previous: ProjectmanBoardView | null, data: Yaml): ProjectmanBoardView {
  return { columns: boardColumns(data), loads: (previous?.loads ?? 0) + 1, isRefreshing: false, error: null }
}

/**
 * The refresh button: re-reads `pm_board` and writes `projectman.board`,
 * which redraws the pane. A press while a read is in flight does nothing; a
 * failed read keeps the previous columns and shows why.
 */
async function refreshBoard($: EngineInterface): Promise<void> {
  if ((await read($, board))?.isRefreshing) return
  await update($, board, (v) => ({ columns: v?.columns ?? [], loads: v?.loads ?? 0, isRefreshing: true, error: null }))
  let outcome: Fetched
  try {
    outcome = await fetchCommand($, PM_BOARD)
  } catch {
    outcome = { error: "ProjectMan: could not read the projectman MCP server's answer" }
  }
  const done = outcome
  await update($, board, (v) =>
    'results' in done
      ? loaded(v, done.results[0] ?? null)
      : { columns: v?.columns ?? [], loads: v?.loads ?? 0, isRefreshing: false, error: done.error },
  )
}

/**
 * The drawing path, where a surface draws. /pm-board writes the board to
 * `projectman.board` and opens it as a pane (US-PM-60-7); a pane the surface
 * could not seat leaves the full view as text. The status and next-task
 * views answer with their full view as text.
 */
async function drawView($: EngineInterface, command: PmCommand, results: readonly Yaml[]): Promise<{ text: string }> {
  if (command !== PM_BOARD) return { text: formatCommand(command, results) }
  await update($, board, (v) => loaded(v, results[0] ?? null))
  const opened = await $.ui.open({ id: BOARD_PANE, title: BOARD_PANE_TITLE }).catch(() => undefined)
  if (opened?.isPlaced !== true) return { text: formatCommand(command, results) }
  return { text: BOARD_OPENED }
}

// ProjectMan orchestration guards (US-PM-59). Enforce the worker rules on tool
// calls in-process instead of in skill prose.
//
// Scope: a call made inside a subagent's loop (the event carries `agentId`) is
// guarded by default; the main session is guarded only when the
// `guard_main_session` userConfig option is on, so the interactive user is
// not blocked.

const lastDenial = { plugin: 'projectman', key: 'lastDenial' } as const

export const register: Register = (on, options) => {
  const guardMain = options.guard_main_session === true
  const inScope = (e: ToolCallInput) => e.agentId !== undefined || guardMain

  // US-PM-59-7: Bash running git checkout / restore / stash.
  const bannedGit = (e: ToolCallInput): string | undefined =>
    e.tool === 'Bash' && inScope(e) ? findBannedGit(e.command) : undefined

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const hit = bannedGit(e)
    if (hit === undefined) return next(e)
    const denial: ProjectmanGuardDenial = { rule: `git ${hit}`, tool: e.tool, reason: GIT_RULE_REASON }
    try {
      await $.state.set(lastDenial, denial)
    } catch {
      // Recording is a convenience; the refusal stands without it.
    }
    return { deny: GIT_RULE_REASON }
  }).catch(($, e, next) => {
    if (next.called) return next(e)
    // Re-entry or a failed hook: judge from `e` alone, refuse if unsure.
    try {
      return bannedGit(e) === undefined ? next(e) : { deny: GIT_RULE_REASON }
    } catch {
      return { deny: `${GIT_RULE_REASON} (the ProjectMan guard failed to read this command)` }
    }
  })

  // US-PM-59-8: Write / Edit / NotebookEdit (MultiEdit where a build has it)
  // aimed at the real .project store. MCP tools (mcp__projectman__*) are a
  // different tool name and never match.
  on('tool.call', { tool: ['Write', 'Edit', 'NotebookEdit', /^MultiEdit$/] }, async ($, e, next) => {
    if (!inScope(e)) return next(e)
    const target = targetOf(e as unknown as { tool: string } & Record<string, unknown>)
    if (target === undefined) return next(e)
    // Where a path lands, every link followed; undefined when it does not stat.
    const resolve: ResolveFn = (path) =>
      $.fs
        .stat(path, { resolve: true })
        .then((s) => s.realPath)
        .catch(() => undefined)
    const root = await $.session.root()
    const cwd = await $.session.cwd()
    const roots = await storeRoots([root, cwd], resolve)
    const hit = await storeHit(absolutize(target, cwd), roots, resolve)
    if (hit === undefined) return next(e)
    const denial: ProjectmanGuardDenial = { rule: 'store write', tool: e.tool, reason: STORE_RULE_REASON }
    try {
      await $.state.set(lastDenial, denial)
    } catch {
      // Recording is a convenience; the refusal stands without it.
    }
    return { deny: STORE_RULE_REASON }
  }).catch(($, e, next) => {
    if (next.called) return next(e)
    // Re-entry or a failed hook: judge the spelling alone, refuse if it names the store.
    try {
      if (!inScope(e)) return next(e)
      const target = targetOf(e as unknown as { tool: string } & Record<string, unknown>)
      return target !== undefined && mentionsStore(target) ? { deny: STORE_RULE_REASON } : next(e)
    } catch {
      return { deny: `${STORE_RULE_REASON} (the ProjectMan guard failed to read this call)` }
    }
  })

  // US-PM-60-6: /pm-board, /pm-status-view and /pm-next-task answer from the
  // projectman MCP server through `$.mcp.call`, with no model request, so a
  // check costs no tokens. `immediate` lets them run while a turn streams.
  on('session.start', async ($, e, next) => {
    for (const command of PM_COMMANDS) {
      await $.command.register({ name: command.name, description: command.description, immediate: true })
    }
    return next(e)
  })

  // The names spelled out so `claude plugin validate` reads the matcher; a
  // mod test holds them equal to PM_COMMANDS.
  on('command.run', { command: ['pm-board', 'pm-status-view', 'pm-next-task'] }, async ($, e, next) => {
    const command = PM_COMMANDS.find((c) => c.name === e.command)
    if (command === undefined) return next(e)
    const fetched = await fetchCommand($, command)
    if ('error' in fetched) return { text: fetched.error }
    // US-PM-60-8: a pane where a surface draws; a compact summary where none does.
    if ((await viewMode($)) === 'pane') return drawView($, command, fetched.results)
    return { text: summarizeCommand(command, fetched.results) }
  }).catch(($, e) => ({ text: `ProjectMan: /${e.command} failed to read the MCP server's answer` }))

  // US-PM-60-7: the board pane, drawn from `projectman.board` on any surface.
  // The read subscribes the pane, so the refresh button's write redraws it.
  // The id spelled out (BOARD_PANE) so `claude plugin validate` reads the matcher.
  on('ui.render', { component: 'Pane', requestId: 'pm-board' }, async ($, e) => {
    const view = await read($, board)
    return boardPane($.ui.resolve(e), view, e.props.bodyColumns, () => void refreshBoard($))
  })
}
