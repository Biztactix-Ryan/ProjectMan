import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ToolCallInput } from 'claude-code'
import type {
  ProjectmanBand,
  ProjectmanBandState,
  ProjectmanBoardView,
  ProjectmanCostRun,
  ProjectmanCostState,
  ProjectmanGuardDenial,
} from '../types'
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
import { BAND_ACTIVE, BAND_NOTE, BAND_SPRINTS, bandFrom, bandSprintCall, activeSprintId, sprintBand } from './sprint-band.tsx'
import type { BandCall } from './sprint-band.tsx'
import { movesBand, PM_TOOL } from './band-refresh.ts'
import { bandSessionValue } from './band-session.ts'
import { attribute, COST_RUNS_KEY, keptRuns, MAIN_LOOP, pmRunCall, recordRequest, rememberRun } from './cost-record.ts'

/** What the board pane draws (US-PM-60-7): null until the board is first read. */
const board = atom({ plugin: 'projectman', key: 'board' } as const, null as ProjectmanBoardView | null)

/**
 * What the sprint band draws (US-PM-62-6): null until the band is first
 * drawn, which is also how the turn.complete hook knows a surface shows it.
 */
const band = atom({ plugin: 'projectman', key: 'band' } as const, null as ProjectmanBandState | null)

/**
 * The active orchestrator run's token usage (US-PM-61-6): null until a pm
 * call carries a run id. Its `run` is also kept in `$.store` (persistCost).
 */
const cost = atom({ plugin: 'projectman', key: 'cost' } as const, null as ProjectmanCostState | null)

/**
 * The run summary's writes to `$.store`, coalesced: each write takes the
 * summary as it stands then, and a request recorded while one runs makes
 * one more after it, so the store never settles on an older summary. The
 * module's own, like bandQueue.
 */
const costQueue = {
  isStale: false,
  isDraining: false,
  /** Runs no longer active whose last summary is not yet written, by run id. */
  retired: {} as Record<string, ProjectmanCostRun>,
}

/**
 * Writes the retired runs' and the active run's summaries into the kept runs
 * until none is outstanding: the one writer, so no write loses another's
 * run. Never throws.
 */
async function drainCost($: EngineInterface): Promise<void> {
  try {
    while (costQueue.isStale) {
      costQueue.isStale = false
      const retired = Object.values(costQueue.retired)
      costQueue.retired = {}
      const active = (await read($, cost))?.run
      const runs = active ? [...retired, active] : retired
      if (runs.length === 0) continue
      let kept: unknown = await $.store.get(COST_RUNS_KEY)
      for (const run of runs) kept = rememberRun(kept, run)
      await $.store.set(COST_RUNS_KEY, kept)
    }
  } catch {
    // Persisting is a convenience; the live value stands without it.
  } finally {
    costQueue.isDraining = false
  }
}

/** A run's kept summary from `$.store`; undefined when there is none or the store cannot be read. */
async function keptRun($: EngineInterface, runId: string): Promise<ProjectmanCostRun | undefined> {
  try {
    return keptRuns(await $.store.get(COST_RUNS_KEY))[runId]
  } catch {
    return undefined
  }
}

/** Asks for the run summary to be persisted, on the timer so no request waits on the store. */
function persistCost($: EngineInterface): void {
  costQueue.isStale = true
  if (costQueue.isDraining) return
  costQueue.isDraining = true
  try {
    $.clock.after(0, () => void drainCost($))
  } catch {
    costQueue.isDraining = false
  }
}

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

/**
 * The band read from the MCP server: the active sprint, the first task in
 * progress and the note, together, then the sprint's live progress when one
 * is active. Null (nothing drawn) when the server is not connected or any
 * call errors, as every call does where the directory has no store.
 */
async function readBand($: EngineInterface): Promise<ProjectmanBand | null> {
  const connected = await $.mcp.connect(MCP_SERVER_KEY)
  if (!connected.isConnected) return null
  const server = connected.server
  const call = async ({ tool, args }: BandCall): Promise<Yaml> => {
    const answer = await $.mcp.call(server, tool, args)
    if (answer.isError) throw new Error(`${tool} failed`)
    return parseYaml(resultText(answer))
  }
  const [sprints, active, note] = await Promise.all([call(BAND_SPRINTS), call(BAND_ACTIVE), call(BAND_NOTE)])
  const id = activeSprintId(sprints)
  const sprint = id === null ? null : await call(bandSprintCall(id))
  return bandFrom(sprint, active, note)
}

/**
 * Re-reads the band and writes `projectman.band`, which redraws it. A read
 * while one is in flight does nothing; a failed read hides the band.
 */
async function refreshBand($: EngineInterface): Promise<void> {
  if ((await read($, band))?.isReading) return
  await update($, band, (v) => ({ view: v?.view ?? null, isReading: true, reads: v?.reads ?? 0 }))
  let view: ProjectmanBand | null = null
  try {
    view = await readBand($)
  } catch {
    view = null
  }
  const done = view
  await update($, band, (v) => ({ view: done, isReading: false, reads: (v?.reads ?? 0) + 1 }))
}

/**
 * The band's re-reads, coalesced (US-PM-62-7): a burst of requests (a turn of
 * pm writes, several draws before the first read lands) makes one read, and a
 * request that arrives while a read runs makes one more after it, so the band
 * never settles on state older than the last write. The module's own: a
 * reload starts it over, as no read of the old module's is still its own.
 */
const bandQueue = {
  /** A request no read has started on since. */
  isStale: false,
  /** The first draw's request: read though no band is drawn yet. */
  isForced: false,
  /** A read is scheduled or running. */
  isDraining: false,
}

/** Runs the asked-for reads, one at a time, until none is outstanding; never throws. */
async function drainBand($: EngineInterface): Promise<void> {
  try {
    while (bandQueue.isStale) {
      bandQueue.isStale = false
      const isForced = bandQueue.isForced
      bandQueue.isForced = false
      // No surface has drawn the band: nothing to keep fresh, no MCP call.
      if (!isForced && (await read($, band)) === null) continue
      await refreshBand($)
    }
  } catch {
    // The band is a convenience; a failed read leaves it as it was.
  } finally {
    bandQueue.isDraining = false
  }
}

/**
 * Asks for a band re-read, run on the timer so the caller never waits on the
 * MCP server; `force` reads though no band is drawn yet (the first draw).
 */
function rereadBand($: EngineInterface, force = false): void {
  bandQueue.isStale = true
  if (force) bandQueue.isForced = true
  if (bandQueue.isDraining) return
  bandQueue.isDraining = true
  try {
    $.clock.after(0, () => void drainBand($))
  } catch {
    bandQueue.isDraining = false
  }
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

  // US-PM-62-8: tell the SessionStart command hook (`projectman
  // session-context`, beneath this one in the classic chain) whether the
  // sprint band draws in this session: PROJECTMAN_BAND_SESSION is set to the
  // session's id where a listed surface raises AbovePrompt (terminal or
  // desktop, BAND_SURFACES), unset everywhere else (none, vscode, mobile), before
  // `next(e)` starts the command. See band-session.ts for why it is safe.
  on('classic.SessionStart', async ($, e, next) => {
    let surfaces: readonly string[] | null = null
    try {
      surfaces = await $.session.surfaces()
    } catch {
      surfaces = null
    }
    try {
      await $.env.set('PROJECTMAN_BAND_SESSION', bandSessionValue(e.session_id, surfaces))
    } catch {
      // No signal set: the command prints the full block, as without the band.
    }
    return next(e)
  }).catch(async ($, e, next) => {
    if (next.called) return next(e)
    try {
      await $.env.set('PROJECTMAN_BAND_SESSION', undefined)
    } catch {
      // Unset or not, a stale value names another session's id.
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

  // US-PM-62-6: the sprint band above the prompt, drawn from `projectman.band`.
  // Its first draw schedules the first read (the timer runs it once this
  // draw resolves, so the draw never waits on the MCP server); until then,
  // and whenever there is nothing to show, it passes and the engine's own
  // band shows. It yields to a survey.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const state = await read($, band)
    if (state === null) rereadBand($, true)
    if (e.props.hasSurvey || !state?.view) return next(e)
    return sprintBand($.ui.resolve(e), state.view, e.props.bodyColumns)
  })

  // After each turn, re-read the band where a surface has drawn it: a turn
  // is what moves a task or writes the note. No band drawn, no MCP call.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    try {
      rereadBand($)
    } catch {
      // The band is a convenience; the turn's answer stands without it.
    }
    return result
  })

  // US-PM-62-7: re-read the band after a pm tool call that writes (status,
  // a new task, the note) answers without error, so it moves with the work
  // rather than at the turn's end. The result is returned as `next` gave it,
  // never waiting on the read, which runs on the timer once the call has
  // answered; a refused or errored call reads nothing. Either server prefix.
  on('tool.call', { tool: PM_TOOL }, async ($, e, next) => {
    const result = await next(e)
    try {
      if (result.deny === undefined && result.isError !== true && movesBand(e as unknown as { tool: string } & Record<string, unknown>)) {
        rereadBand($)
      }
    } catch {
      // The band is a convenience; the tool's result stands without it.
    }
    return result
  }).catch(($, e, next) => next(e))

  // US-PM-61-6: a pm call carrying a run id makes that run the active one
  // and, when it names a task, sets the task its loop (the main session or
  // the subagent by `agentId`) works on. A run new to this session goes on
  // from its summary in `$.store`, so a restart keeps adding to it. A
  // refused call attributes nothing.
  on('tool.call', { tool: PM_TOOL }, async ($, e, next) => {
    const result = await next(e)
    try {
      const call = pmRunCall(e as unknown as { tool: string } & Record<string, unknown>)
      if (call !== undefined && result.deny === undefined) {
        const loop = e.agentId ?? MAIN_LOOP
        const at = await $.clock.now()
        const current = await read($, cost)
        const seed = current?.run?.runId === call.runId ? undefined : await keptRun($, call.runId)
        await update($, cost, (v) => {
          // A run this call ends: its last summary is written with the next drain.
          if (v?.run && v.run.runId !== call.runId) costQueue.retired[v.run.runId] = v.run
          return attribute(v, call, loop, at, seed)
        })
        persistCost($)
      }
    } catch {
      // Recording is a convenience; the tool's result stands without it.
    }
    return result
  }).catch(($, e, next) => next(e))

  // US-PM-61-6: each model request's input, cache-read and cache-write
  // tokens, once its response is whole, charged to the task of the loop it
  // was made in. Nothing is recorded while no run is active. The response
  // streams through untouched.
  on('turn.step', async function* ($, e, next) {
    const response = yield* next(e)
    try {
      const usage = response.usage
      if (usage !== null && (await read($, cost))?.run) {
        const at = await $.clock.now()
        const loop = e.agentId ?? MAIN_LOOP
        await update($, cost, (v) => recordRequest(v, loop, usage, at))
        persistCost($)
      }
    } catch {
      // Recording is a convenience; the response stands without it.
    }
    return response
  })
}
