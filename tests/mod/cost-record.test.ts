import type { On } from 'claude-code'
import type { ProjectmanCostRun, ProjectmanCostState } from '../../types'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import {
  addUsage,
  attribute,
  COST_RUNS_KEY,
  emptyCounts,
  KEPT_REQUESTS,
  KEPT_RUNS,
  MAIN_LOOP,
  newRun,
  pmRunCall,
  recordRequest,
  rememberRun,
} from '../../hooks/cost-record.ts'

// US-PM-61-6: each model request's input, cache-read and cache-write tokens
// are recorded per task while an orchestrator run is active, and the run's
// summary is persisted in `$.store`. The test's hooks beneath the plugin
// stand for the engine: the projectman MCP tools answer plainly, and each
// `turn.step` answers with the usage the test queued for it. The clock and
// the store are mocked; the store write runs on the timer, so a test settles
// the clock before reading it.

const RUN = 'orch-2026-10-21-3a6e'
const OTHER_RUN = 'orch-2026-10-22-beef'
const GRAB = 'mcp__plugin_projectman_projectman__pm_grab'
const ACCEPT = 'mcp__plugin_projectman_projectman__pm_accept'
const WORKER = 'agent-worker-1'

type Usage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number }

const usage = (input: number, cacheRead: number, cacheWrite: number, output = 10): Usage => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: cacheRead,
  cache_creation_input_tokens: cacheWrite,
})

type World = {
  /** The usage the next steps answer with, in order; null for a response with none. */
  usages: (Usage | null)[]
  /** Each value the plugin wrote to projectman.cost, in order. */
  cost: (ProjectmanCostState | null)[]
  /** The projectman tools called beneath the plugin. */
  tools: string[]
  /** What the pm tools answer; a plain result by default. */
  answer: Record<string, unknown>
  /** The plugin's `$.store`, in memory. */
  store: Record<string, unknown>
  /** Every store call fails, as a full disk would. */
  storeFails: boolean
}

// The plugin's `$.store` is answered from `w.store`, so a test reads back what
// was persisted and seeds what a previous session left.
function world(on: On, store: Record<string, unknown> = {}): World {
  const w: World = { usages: [], cost: [], tools: [], answer: { result: 'ok', text: 'ok' }, store: { ...store }, storeFails: false }
  on('store.get', ($, e) => {
    if (w.storeFails) throw new Error('disk full')
    return { value: structuredClone(w.store[e.key]) }
  })
  on('store.set', ($, e) => {
    if (w.storeFails) throw new Error('disk full')
    w.store[e.key] = structuredClone(e.value)
    return { value: undefined }
  })
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'cost') w.cost.push(e.value as ProjectmanCostState | null)
    return next(e)
  })
  on('tool.call', { tool: /^mcp__/ }, ($, e) => {
    w.tools.push(e.tool)
    return w.answer as never
  })
  on('turn.step', async function* ($, e) {
    const u = w.usages.shift() ?? null
    yield { kind: 'text', index: 0, text: 'ok' }
    yield { kind: 'stop', stopReason: 'end_turn', usage: u === null ? null : { ...u, model: 'claude-opus' } }
    return {
      turnId: e.turnId,
      index: e.index,
      answer: 'ok',
      toolUses: [],
      stopReason: 'end_turn',
      usage: u === null ? null : { ...u, model: 'claude-opus' },
    }
  })
  return w
}

let stepIndex = 0

/** One model request, in the main loop or a subagent's, read to its end; its chunks and result. */
async function request($: Engine, w: World, u: Usage | null, agentId?: string) {
  w.usages.push(u)
  const stream = $.turn.step({ turnId: 't1', index: stepIndex++, model: 'claude-opus', messageCount: 3, ...(agentId ? { agentId } : {}) })
  const chunks: unknown[] = []
  let piece = await stream.next()
  while (!piece.done) {
    chunks.push(piece.value)
    piece = await stream.next()
  }
  return { chunks, result: piece.value }
}

const pmCall = ($: Engine, tool: string, args: Record<string, unknown>, agentId?: string) =>
  $.tool.call({ tool, ...args, ...(agentId ? { agentId } : {}) } as never)

const live = (w: World) => w.cost[w.cost.length - 1] ?? null

async function stored(w: World, clock: MockClock): Promise<Record<string, ProjectmanCostRun>> {
  await clock.settle()
  return (w.store[COST_RUNS_KEY] ?? {}) as Record<string, ProjectmanCostRun>
}

// ------------------------------------------------- the pure parts

test('pmRunCall reads the run id and the task a pm call names, under either prefix', () => {
  expect(pmRunCall({ tool: GRAB, task_id: 'US-PM-61-6', run_id: RUN })).toEqual({ runId: RUN, taskId: 'US-PM-61-6' })
  expect(pmRunCall({ tool: 'mcp__projectman__pm_accept', id: 'US-PM-61-6', run_id: RUN })).toEqual({ runId: RUN, taskId: 'US-PM-61-6' })
  // A run-carrying call that names no task (or a story, or a sprint) still marks the run.
  expect(pmRunCall({ tool: 'mcp__projectman__pm_update_sprint', sprint_id: 'SPRINT-PM-21', run_id: RUN })).toEqual({ runId: RUN, taskId: null })
  expect(pmRunCall({ tool: GRAB, id: 'US-PM-61', run_id: RUN })).toEqual({ runId: RUN, taskId: null })
  // No run id, or another tool: nothing.
  expect(pmRunCall({ tool: GRAB, task_id: 'US-PM-61-6' })).toBeUndefined()
  expect(pmRunCall({ tool: GRAB, task_id: 'US-PM-61-6', run_id: '  ' })).toBeUndefined()
  expect(pmRunCall({ tool: 'mcp__other__pm_grab', task_id: 'US-PM-61-6', run_id: RUN })).toBeUndefined()
  expect(pmRunCall({ tool: 'Bash', run_id: RUN })).toBeUndefined()
})

test('addUsage sums the four counts, a missing count reading as zero', () => {
  const once = addUsage(emptyCounts(), usage(5, 100, 20, 7))
  expect(once).toEqual({ requests: 1, input: 5, cacheRead: 100, cacheWrite: 20, output: 7 })
  expect(addUsage(once, { input_tokens: 1 } as never)).toEqual({ requests: 2, input: 6, cacheRead: 100, cacheWrite: 20, output: 7 })
})

test('recordRequest does nothing while no run is active', () => {
  expect(recordRequest(null, MAIN_LOOP, usage(1, 2, 3), 0)).toBeNull()
  const idle: ProjectmanCostState = { run: null, requests: [], loops: {} }
  expect(recordRequest(idle, MAIN_LOOP, usage(1, 2, 3), 0)).toBe(idle)
})

test('recordRequest keeps only the newest requests listed, the counts whole', () => {
  let state: ProjectmanCostState | null = attribute(null, { runId: RUN, taskId: 'US-PM-61-6' }, MAIN_LOOP, 0)
  for (let i = 0; i < KEPT_REQUESTS + 5; i++) state = recordRequest(state, MAIN_LOOP, usage(1, 2, 3), i)
  expect(state?.requests.length).toBe(KEPT_REQUESTS)
  expect(state?.requests[0]?.at).toBe(5)
  expect(state?.run?.tasks['US-PM-61-6']?.requests).toBe(KEPT_REQUESTS + 5)
  expect(state?.run?.totals.cacheWrite).toBe(3 * (KEPT_REQUESTS + 5))
})

test('rememberRun keeps the most recently updated runs and drops what is not a run', () => {
  const runs: Record<string, ProjectmanCostRun> = {}
  for (let i = 0; i < 4; i++) runs[`r${i}`] = { ...newRun(`r${i}`, i), updatedAt: i }
  const kept = rememberRun({ ...runs, junk: 3 }, { ...newRun('r9', 9), updatedAt: 9 }, 3)
  expect(Object.keys(kept).sort()).toEqual(['r2', 'r3', 'r9'])
  expect(rememberRun('not a map', newRun('r1', 1))).toEqual({ r1: newRun('r1', 1) })
})

// ------------------------------------------------- US-PM-61-1 criterion
//
// "Each request's input, cache-read and cache-write tokens are recorded per
// task while an orchestrator run is active."

test('US-PM-61-1 criterion: requests are recorded per task once a run is active, and not before', async ($, on) => {
  mock.clock(on, { now: 1000 })
  const w = world(on)

  // No run yet: the request is not recorded.
  await request($, w, usage(50, 0, 4000))
  expect(w.cost).toEqual([])

  // The orchestrator claims a task: its main-loop requests are charged to it.
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(3, 20000, 500))
  await request($, w, usage(2, 20500, 100))

  const state = live(w)
  expect(state?.run?.runId).toBe(RUN)
  expect(state?.run?.tasks).toEqual({
    'US-PM-61-6': { requests: 2, input: 5, cacheRead: 40500, cacheWrite: 600, output: 20 },
  })
  expect(state?.run?.totals).toEqual({ requests: 2, input: 5, cacheRead: 40500, cacheWrite: 600, output: 20 })
  expect(state?.requests.map((r) => [r.taskId, r.agentId, r.input, r.cacheRead, r.cacheWrite])).toEqual([
    ['US-PM-61-6', null, 3, 20000, 500],
    ['US-PM-61-6', null, 2, 20500, 100],
  ])
  expect(state?.requests.every((r) => r.model === 'claude-opus' && r.at === 1000)).toBe(true)
})

test("US-PM-61-1 criterion: a worker's requests go to its own task, from its pm_grab on", async ($, on) => {
  mock.clock(on)
  const w = world(on)

  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  // The worker's first request, before its own pm_grab: the orchestrator's task.
  await request($, w, usage(10, 0, 9000), WORKER)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN }, WORKER)
  await request($, w, usage(1, 9000, 300), WORKER)

  // The orchestrator moves on to the next task while the worker runs.
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: RUN })
  await request($, w, usage(2, 30000, 200))
  await request($, w, usage(1, 9300, 50), WORKER)

  // A second worker grabs another task: charged there, never to the first's.
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: RUN }, 'agent-worker-2')
  await request($, w, usage(4, 0, 7000), 'agent-worker-2')

  // pm_accept names the task the orchestrator is now on.
  await pmCall($, ACCEPT, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 31000, 10))

  const run = live(w)?.run
  expect(run?.tasks['US-PM-61-6']).toEqual({ requests: 4, input: 13, cacheRead: 49300, cacheWrite: 9360, output: 40 })
  expect(run?.tasks['US-PM-61-7']).toEqual({ requests: 2, input: 6, cacheRead: 30000, cacheWrite: 7200, output: 20 })
  expect(run?.unattributed).toEqual(emptyCounts())
  expect(run?.totals.requests).toBe(6)
  expect(live(w)?.loops).toEqual({ main: 'US-PM-61-6', [WORKER]: 'US-PM-61-6', 'agent-worker-2': 'US-PM-61-7' })
})

test('a run-carrying call that names no task leaves requests unattributed', async ($, on) => {
  mock.clock(on)
  const w = world(on)
  await pmCall($, 'mcp__projectman__pm_update_sprint', { sprint_id: 'SPRINT-PM-21', status: 'active', run_id: RUN })
  await request($, w, usage(7, 100, 30))
  expect(live(w)?.run?.tasks).toEqual({})
  expect(live(w)?.run?.unattributed).toEqual({ requests: 1, input: 7, cacheRead: 100, cacheWrite: 30, output: 10 })
})

test('a refused pm call and a call with no run id attribute nothing', async ($, on) => {
  mock.clock(on)
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6' })
  w.answer = { deny: 'not allowed' }
  expect((await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })).deny).toBe('not allowed')
  await request($, w, usage(1, 2, 3))
  expect(w.cost).toEqual([])
})

test('a response with no usage records nothing', async ($, on) => {
  mock.clock(on)
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  const before = w.cost.length
  await request($, w, null)
  expect(w.cost.length).toBe(before)
  expect(live(w)?.run?.totals).toEqual(emptyCounts())
})

test("a step's chunks and result pass through unchanged", async ($, on) => {
  mock.clock(on)
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  const { chunks, result } = await request($, w, usage(1, 2, 3))
  expect(chunks).toEqual([
    { kind: 'text', index: 0, text: 'ok' },
    { kind: 'stop', stopReason: 'end_turn', usage: { ...usage(1, 2, 3), model: 'claude-opus' } },
  ])
  expect(result).toEqual({
    turnId: 't1',
    index: expect.any(Number),
    answer: 'ok',
    toolUses: [],
    stopReason: 'end_turn',
    usage: { ...usage(1, 2, 3), model: 'claude-opus' },
  })
  // The pm tools ran beneath, unchanged.
  expect(w.tools).toEqual([GRAB])
})

test('a new run id starts a fresh summary; the old run stays kept', async ($, on) => {
  const clock = mock.clock(on)
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 2, 3))
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: OTHER_RUN })
  await request($, w, usage(5, 6, 7))

  expect(live(w)?.run?.runId).toBe(OTHER_RUN)
  expect(live(w)?.run?.tasks).toEqual({ 'US-PM-61-7': { requests: 1, input: 5, cacheRead: 6, cacheWrite: 7, output: 10 } })
  expect(live(w)?.requests.length).toBe(1)
  // The new run's loops start empty: a worker of the old run is not carried over.
  expect(live(w)?.loops).toEqual({ main: 'US-PM-61-7' })
  const kept = await stored(w, clock)
  expect(Object.keys(kept).sort()).toEqual([RUN, OTHER_RUN].sort())
  expect(kept[RUN]?.totals.requests).toBe(1)
})

// ------------------------------------------------- US-PM-61-5 criterion
//
// "The per-run summary is persisted so it survives a session restart."

test('US-PM-61-5 criterion: the run summary is written to $.store as it is recorded', async ($, on) => {
  const clock = mock.clock(on, { now: 5000 })
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(3, 20000, 500))
  await request($, w, usage(2, 100, 7), WORKER)

  const kept = await stored(w, clock)
  expect(kept[RUN]).toEqual(live(w)?.run)
  expect(kept[RUN]?.tasks['US-PM-61-6']?.requests).toBe(2)
  expect(kept[RUN]?.startedAt).toBe(5000)
})

test('US-PM-61-5 criterion: after a restart the same run goes on from its kept summary', async ($, on) => {
  // What a previous session of this run left in the store; this session's state is empty.
  const previous: ProjectmanCostRun = {
    runId: RUN,
    startedAt: 100,
    updatedAt: 200,
    tasks: { 'US-PM-61-6': { requests: 3, input: 30, cacheRead: 3000, cacheWrite: 300, output: 3 } },
    unattributed: { requests: 1, input: 1, cacheRead: 0, cacheWrite: 50, output: 1 },
    totals: { requests: 4, input: 31, cacheRead: 3000, cacheWrite: 350, output: 4 },
  }
  const older = newRun('orch-2026-10-01-0001', 1)
  const clock = mock.clock(on, { now: 900 })
  const w = world(on, { [COST_RUNS_KEY]: { [RUN]: previous, [older.runId]: older } })

  await pmCall($, ACCEPT, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 4000, 10))

  const run = live(w)?.run
  expect(run?.startedAt).toBe(100)
  expect(run?.tasks['US-PM-61-6']).toEqual({ requests: 4, input: 31, cacheRead: 7000, cacheWrite: 310, output: 13 })
  expect(run?.unattributed).toEqual(previous.unattributed)
  expect(run?.totals.requests).toBe(5)
  const kept = await stored(w, clock)
  expect(kept[RUN]).toEqual(run)
  expect(kept[older.runId]).toEqual(older)
})

test('a store that cannot be written leaves the live recording standing', async ($, on) => {
  const clock = mock.clock(on)
  const w = world(on)
  w.storeFails = true
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 2, 3))
  await clock.settle()
  expect(live(w)?.run?.tasks['US-PM-61-6']?.requests).toBe(1)
  expect(w.store).toEqual({})
  // Once the store answers again, the next request's write lands.
  w.storeFails = false
  await request($, w, usage(1, 2, 3))
  expect((await stored(w, clock))[RUN]).toEqual(live(w)?.run)
})

// A session restart, as two tests: each test loads the plugin afresh (its
// `$.state` empty, `register` run again), so the second test is a new mod
// instance whose only link to the first is the `$.store` the first left.
// The second is handed that store as written; it fails, naming why, when
// run without the first.
let sessionOne: { store: Record<string, unknown>; run: ProjectmanCostRun } | undefined

test('US-PM-61-5 criterion: restart, session one leaves its exact run summary in $.store', async ($, on) => {
  const clock = mock.clock(on, { now: 1000 })
  const w = world(on)
  await pmCall($, 'mcp__projectman__pm_update_sprint', { sprint_id: 'SPRINT-PM-21', status: 'active', run_id: RUN })
  await request($, w, usage(7, 100, 30))
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(3, 20000, 500))
  await request($, w, usage(10, 0, 9000), WORKER)

  const expected: ProjectmanCostRun = {
    runId: RUN,
    startedAt: 1000,
    updatedAt: 1000,
    tasks: { 'US-PM-61-6': { requests: 2, input: 13, cacheRead: 20000, cacheWrite: 9500, output: 20 } },
    unattributed: { requests: 1, input: 7, cacheRead: 100, cacheWrite: 30, output: 10 },
    totals: { requests: 3, input: 20, cacheRead: 20100, cacheWrite: 9530, output: 30 },
  }
  expect(live(w)?.run).toEqual(expected)
  const kept = await stored(w, clock)
  expect(Object.keys(kept)).toEqual([RUN])
  expect(kept[RUN]).toEqual(expected)
  sessionOne = { store: structuredClone(w.store), run: expected }
})

test('US-PM-61-5 criterion: restart, a fresh instance reads the kept summary back exactly and adds to it', async ($, on) => {
  if (sessionOne === undefined) throw new Error('needs the session-one test above to have run first')
  const clock = mock.clock(on, { now: 50000 })
  const w = world(on, sessionOne.store)
  // A fresh instance: nothing live until a run-carrying pm call.
  await request($, w, usage(99, 99, 99))
  expect(w.cost).toEqual([])

  // The same run id goes on from the kept summary, totals exact.
  await pmCall($, ACCEPT, { task_id: 'US-PM-61-6', run_id: RUN })
  expect(live(w)?.run).toEqual(sessionOne.run)

  // Requests add to it, never replace it.
  await request($, w, usage(2, 30000, 40, 5))
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: RUN }, 'agent-worker-2')
  await request($, w, usage(4, 0, 7000), 'agent-worker-2')
  const expected: ProjectmanCostRun = {
    runId: RUN,
    startedAt: 1000,
    updatedAt: 50000,
    tasks: {
      'US-PM-61-6': { requests: 3, input: 15, cacheRead: 50000, cacheWrite: 9540, output: 25 },
      'US-PM-61-7': { requests: 1, input: 4, cacheRead: 0, cacheWrite: 7000, output: 10 },
    },
    unattributed: { requests: 1, input: 7, cacheRead: 100, cacheWrite: 30, output: 10 },
    totals: { requests: 5, input: 26, cacheRead: 50100, cacheWrite: 16570, output: 45 },
  }
  expect(live(w)?.run).toEqual(expected)
  const kept = await stored(w, clock)
  expect(Object.keys(kept)).toEqual([RUN])
  expect(kept[RUN]).toEqual(expected)
})

test("US-PM-61-5 criterion: switching run ids keeps the old run's last summary, and switching back resumes it", async ($, on) => {
  const clock = mock.clock(on, { now: 2000 })
  const w = world(on)
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 2, 3))
  await request($, w, usage(4, 5, 6))
  const last = live(w)?.run
  expect(last?.totals).toEqual({ requests: 2, input: 5, cacheRead: 7, cacheWrite: 9, output: 20 })

  // The switch comes before the last request's write lands: that summary is still the one kept.
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: OTHER_RUN })
  await request($, w, usage(5, 6, 7))
  let kept = await stored(w, clock)
  expect(kept[RUN]).toEqual(last)
  expect(kept[OTHER_RUN]).toEqual(live(w)?.run)

  // More of the new run leaves the old run's summary as it was.
  await request($, w, usage(1, 1, 1))
  kept = await stored(w, clock)
  expect(kept[RUN]).toEqual(last)
  expect(kept[OTHER_RUN]?.totals.requests).toBe(2)

  // Back to the old run id: it goes on from its kept summary, not afresh.
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  expect(live(w)?.run).toEqual(last)
  await request($, w, usage(1, 1, 1))
  expect(live(w)?.run?.totals).toEqual({ requests: 3, input: 6, cacheRead: 8, cacheWrite: 10, output: 30 })
  kept = await stored(w, clock)
  expect(kept[RUN]).toEqual(live(w)?.run)
  expect(kept[OTHER_RUN]?.totals.requests).toBe(2)
})

test('US-PM-61-5 criterion: $.store keeps the 20 most recent runs, evicting the oldest', async ($, on) => {
  expect(KEPT_RUNS).toBe(20)
  const seeded: Record<string, ProjectmanCostRun> = {}
  for (let i = 1; i <= KEPT_RUNS; i++) seeded[`orch-old-${i}`] = newRun(`orch-old-${i}`, i)
  const clock = mock.clock(on, { now: 1000 })
  const w = world(on, { [COST_RUNS_KEY]: seeded })

  // A 21st run evicts the least recently updated one alone.
  await pmCall($, GRAB, { task_id: 'US-PM-61-6', run_id: RUN })
  await request($, w, usage(1, 2, 3))
  let kept = await stored(w, clock)
  expect(Object.keys(kept).length).toBe(KEPT_RUNS)
  expect(kept['orch-old-1']).toBeUndefined()
  for (let i = 2; i <= KEPT_RUNS; i++) expect(kept[`orch-old-${i}`]).toEqual(seeded[`orch-old-${i}`])
  expect(kept[RUN]).toEqual(live(w)?.run)

  // A 22nd evicts the next oldest; the runs this session updated stay.
  await pmCall($, GRAB, { task_id: 'US-PM-61-7', run_id: OTHER_RUN })
  await request($, w, usage(1, 2, 3))
  kept = await stored(w, clock)
  expect(Object.keys(kept).length).toBe(KEPT_RUNS)
  expect(kept['orch-old-2']).toBeUndefined()
  expect(kept['orch-old-3']).toEqual(seeded['orch-old-3'])
  expect(kept[RUN]?.totals.requests).toBe(1)
  expect(kept[OTHER_RUN]).toEqual(live(w)?.run)
})
