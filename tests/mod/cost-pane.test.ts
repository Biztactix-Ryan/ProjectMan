import type { CommandRunInput, On, RenderSurface } from 'claude-code'
import type { ProjectmanCostRun, ProjectmanCostState } from '../../types'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import {
  CACHE_TTL_MS,
  COST_RUNS_KEY,
  emptyCounts,
  isHeartbeatPrompt,
  MAIN_LOOP,
  markTurn,
  newRun,
  attribute,
  recordRequest,
} from '../../hooks/cost-record.ts'
import {
  COST_COMMAND,
  COST_HEARTBEAT_KEY,
  COST_OPENED,
  COST_PANE,
  COST_PANE_TITLE,
  COST_REQUESTS_KEY,
  COST_TASKS_KEY,
  costSummary,
  costView,
  duration,
  PAST_TTL_MARK,
  tokens,
} from '../../hooks/cost-pane.tsx'

// US-PM-61-7: the cache-cost pane draws the active run's per-task input /
// cache-read / cache-write totals from `projectman.cost`, marks requests that
// followed a gap over the cache TTL, and keeps heartbeat requests in their own
// bucket with the cache writes they avoided. The test's hooks beneath the
// plugin stand for the engine: the pm tools answer plainly, each `turn.step`
// answers with the queued usage, the clock is mocked and moved between
// requests, and the surface seats the pane.

const RUN = 'orch-2026-10-21-3a6e'
const GRAB = 'mcp__plugin_projectman_projectman__pm_grab'
const WORKER = 'agent-worker-1'
const MIN = 60_000
const HEARTBEAT = `Heartbeat ${RUN}: worker out → reply in five words, no tools; no run in flight → CronDelete this job`

type Usage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number }

const usage = (input: number, cacheRead: number, cacheWrite: number, output = 10): Usage => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: cacheRead,
  cache_creation_input_tokens: cacheWrite,
})

type World = {
  usages: (Usage | null)[]
  cost: (ProjectmanCostState | null)[]
  store: Record<string, unknown>
  opened: { id: string; title?: string }[]
  surfaces: readonly RenderSurface[]
  isPlaced: boolean
  core: string[]
}

function world(on: On, store: Record<string, unknown> = {}): World {
  const w: World = { usages: [], cost: [], store: { ...store }, opened: [], surfaces: ['terminal'], isPlaced: true, core: [] }
  on('store.get', ($, e) => ({ value: structuredClone(w.store[e.key]) }))
  on('store.set', ($, e) => {
    w.store[e.key] = structuredClone(e.value)
    return { value: undefined }
  })
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'cost') w.cost.push(e.value as ProjectmanCostState | null)
    return next(e)
  })
  on('session.surfaces', () => ({ value: w.surfaces }))
  on('ui.open', ($, e) => {
    w.opened.push({ id: e.id, title: e.title })
    return { value: w.isPlaced ? { isPlaced: true } : { isPlaced: false, reason: 'the terminal is 80 columns wide' } }
  })
  on('command.run', ($, e) => {
    w.core.push(e.command)
    return { text: 'core ran' }
  })
  on('tool.call', { tool: /^mcp__/ }, () => ({ result: 'ok', text: 'ok' }) as never)
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.step', async function* ($, e) {
    const u = w.usages.shift() ?? null
    yield { kind: 'stop', stopReason: 'end_turn', usage: u === null ? null : { ...u, model: 'claude-opus' } }
    return { turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [], stopReason: 'end_turn', usage: u === null ? null : { ...u, model: 'claude-opus' } }
  })
  return w
}

let stepIndex = 0

/** One model request in `turnId`, in the main loop or a subagent's, read to its end. */
async function request($: Engine, w: World, u: Usage, opts: { agentId?: string; turnId?: string } = {}) {
  w.usages.push(u)
  const stream = $.turn.step({
    turnId: opts.turnId ?? 'turn-work',
    index: stepIndex++,
    model: 'claude-opus',
    messageCount: 3,
    ...(opts.agentId ? { agentId: opts.agentId } : {}),
  })
  let piece = await stream.next()
  while (!piece.done) piece = await stream.next()
}

/** A turn starting in the main loop (or a subagent's) with `text` as its prompt. */
const startTurn = ($: Engine, turnId: string, text: string, agentId?: string) =>
  $.turn.start({ text, turnId, ...(agentId ? { agentId } : {}) })

const grab = ($: Engine, taskId: string, agentId?: string) =>
  $.tool.call({ tool: GRAB, task_id: taskId, run_id: RUN, ...(agentId ? { agentId } : {}) } as never)

const live = (w: World) => w.cost[w.cost.length - 1] ?? null

function paneProps(bodyColumns = 120) {
  return { title: COST_PANE_TITLE, isFocused: false, bodyColumns, placement: 'dock' as const, scroll: { offset: 0, bodyRows: 40 }, view: {} }
}

const mount = ($: Engine, surface: RenderSurface) =>
  $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: COST_PANE, props: paneProps() })

function run(command: string): CommandRunInput {
  return { command, args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } } as CommandRunInput
}

/**
 * Two tasks, a worker, and one main-loop wait that outlived the TTL:
 * US-PM-61-6 3 req (input 14, read 29000, write 9800);
 * US-PM-61-7 2 req (input 6, read 20500, write 24100), the second after 70m.
 */
async function twoTasks($: Engine, w: World, clock: MockClock): Promise<void> {
  await grab($, 'US-PM-61-6')
  await request($, w, usage(3, 20000, 500))
  await clock.advance(1 * MIN)
  // The worker's first request, before its own pm_grab: the orchestrator's task.
  await request($, w, usage(10, 0, 9000), { agentId: WORKER })
  await grab($, 'US-PM-61-6', WORKER)
  await clock.advance(1 * MIN)
  await request($, w, usage(1, 9000, 300), { agentId: WORKER })
  await grab($, 'US-PM-61-7')
  await request($, w, usage(2, 20500, 100))
  // The orchestrator waits 70 minutes on a worker: its prefix expired.
  await clock.advance(70 * MIN)
  await request($, w, usage(4, 0, 24000))
}

/**
 * A run bridged by heartbeats: work at 0, heartbeats at 30m and 60m, and the
 * worker's hand-back at 80m, 80m after the last real request yet 20m after
 * the last heartbeat, still reading the 30.2k prefix from the cache.
 */
async function bridgedRun($: Engine, w: World, clock: MockClock): Promise<void> {
  await grab($, 'US-PM-61-7')
  await startTurn($, 'turn-1', 'run the sprint')
  await request($, w, usage(2, 30000, 200), { turnId: 'turn-1' })
  await clock.advance(30 * MIN)
  await startTurn($, 'hb-1', HEARTBEAT)
  await request($, w, usage(1, 30200, 0, 8), { turnId: 'hb-1' })
  await clock.advance(30 * MIN)
  await startTurn($, 'hb-2', HEARTBEAT)
  await request($, w, usage(1, 30200, 0, 8), { turnId: 'hb-2' })
  await clock.advance(20 * MIN)
  await startTurn($, 'turn-2', '<task-notification>US-PM-61-7 done</task-notification>')
  await request($, w, usage(3, 30200, 900), { turnId: 'turn-2' })
}

// ------------------------------------------------- the pure parts

test('tokens and duration read short', () => {
  expect([tokens(0), tokens(600), tokens(1000), tokens(20500), tokens(9800), tokens(1_250_000)]).toEqual(['0', '600', '1k', '20.5k', '9.8k', '1.3M'])
  expect([duration(40_000), duration(2 * MIN), duration(70 * MIN), duration(CACHE_TTL_MS)]).toEqual(['40s', '2m', '1h10m', '1h00m'])
})

test('isHeartbeatPrompt matches the /pm-orchestrate keep-alive and nothing else', () => {
  expect(isHeartbeatPrompt(HEARTBEAT)).toBe(true)
  expect(isHeartbeatPrompt(`  ${HEARTBEAT}`)).toBe(true)
  expect(isHeartbeatPrompt('heartbeat orch-1')).toBe(false)
  expect(isHeartbeatPrompt('Heartbeat check please')).toBe(false)
  expect(isHeartbeatPrompt(undefined)).toBe(false)
})

test('markTurn marks a main-loop heartbeat turn only, and returns the same state when nothing changes', () => {
  expect(markTurn(null, MAIN_LOOP, 'hb', HEARTBEAT)).toBeNull()
  const idle: ProjectmanCostState = { run: null, requests: [], loops: {} }
  expect(markTurn(idle, MAIN_LOOP, 'hb', HEARTBEAT)).toBe(idle)
  const active = attribute(null, { runId: RUN, taskId: 'US-PM-61-7' }, MAIN_LOOP, 0)
  // A subagent's prompt never marks, even one spelled like the heartbeat.
  expect(markTurn(active, WORKER, 'w', HEARTBEAT)).toBe(active)
  // Another main-loop turn with no mark set: nothing to change.
  expect(markTurn(active, MAIN_LOOP, 't', 'hello')).toBe(active)
  const marked = markTurn(active, MAIN_LOOP, 'hb', HEARTBEAT)
  expect(marked?.heartbeatTurn).toBe('hb')
  expect(markTurn(marked, MAIN_LOOP, 't2', 'next prompt')?.heartbeatTurn).toBeNull()
})

test('recordRequest times each loop on its own and marks a gap over the TTL', () => {
  let s = attribute(null, { runId: RUN, taskId: 'US-PM-61-7' }, MAIN_LOOP, 0)
  s = recordRequest(s, MAIN_LOOP, usage(1, 0, 100), 0)!
  s = recordRequest(s, WORKER, usage(1, 0, 100), 50 * MIN)!
  s = recordRequest(s, MAIN_LOOP, usage(1, 100, 0), CACHE_TTL_MS)!
  s = recordRequest(s, WORKER, usage(1, 0, 100), 50 * MIN + CACHE_TTL_MS + 1)!
  expect(s.requests.map((r) => [r.agentId, r.gapMs, r.isPastTtl, r.isHeartbeat])).toEqual([
    [null, null, false, false],
    [WORKER, null, false, false],
    // Exactly the TTL is not past it.
    [null, CACHE_TTL_MS, false, false],
    [WORKER, CACHE_TTL_MS + 1, true, false],
  ])
  expect(s.run?.pastTtl).toEqual({ 'US-PM-61-7': 1 })
  // No heartbeat: no bucket.
  expect(s.run?.heartbeat).toBeUndefined()
})

test('recordRequest puts heartbeat requests in their own bucket and counts a late heartbeat past TTL', () => {
  let s = attribute(null, { runId: RUN, taskId: 'US-PM-61-7' }, MAIN_LOOP, 0)
  s = recordRequest(s, MAIN_LOOP, usage(2, 1000, 50), 0)!
  s = markTurn(s, MAIN_LOOP, 'hb', HEARTBEAT)!
  // The heartbeat fires too late: 61 minutes after the last request.
  s = recordRequest(s, MAIN_LOOP, usage(1, 0, 1050, 5), 61 * MIN, { turnId: 'hb' })!
  // A subagent's request during the heartbeat turn is the worker's, not a heartbeat.
  s = recordRequest(s, WORKER, usage(1, 0, 7), 61 * MIN, { turnId: 'hb' })!
  expect(s.run?.tasks['US-PM-61-7']).toEqual({ requests: 2, input: 3, cacheRead: 1000, cacheWrite: 57, output: 20 })
  expect(s.run?.heartbeat).toEqual({ requests: 1, input: 1, cacheRead: 0, cacheWrite: 1050, output: 5, bridged: 0, avoidedWrites: 0 })
  expect(s.run?.totals.requests).toBe(3)
  expect(s.run?.unattributed).toEqual(emptyCounts())
  expect(s.run?.pastTtl).toEqual({ heartbeat: 1 })
  expect(s.requests.map((r) => [r.taskId, r.isHeartbeat])).toEqual([
    ['US-PM-61-7', false],
    [null, true],
    ['US-PM-61-7', false],
  ])
})

test('recordRequest credits a bridged wait with the cache reads it kept, and only a bridged one', () => {
  let s = attribute(null, { runId: RUN, taskId: 'US-PM-61-7' }, MAIN_LOOP, 0)
  s = recordRequest(s, MAIN_LOOP, usage(2, 30000, 200), 0)!
  // Within the TTL with no heartbeat between: nothing bridged.
  s = recordRequest(s, MAIN_LOOP, usage(2, 30200, 100), 50 * MIN)!
  expect(s.run?.heartbeat).toBeUndefined()
  s = markTurn(s, MAIN_LOOP, 'hb', HEARTBEAT)!
  s = recordRequest(s, MAIN_LOOP, usage(1, 30300, 0), 100 * MIN, { turnId: 'hb' })!
  s = markTurn(s, MAIN_LOOP, 'w', 'go on')!
  // 70m since the last real request, 20m since the heartbeat: bridged.
  s = recordRequest(s, MAIN_LOOP, usage(3, 30300, 500), 120 * MIN, { turnId: 'w' })!
  // The next one is 5m on: a plain request, nothing more avoided.
  s = recordRequest(s, MAIN_LOOP, usage(3, 30800, 50), 125 * MIN, { turnId: 'w' })!
  expect(s.run?.heartbeat).toMatchObject({ requests: 1, bridged: 1, avoidedWrites: 30300 })
  expect(s.run?.pastTtl).toBeUndefined()
})

test('costView prefers the live run, else the kept one', () => {
  const kept = newRun('orch-kept', 5)
  const state = attribute(null, { runId: RUN, taskId: null }, MAIN_LOOP, 0)
  expect(costView(state, kept)?.run.runId).toBe(RUN)
  expect(costView(state, kept)?.isLive).toBe(true)
  expect(costView(null, kept)).toMatchObject({ isLive: false, requests: [] })
  expect(costView(null, null)).toBeNull()
})

// ------------------------------------------------- US-PM-61-2 criterion
//
// "A pane shows per-task totals and marks requests that followed a gap longer
// than the cache TTL."

for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
  test(`US-PM-61-2 criterion: on ${surface}, the pane shows per-task totals and marks the request after a gap over the TTL`, async ($, on) => {
    const clock = mock.clock(on, { now: 0 })
    const w = world(on)
    await twoTasks($, w, clock)

    const ui = await mount($, surface)
    expect(await ui.find({ type: 'Text', text: `Run ${RUN} · live` })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /requests · cache TTL/ }))?.text).toBe('5 requests · cache TTL 1h00m · 1 past TTL')

    // Per task: input, cache read and cache write, in the order first charged.
    const rows = (await ui.findAll({ type: 'Text', text: /req · input/ })).map((t) => t.text)
    expect(rows.slice(0, 3)).toEqual([
      'US-PM-61-6  3 req · input 14 · cache read 29k · cache write 9.8k',
      'US-PM-61-7  2 req · input 6 · cache read 20.5k · cache write 24.1k · 1 past TTL',
      'Total  5 req · input 20 · cache read 49.5k · cache write 33.9k',
    ])
    expect(await ui.find({ type: 'Box', key: COST_TASKS_KEY })).toBeDefined()

    // The request after the 70-minute wait carries the marker; no other does.
    const marked = await ui.findAll({ type: 'Text', text: PAST_TTL_MARK })
    expect(marked.map((t) => t.text)).toEqual([`+1h10m  US-PM-61-7  input 4 · read 0 · write 24k  ${PAST_TTL_MARK}`])
    expect(marked[0]?.props.color).toBe('warning')
    expect(await ui.find({ type: 'Text', text: '+1m  US-PM-61-6 (worker)  input 1 · read 9k · write 300' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'first  US-PM-61-6 (worker)  input 10 · read 0 · write 9k' })).toBeDefined()
    expect(await ui.find({ type: 'Box', key: COST_REQUESTS_KEY })).toBeDefined()
    await ui.unmount()
  })
}

test('US-PM-61-2 criterion: the pane redraws as each request is recorded', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-7')
  await request($, w, usage(2, 1000, 100))
  const ui = await mount($, 'terminal')
  expect(await ui.find({ type: 'Text', text: 'US-PM-61-7  1 req · input 2 · cache read 1k · cache write 100' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: PAST_TTL_MARK })).toBeUndefined()

  await clock.advance(CACHE_TTL_MS + MIN)
  await request($, w, usage(5, 0, 1200))
  expect(await ui.find({ type: 'Text', text: 'US-PM-61-7  2 req · input 7 · cache read 1k · cache write 1.3k · 1 past TTL' })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: PAST_TTL_MARK }))?.text).toBe(`+1h01m  US-PM-61-7  input 5 · read 0 · write 1.2k  ${PAST_TTL_MARK}`)
  await ui.unmount()
})

test('US-PM-61-2 criterion: the pane marks a gap over the TTL per loop, and not one of exactly the TTL', async ($, on) => {
  // Main loop at 0 and 60m (exactly the TTL: not past it); the worker at 30m
  // and 90m + 1ms (its own gap is past the TTL, though only 30m + 1ms after
  // the main loop's last request, so a gap taken across loops would miss it).
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-6')
  await request($, w, usage(3, 1200, 400))
  await clock.advance(30 * MIN)
  await grab($, 'US-PM-61-7', WORKER)
  await request($, w, usage(5, 0, 900), { agentId: WORKER })
  await clock.advance(30 * MIN)
  await request($, w, usage(2, 1600, 0))
  await clock.advance(30 * MIN + 1)
  await request($, w, usage(4, 0, 1100), { agentId: WORKER })

  // Recorded exactly, per task.
  const recorded = live(w)?.run
  expect(recorded?.tasks).toEqual({
    'US-PM-61-6': { requests: 2, input: 5, cacheRead: 2800, cacheWrite: 400, output: 20 },
    'US-PM-61-7': { requests: 2, input: 9, cacheRead: 0, cacheWrite: 2000, output: 20 },
  })
  expect(recorded?.pastTtl).toEqual({ 'US-PM-61-7': 1 })

  const ui = await mount($, 'terminal')
  expect((await ui.find({ type: 'Text', text: /requests · cache TTL/ }))?.text).toBe('4 requests · cache TTL 1h00m · 1 past TTL')
  const rows = (await ui.findAll({ type: 'Text', text: /req · input/ })).map((t) => t.text)
  expect(rows).toEqual([
    'US-PM-61-6  2 req · input 5 · cache read 2.8k · cache write 400',
    'US-PM-61-7  2 req · input 9 · cache read 0 · cache write 2k · 1 past TTL',
    'Total  4 req · input 14 · cache read 2.8k · cache write 2.4k',
  ])
  // Newest first: only the worker's request past its own loop's TTL is marked.
  const requests = (await ui.findAll({ type: 'Text', text: /  input \d/ })).map((t) => [t.text, t.props.color])
  expect(requests).toEqual([
    [`+1h00m  US-PM-61-7 (worker)  input 4 · read 0 · write 1.1k  ${PAST_TTL_MARK}`, 'warning'],
    ['+1h00m  US-PM-61-6  input 2 · read 1.6k · write 0', undefined],
    ['first  US-PM-61-7 (worker)  input 5 · read 0 · write 900', undefined],
    ['first  US-PM-61-6  input 3 · read 1.2k · write 400', undefined],
  ])
  expect(live(w)?.requests.map((r) => r.gapMs)).toEqual([null, null, CACHE_TTL_MS, CACHE_TTL_MS + 1])
  await ui.unmount()
})

test('with no run live the pane draws the most recently kept run, and says so', async ($, on) => {
  const older: ProjectmanCostRun = { ...newRun('orch-2026-10-01-0001', 1), updatedAt: 10 }
  const recent: ProjectmanCostRun = {
    ...newRun('orch-2026-10-20-0002', 100),
    updatedAt: 200,
    tasks: { 'US-PM-61-6': { requests: 4, input: 31, cacheRead: 7000, cacheWrite: 310, output: 13 } },
    totals: { requests: 4, input: 31, cacheRead: 7000, cacheWrite: 310, output: 13 },
    pastTtl: { 'US-PM-61-6': 2 },
  }
  mock.clock(on)
  world(on, { [COST_RUNS_KEY]: { [older.runId]: older, [recent.runId]: recent } })
  const ui = await mount($, 'desktop')
  expect(await ui.find({ type: 'Text', text: 'Run orch-2026-10-20-0002 · last kept, not live' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'US-PM-61-6  4 req · input 31 · cache read 7k · cache write 310 · 2 past TTL' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Requests are listed for the live run only.' })).toBeDefined()
  await ui.unmount()
})

test('with no run recorded or kept the pane says how one starts', async ($, on) => {
  mock.clock(on)
  world(on)
  const ui = await mount($, 'terminal')
  expect(await ui.find({ type: 'Text', text: 'No orchestrator run recorded yet' })).toBeDefined()
  expect(await ui.find({ type: 'Box', key: COST_TASKS_KEY })).toBeUndefined()
  await ui.unmount()
})

// ------------------------------------------------- US-PM-61-3 criterion
//
// "Heartbeat requests are counted separately so their cost and the cache
// writes they avoided are visible."

for (const surface of ['terminal', 'desktop'] as const) {
  test(`US-PM-61-3 criterion: on ${surface}, heartbeats have their own bucket with the cache writes they avoided`, async ($, on) => {
    const clock = mock.clock(on, { now: 0 })
    const w = world(on)
    await bridgedRun($, w, clock)

    // Recorded: the heartbeats are not the task's, and the bridged wait is credited.
    const runNow = live(w)?.run
    expect(runNow?.tasks['US-PM-61-7']).toEqual({ requests: 2, input: 5, cacheRead: 60200, cacheWrite: 1100, output: 20 })
    expect(runNow?.heartbeat).toEqual({ requests: 2, input: 2, cacheRead: 60400, cacheWrite: 0, output: 16, bridged: 1, avoidedWrites: 30200 })
    expect(runNow?.totals.requests).toBe(4)
    expect(runNow?.pastTtl).toBeUndefined()

    const ui = await mount($, surface)
    const beat = (await ui.find({ type: 'Box', key: COST_HEARTBEAT_KEY }))!
    expect(beat).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '2 req · input 2 · cache read 60.4k · cache write 0' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Bridged 1 wait over the TTL · avoided 30.2k cache-write tokens' })).toBeDefined()
    // The task row leaves the heartbeats out; the total keeps them.
    expect(await ui.find({ type: 'Text', text: 'US-PM-61-7  2 req · input 5 · cache read 60.2k · cache write 1.1k' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Total  4 req · input 7 · cache read 120.6k · cache write 1.1k' })).toBeDefined()
    // The heartbeat requests are listed as such; nothing is past the TTL.
    expect((await ui.findAll({ type: 'Text', text: /heartbeat  input/ })).map((t) => t.text)).toEqual([
      '+30m  heartbeat  input 1 · read 30.2k · write 0',
      '+30m  heartbeat  input 1 · read 30.2k · write 0',
    ])
    expect(await ui.find({ type: 'Text', text: '+20m  US-PM-61-7  input 3 · read 30.2k · write 900' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: PAST_TTL_MARK })).toBeUndefined()
    await ui.unmount()
  })
}

test('US-PM-61-3 criterion: a run with no heartbeat shows an empty heartbeat bucket', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await twoTasks($, w, clock)
  const ui = await mount($, 'terminal')
  expect(await ui.find({ type: 'Text', text: 'No heartbeat requests yet.' })).toBeDefined()
  await ui.unmount()
})

test('US-PM-61-3 criterion: without heartbeats the same wait is a marked miss, not a bridged one', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-7')
  await startTurn($, 'turn-1', 'run the sprint')
  await request($, w, usage(2, 30000, 200), { turnId: 'turn-1' })
  await clock.advance(80 * MIN)
  await startTurn($, 'turn-2', '<task-notification>US-PM-61-7 done</task-notification>')
  await request($, w, usage(3, 0, 30400), { turnId: 'turn-2' })
  expect(live(w)?.run?.heartbeat).toBeUndefined()
  expect(live(w)?.run?.pastTtl).toEqual({ 'US-PM-61-7': 1 })
  const ui = await mount($, 'terminal')
  expect((await ui.find({ type: 'Text', text: PAST_TTL_MARK }))?.text).toBe(`+1h20m  US-PM-61-7  input 3 · read 0 · write 30.4k  ${PAST_TTL_MARK}`)
  await ui.unmount()
})

test('US-PM-61-3 criterion: a heartbeat that bridged no wait shows its exact cost and zero avoided writes', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-7')
  await startTurn($, 'turn-1', 'run the sprint')
  await request($, w, usage(2, 30000, 200), { turnId: 'turn-1' })
  await clock.advance(30 * MIN)
  await startTurn($, 'hb-1', HEARTBEAT)
  await request($, w, usage(1, 30200, 0, 8), { turnId: 'hb-1' })
  // The hand-back comes 40m after the last real request: inside the TTL, nothing bridged.
  await clock.advance(10 * MIN)
  await startTurn($, 'turn-2', '<task-notification>US-PM-61-7 done</task-notification>')
  await request($, w, usage(3, 30200, 900), { turnId: 'turn-2' })

  const runNow = live(w)?.run
  expect(runNow?.tasks['US-PM-61-7']).toEqual({ requests: 2, input: 5, cacheRead: 60200, cacheWrite: 1100, output: 20 })
  expect(runNow?.heartbeat).toEqual({ requests: 1, input: 1, cacheRead: 30200, cacheWrite: 0, output: 8, bridged: 0, avoidedWrites: 0 })

  const ui = await mount($, 'terminal')
  expect(await ui.find({ type: 'Text', text: '1 req · input 1 · cache read 30.2k · cache write 0' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Bridged 0 waits over the TTL · avoided 0 cache-write tokens' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'US-PM-61-7  2 req · input 5 · cache read 60.2k · cache write 1.1k' })).toBeDefined()
  await ui.unmount()
})

test('US-PM-61-3 criterion: a prompt that mentions the heartbeat but does not open with it is not counted as one', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-7')
  await startTurn($, 'turn-1', `Why did the ${HEARTBEAT}`)
  await request($, w, usage(2, 30000, 200), { turnId: 'turn-1' })
  await clock.advance(5 * MIN)
  await startTurn($, 'turn-2', `heartbeat ${RUN}: is it still running?`)
  await request($, w, usage(1, 30200, 0, 8), { turnId: 'turn-2' })

  const runNow = live(w)?.run
  expect(runNow?.heartbeat).toBeUndefined()
  expect(runNow?.tasks['US-PM-61-7']).toEqual({ requests: 2, input: 3, cacheRead: 60200, cacheWrite: 200, output: 18 })
  expect(live(w)?.requests.map((r) => r.isHeartbeat)).toEqual([false, false])

  const ui = await mount($, 'terminal')
  expect(await ui.find({ type: 'Text', text: 'No heartbeat requests yet.' })).toBeDefined()
  expect(await ui.findAll({ type: 'Text', text: /heartbeat  input/ })).toEqual([])
  expect(await ui.find({ type: 'Text', text: 'US-PM-61-7  2 req · input 3 · cache read 60.2k · cache write 200' })).toBeDefined()
  await ui.unmount()
})

test("a subagent's turn never starts the heartbeat bucket, and a plain turn writes no mark", async ($, on) => {
  mock.clock(on, { now: 0 })
  const w = world(on)
  await grab($, 'US-PM-61-7')
  const before = w.cost.length
  await startTurn($, 'turn-1', 'run the sprint')
  await startTurn($, 'w-1', HEARTBEAT, WORKER)
  expect(w.cost.length).toBe(before)
  await request($, w, usage(1, 2, 3), { agentId: WORKER, turnId: 'w-1' })
  expect(live(w)?.run?.heartbeat).toBeUndefined()
})

// ------------------------------------------------- /pm-cost

test('/pm-cost opens the pane where a surface seats it, with no model request or MCP call', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await twoTasks($, w, clock)
  const ran = await $.command.run(run(COST_COMMAND))
  expect(ran.text).toBe(COST_OPENED)
  expect(w.opened).toEqual([{ id: COST_PANE, title: COST_PANE_TITLE }])
  expect(w.core).toEqual([])
})

test('/pm-cost answers with the same content as text where no surface draws or the pane cannot be seated', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const w = world(on)
  await bridgedRun($, w, clock)
  const expected = costSummary(costView(live(w), null))
  expect(expected).toContain('Per task:\n  US-PM-61-7  2 req · input 5 · cache read 60.2k · cache write 1.1k')
  expect(expected).toContain('Heartbeats:\n  2 req · input 2 · cache read 60.4k · cache write 0\n  Bridged 1 wait over the TTL · avoided 30.2k cache-write tokens')

  w.surfaces = []
  expect((await $.command.run(run(COST_COMMAND))).text).toBe(expected)
  expect(w.opened).toEqual([])

  w.surfaces = ['terminal']
  w.isPlaced = false
  expect((await $.command.run(run(COST_COMMAND))).text).toBe(expected)
  expect(w.opened).toEqual([{ id: COST_PANE, title: COST_PANE_TITLE }])
})

test('the text summary lists the requests past the TTL', () => {
  let s = attribute(null, { runId: RUN, taskId: 'US-PM-61-7' }, MAIN_LOOP, 0)
  s = recordRequest(s, MAIN_LOOP, usage(1, 0, 100), 0)!
  s = recordRequest(s, MAIN_LOOP, usage(1, 0, 2000), 2 * CACHE_TTL_MS)!
  expect(costSummary(costView(s, null))).toContain(
    `Requests past TTL (most recent first):\n  +2h00m  US-PM-61-7  input 1 · read 0 · write 2k  ${PAST_TTL_MARK}`,
  )
  expect(costSummary(null)).toContain('No orchestrator run recorded yet')
})

test('/pm-cost does not clash with the plugin skills', () => {
  const skills = ['pm', 'pm-autoscope', 'pm-cleanup', 'pm-do', 'pm-next', 'pm-orchestrate', 'pm-plan', 'pm-status']
  expect(skills.includes(COST_COMMAND)).toBe(false)
})
