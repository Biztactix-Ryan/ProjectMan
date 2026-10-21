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

import type {
  ProjectmanCostRequest,
  ProjectmanCostRun,
  ProjectmanCostState,
  ProjectmanTokenCounts,
} from '../types'
import { pmToolName } from './band-refresh.ts'

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
  return { run, requests, loops }
}

/** The task a request made in `loop` is charged to; null when none can be found. */
export function taskOf(state: ProjectmanCostState, loop: string): string | null {
  return state.loops[loop] ?? state.loops[MAIN_LOOP] ?? null
}

/**
 * The state with one request made in `loop` recorded: listed (the newest
 * KEPT_REQUESTS kept) and added to its task's counts and the run's totals.
 * Unchanged when no run is active.
 */
export function recordRequest(
  state: ProjectmanCostState | null,
  loop: string,
  usage: RequestUsage & { model?: string },
  at: number,
): ProjectmanCostState | null {
  if (state === null || state.run === null) return state
  const taskId = taskOf(state, loop)
  const run = state.run
  const tasks = { ...run.tasks }
  if (taskId !== null) tasks[taskId] = addUsage(tasks[taskId] ?? emptyCounts(), usage)
  const request: ProjectmanCostRequest = {
    at,
    taskId,
    agentId: loop === MAIN_LOOP ? null : loop,
    model: typeof usage.model === 'string' ? usage.model : '',
    input: n(usage.input_tokens),
    cacheRead: n(usage.cache_read_input_tokens),
    cacheWrite: n(usage.cache_creation_input_tokens),
    output: n(usage.output_tokens),
  }
  return {
    loops: state.loops,
    requests: [...state.requests, request].slice(-KEPT_REQUESTS),
    run: {
      ...run,
      updatedAt: at,
      tasks,
      unattributed: taskId === null ? addUsage(run.unattributed, usage) : run.unattributed,
      totals: addUsage(run.totals, usage),
    },
  }
}
