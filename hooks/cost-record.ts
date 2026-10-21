// Per-request token usage of an orchestrator run, per task (US-PM-61-6).
//
// register.ts hooks `turn.step` to read each model request's usage as the API
// reported it, and the projectman `tool.call`s to learn which run is active
// and which task each loop is working on. These are the pure parts: what a pm
// call says about the run, how a request is added to the run's summary, and
// how summaries are kept in `$.store`. The live value is `projectman.cost`.
//
// Attribution:
// - A run is active from the first pm call that carries a `run_id`; a call
//   naming another run id starts that run (a fresh summary, or the one kept
//   in `$.store` for it, so a restarted session goes on adding to it).
// - Each loop (the main session, or a subagent by its `agentId`) works on the
//   task its last run-carrying pm call named (`pm_grab`, `pm_accept`, ...).
// - A subagent that has named no task yet (a worker's requests before its
//   own `pm_grab`) is charged to the task the main loop last named: the
//   orchestrator dispatches a worker right after claiming its task.
// - A request no task can be found for is counted in `unattributed`.
// - Requests made while no run is active are not recorded.
//
// Gaps and heartbeats (US-PM-61-7):
// - Each request carries the gap since the previous request in its loop (each
//   loop has its own cached prefix) and whether that gap outlived the cache
//   TTL, so the prefix had expired.
// - A main-loop turn whose prompt opens `Heartbeat orch-` is the
//   /pm-orchestrate keep-alive firing (the marker orch_cost reads too); its
//   requests go to the run's `heartbeat` bucket, never to a task.
// - A request whose wait since its loop's last non-heartbeat request outlived
//   the TTL, while a heartbeat in between kept its own gap under it, is a
//   bridged wait: its cache-read tokens are the writes the heartbeat avoided.

import type {
  ProjectmanCostRequest,
  ProjectmanCostRun,
  ProjectmanCostState,
  ProjectmanHeartbeatCounts,
  ProjectmanTokenCounts,
} from '../types'
import { pmToolName } from './band-refresh.ts'

/**
 * The prompt-cache TTL the orchestrator runs on: one hour (promptCacheTtl=1h,
 * US-PM-54). A request after a longer gap in its loop found its prefix gone.
 */
export const CACHE_TTL_MS = 60 * 60 * 1000

/** How the heartbeat prompt opens: `Heartbeat <run-id>: ...`, every run id `orch-`. */
export const HEARTBEAT_MARKER = 'Heartbeat orch-'

/** The `pastTtl` bucket of heartbeat requests and of requests no task was found for. */
export const HEARTBEAT_BUCKET = 'heartbeat'
export const UNATTRIBUTED_BUCKET = 'unattributed'

/** The `$.store` key holding the kept run summaries, by run id. */
export const COST_RUNS_KEY = 'costRuns'

/** How many run summaries `$.store` keeps; the least recently updated go first. */
export const KEPT_RUNS = 20

/** How many of the active run's requests `projectman.cost` lists, newest last. */
export const KEPT_REQUESTS = 200

/** The loop key of the main session; a subagent's is its `agentId`. */
export const MAIN_LOOP = 'main'

/** The pm tools whose `task_id` (or `id`) names the task the calling loop works on. */
const ATTRIBUTING = new Set([
  'pm_grab',
  'pm_accept',
  'pm_done_next',
  'pm_retry',
  'pm_park',
  'pm_review',
  'pm_release',
  'pm_update',
])

/** A task id (`US-PM-61-6`); stories, epics and sprints never name a task. */
const TASK_ID = /^US-[A-Za-z0-9]+-\d+-\d+$/

/** The four token counts of one request, as the API reported them. */
export type RequestUsage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
}

/** What a pm call says about the run: its id, and the task it names (null for none). */
export type PmRunCall = { runId: string; taskId: string | null }

/**
 * The run id a projectman tool call carries, and the task it attributes the
 * calling loop to; undefined for any other tool or a call with no run id.
 */
export function pmRunCall(call: { tool: string } & Record<string, unknown>): PmRunCall | undefined {
  const name = pmToolName(call.tool)
  if (name === undefined) return undefined
  const runId = call.run_id
  if (typeof runId !== 'string' || runId.trim() === '') return undefined
  if (!ATTRIBUTING.has(name)) return { runId, taskId: null }
  const id = typeof call.task_id === 'string' ? call.task_id : call.id
  return { runId, taskId: typeof id === 'string' && TASK_ID.test(id) ? id : null }
}

/** Counts with nothing in them. */
export function emptyCounts(): ProjectmanTokenCounts {
  return { requests: 0, input: 0, cacheRead: 0, cacheWrite: 0, output: 0 }
}

/** A count the response left out, or one that is not a number, reads as zero. */
const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0)

/** `counts` with one more request of `usage` added. */
export function addUsage(counts: ProjectmanTokenCounts, usage: RequestUsage): ProjectmanTokenCounts {
  return {
    requests: counts.requests + 1,
    input: counts.input + n(usage.input_tokens),
    cacheRead: counts.cacheRead + n(usage.cache_read_input_tokens),
    cacheWrite: counts.cacheWrite + n(usage.cache_creation_input_tokens),
    output: counts.output + n(usage.output_tokens),
  }
}

/** A fresh summary for a run starting now. */
export function newRun(runId: string, at: number): ProjectmanCostRun {
  return { runId, startedAt: at, updatedAt: at, tasks: {}, unattributed: emptyCounts(), totals: emptyCounts() }
}

/** The kept summaries as `$.store` holds them; anything else reads as none. */
export function keptRuns(stored: unknown): Record<string, ProjectmanCostRun> {
  if (stored === null || typeof stored !== 'object' || Array.isArray(stored)) return {}
  const runs: Record<string, ProjectmanCostRun> = {}
  for (const [id, run] of Object.entries(stored as Record<string, unknown>)) {
    if (run !== null && typeof run === 'object' && (run as ProjectmanCostRun).runId === id) {
      runs[id] = run as ProjectmanCostRun
    }
  }
  return runs
}

/** The most recently updated kept summary; null when none is kept. */
export function latestRun(stored: unknown): ProjectmanCostRun | null {
  let latest: ProjectmanCostRun | null = null
  for (const run of Object.values(keptRuns(stored))) {
    if (latest === null || run.updatedAt > latest.updatedAt) latest = run
  }
  return latest
}

/** The kept summaries with `run` written in, at most `keep`, the least recently updated dropped. */
export function rememberRun(
  stored: unknown,
  run: ProjectmanCostRun,
  keep: number = KEPT_RUNS,
): Record<string, ProjectmanCostRun> {
  const runs = Object.values({ ...keptRuns(stored), [run.runId]: run })
  runs.sort((a, b) => b.updatedAt - a.updatedAt)
  const kept: Record<string, ProjectmanCostRun> = {}
  for (const r of runs.slice(0, Math.max(1, keep))) kept[r.runId] = r
  return kept
}

/**
 * The state after a run-carrying pm call made in `loop`: the run started
 * when it is a new one (from `seed`, its kept summary, when there is one),
 * and the loop's task set when the call names one.
 */
export function attribute(
  state: ProjectmanCostState | null,
  call: PmRunCall,
  loop: string,
  at: number,
  seed?: ProjectmanCostRun,
): ProjectmanCostState {
  const isSameRun = state?.run?.runId === call.runId
  const run = isSameRun && state?.run ? state.run : (seed ?? newRun(call.runId, at))
  const loops = isSameRun && state ? { ...state.loops } : {}
  const requests = isSameRun && state ? state.requests : []
  if (call.taskId !== null) loops[loop] = call.taskId
  return { ...timeline(state), run, requests, loops }
}

/** The gap-timing and heartbeat fields of `state`, those it has. */
function timeline(state: ProjectmanCostState | null): Partial<ProjectmanCostState> {
  const kept: Partial<ProjectmanCostState> = {}
  if (state?.lastAt !== undefined) kept.lastAt = state.lastAt
  if (state?.lastWorkAt !== undefined) kept.lastWorkAt = state.lastWorkAt
  if (state?.heartbeatTurn !== undefined) kept.heartbeatTurn = state.heartbeatTurn
  return kept
}

/** The task a request made in `loop` is charged to; null when none can be found. */
export function taskOf(state: ProjectmanCostState, loop: string): string | null {
  return state.loops[loop] ?? state.loops[MAIN_LOOP] ?? null
}

/** True for the /pm-orchestrate heartbeat's prompt. */
export function isHeartbeatPrompt(text: unknown): boolean {
  return typeof text === 'string' && text.trimStart().startsWith(HEARTBEAT_MARKER)
}

/**
 * The state as a turn starts in `loop`: a main-loop turn opened by the
 * heartbeat prompt becomes the heartbeat turn, any other main-loop turn ends
 * it. The same object when nothing changes (no run, a subagent's turn, or
 * the mark already as it should be), so a caller can skip the write.
 */
export function markTurn(
  state: ProjectmanCostState | null,
  loop: string,
  turnId: string,
  text: unknown,
): ProjectmanCostState | null {
  if (state === null || state.run === null || loop !== MAIN_LOOP) return state
  const heartbeatTurn = isHeartbeatPrompt(text) ? turnId : null
  if ((state.heartbeatTurn ?? null) === heartbeatTurn) return state
  return { ...state, heartbeatTurn }
}

/** Heartbeat counts with nothing in them. */
export function emptyHeartbeat(): ProjectmanHeartbeatCounts {
  return { ...emptyCounts(), bridged: 0, avoidedWrites: 0 }
}

/** What `recordRequest` needs to know beyond the usage. */
export type RecordOptions = {
  /** The turn the request was made in; a match with `heartbeatTurn` makes it a heartbeat. */
  turnId?: string
  /** The cache TTL gaps are held to; CACHE_TTL_MS by default. */
  ttlMs?: number
}

/**
 * The state with one request made in `loop` recorded: listed (the newest
 * KEPT_REQUESTS kept) and added to its task's counts (or the heartbeat
 * bucket) and the run's totals, with the gap since its loop's previous
 * request. Unchanged when no run is active.
 */
export function recordRequest(
  state: ProjectmanCostState | null,
  loop: string,
  usage: RequestUsage & { model?: string },
  at: number,
  options: RecordOptions = {},
): ProjectmanCostState | null {
  if (state === null || state.run === null) return state
  const ttlMs = options.ttlMs ?? CACHE_TTL_MS
  const isHeartbeat =
    loop === MAIN_LOOP && options.turnId !== undefined && options.turnId === (state.heartbeatTurn ?? null)
  const taskId = isHeartbeat ? null : taskOf(state, loop)
  const run = state.run

  const previousAt = state.lastAt?.[loop]
  const previousWorkAt = state.lastWorkAt?.[loop]
  const gapMs = previousAt === undefined ? null : Math.max(0, at - previousAt)
  const isPastTtl = gapMs !== null && gapMs > ttlMs
  const cacheRead = n(usage.cache_read_input_tokens)
  // The wait since the loop's last real request outlived the TTL, a
  // heartbeat came between, and the cache still served the prefix.
  const isBridged =
    !isHeartbeat &&
    !isPastTtl &&
    previousAt !== undefined &&
    previousWorkAt !== undefined &&
    previousAt > previousWorkAt &&
    at - previousWorkAt > ttlMs &&
    cacheRead > 0

  const tasks = { ...run.tasks }
  if (!isHeartbeat && taskId !== null) tasks[taskId] = addUsage(tasks[taskId] ?? emptyCounts(), usage)

  const next: ProjectmanCostRun = {
    ...run,
    updatedAt: at,
    tasks,
    unattributed: !isHeartbeat && taskId === null ? addUsage(run.unattributed, usage) : run.unattributed,
    totals: addUsage(run.totals, usage),
  }
  if (isHeartbeat || isBridged) {
    const was = run.heartbeat ?? emptyHeartbeat()
    next.heartbeat = {
      ...(isHeartbeat ? addUsage(was, usage) : pickCounts(was)),
      bridged: was.bridged + (isBridged ? 1 : 0),
      avoidedWrites: was.avoidedWrites + (isBridged ? cacheRead : 0),
    }
  }
  if (isPastTtl) {
    const bucket = isHeartbeat ? HEARTBEAT_BUCKET : (taskId ?? UNATTRIBUTED_BUCKET)
    next.pastTtl = { ...run.pastTtl, [bucket]: (run.pastTtl?.[bucket] ?? 0) + 1 }
  }

  const request: ProjectmanCostRequest = {
    at,
    taskId,
    agentId: loop === MAIN_LOOP ? null : loop,
    model: typeof usage.model === 'string' ? usage.model : '',
    input: n(usage.input_tokens),
    cacheRead,
    cacheWrite: n(usage.cache_creation_input_tokens),
    output: n(usage.output_tokens),
    gapMs,
    isPastTtl,
    isHeartbeat,
  }
  return {
    ...timeline(state),
    loops: state.loops,
    requests: [...state.requests, request].slice(-KEPT_REQUESTS),
    run: next,
    lastAt: { ...state.lastAt, [loop]: at },
    lastWorkAt: isHeartbeat ? (state.lastWorkAt ?? {}) : { ...state.lastWorkAt, [loop]: at },
  }
}

/** The five token counts of `counts`, nothing else. */
function pickCounts(counts: ProjectmanTokenCounts): ProjectmanTokenCounts {
  const { requests, input, cacheRead, cacheWrite, output } = counts
  return { requests, input, cacheRead, cacheWrite, output }
}
