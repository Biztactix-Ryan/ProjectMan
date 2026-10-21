import type { On } from 'claude-code'
import type { ProjectmanCostRun, ProjectmanCostState, ProjectmanTokenCounts } from '../../types'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import { COST_RUNS_KEY } from '../../hooks/cost-record.ts'
import { costSummary, costView, countsText } from '../../hooks/cost-pane.tsx'
import { REPLAY_MOD_RUN, REPLAY_RUN_ID, REPLAY_TRANSCRIPT } from './fixtures/orch-replay.ts'

// US-PM-61-8: the recorder and the pane, fed one recorded orchestrator run.
//
// The mod only records in-process, so the run is replayed: each record of a
// synthetic Claude Code transcript (tests/fixtures/orch-replay/session.jsonl,
// mirrored in ./fixtures/orch-replay.ts) is turned back into the hooks the
// engine fires for it, in transcript order, the mock clock set to the
// record's timestamp:
//
// - a user record carrying a prompt (not only tool results) starts a
//   main-loop turn with that text (`turn.start`), so a `Heartbeat orch-...`
//   prompt marks its turn and a `<task-notification>` ends the mark;
// - the first record of each assistant message id is one model request
//   (`turn.step`) answering with that message's usage; the harness writes
//   one record per content block sharing one usage, so later records of the
//   same id are the same request and are not replayed again;
// - each `tool_use` block is the tool call (`tool.call`) with its input,
//   made after the request that produced it, as the engine makes it.
//
// What the replay records is REPLAY_MOD_RUN; tests/test_orch_cost_pane_crosscheck.py
// holds the same numbers against orch-cost on the same file.

type Usage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
}

type Block = { type?: string; text?: string; name?: string; input?: Record<string, unknown> }

type TranscriptRecord = {
  type?: string
  timestamp?: string
  message?: { id?: string; content?: string | Block[]; usage?: Usage }
}

type World = {
  /** The usage the next request answers with. */
  usages: Usage[]
  /** Each value the plugin wrote to projectman.cost, in order. */
  cost: (ProjectmanCostState | null)[]
  /** The plugin's `$.store`, in memory. */
  store: Record<string, unknown>
}

// The test's hooks beneath the plugin stand for the engine: every tool call
// answers plainly, each request answers with the usage queued for it.
function world(on: On): World {
  const w: World = { usages: [], cost: [], store: {} }
  on('store.get', ($, e) => ({ value: structuredClone(w.store[e.key]) }))
  on('store.set', ($, e) => {
    w.store[e.key] = structuredClone(e.value)
    return { value: undefined }
  })
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'cost') w.cost.push(e.value as ProjectmanCostState | null)
    return next(e)
  })
  on('tool.call', () => ({ result: 'ok', text: 'ok' }) as never)
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.step', async function* ($, e) {
    const u = w.usages.shift() ?? null
    const usage = u === null ? null : { ...u, model: 'claude-opus' }
    yield { kind: 'stop', stopReason: 'end_turn', usage }
    return { turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [], stopReason: 'end_turn', usage }
  })
  return w
}

/** The blocks of a record's message; a string content is one text block. */
function blocksOf(record: TranscriptRecord): Block[] {
  const content = record.message?.content
  if (typeof content === 'string') return [{ type: 'text', text: content }]
  return Array.isArray(content) ? content : []
}

/** Feeds the transcript's records through the plugin's hooks, in order. */
async function replay($: Engine, w: World, clock: MockClock, transcript: string, startMs: number): Promise<void> {
  const seen = new Set<string>()
  let now = startMs
  let turn = 0
  let turnId = 'turn-0'
  let index = 0
  for (const line of transcript.split('\n')) {
    if (line.trim() === '') continue
    const record = JSON.parse(line) as TranscriptRecord
    const at = Date.parse(record.timestamp ?? '')
    if (Number.isFinite(at) && at > now) {
      await clock.advance(at - now)
      now = at
    }
    const blocks = blocksOf(record)
    if (record.type === 'user') {
      const prompt = blocks.find((b) => b.type === 'text')
      if (prompt === undefined) continue // tool results only: the same turn goes on
      turnId = `turn-${++turn}`
      await $.turn.start({ text: prompt.text ?? '', turnId })
      continue
    }
    if (record.type !== 'assistant') continue
    const id = record.message?.id
    const usage = record.message?.usage
    if (typeof id === 'string' && usage !== undefined && !seen.has(id)) {
      seen.add(id)
      w.usages.push(usage)
      const stream = $.turn.step({ turnId, index: index++, model: 'claude-opus', messageCount: 3 })
      let piece = await stream.next()
      while (!piece.done) piece = await stream.next()
    }
    for (const block of blocks) {
      if (block.type === 'tool_use' && typeof block.name === 'string') {
        await $.tool.call({ tool: block.name, ...(block.input ?? {}) } as never)
      }
    }
  }
}

/** The first record's time: where the replay's clock starts. */
const START_MS = Date.parse((JSON.parse(REPLAY_TRANSCRIPT.trim().split('\n')[0] ?? '{}') as TranscriptRecord).timestamp ?? '')

const live = (w: World) => w.cost[w.cost.length - 1] ?? null

function sum(parts: ProjectmanTokenCounts[]): ProjectmanTokenCounts {
  const total = { requests: 0, input: 0, cacheRead: 0, cacheWrite: 0, output: 0 }
  for (const p of parts) {
    total.requests += p.requests
    total.input += p.input
    total.cacheRead += p.cacheRead
    total.cacheWrite += p.cacheWrite
    total.output += p.output
  }
  return total
}

async function replayed($: Engine, on: On) {
  const clock = mock.clock(on, { now: START_MS })
  const w = world(on)
  await replay($, w, clock, REPLAY_TRANSCRIPT, START_MS)
  await clock.settle()
  return { w, run: live(w)?.run ?? null, state: live(w) }
}

test('US-PM-61-8: the replayed run records the totals the cross-check holds orch-cost to', async ($, on) => {
  const { run } = await replayed($, on)
  expect(run?.runId).toBe(REPLAY_RUN_ID)
  expect(run?.totals).toEqual(REPLAY_MOD_RUN.totals)
  expect(run?.tasks).toEqual(REPLAY_MOD_RUN.tasks)
  expect(run?.unattributed).toEqual(REPLAY_MOD_RUN.unattributed)
  expect(run?.heartbeat).toEqual(REPLAY_MOD_RUN.heartbeat)
  expect(run?.pastTtl).toEqual(REPLAY_MOD_RUN.pastTtl)
})

test('US-PM-61-8: per task, the heartbeat bucket and unattributed partition the run total', async ($, on) => {
  const { run } = await replayed($, on)
  const r = run as ProjectmanCostRun
  const heartbeat = r.heartbeat as ProjectmanTokenCounts
  const { requests, input, cacheRead, cacheWrite, output } = heartbeat
  expect(sum([...Object.values(r.tasks), r.unattributed, { requests, input, cacheRead, cacheWrite, output }])).toEqual(r.totals)
})

test('US-PM-61-8: the request that makes the first run-carrying pm call is not recorded', async ($, on) => {
  // The engine runs the request before the tool call it produced, so the
  // run is not active yet when the opening pm_grab's request is recorded:
  // the systematic difference from orch-cost, which counts it.
  const { state } = await replayed($, on)
  expect(state?.requests.length).toBe(REPLAY_MOD_RUN.totals.requests)
  expect(state?.requests[0]?.cacheRead).toBe(19200)
  expect(state?.requests[0]?.taskId).toBe('US-DEMO-1-1')
})

test('US-PM-61-8: the kept summary and the pane show the recorded totals', async ($, on) => {
  const { w, run } = await replayed($, on)
  const kept = (w.store[COST_RUNS_KEY] ?? {}) as Record<string, ProjectmanCostRun>
  expect(kept[REPLAY_RUN_ID]).toEqual(run as ProjectmanCostRun)

  // The pane's text rounds counts to 0.1k / 0.1M; the recorded counts are exact.
  const summary = costSummary(costView(null, kept[REPLAY_RUN_ID] ?? null))
  expect(summary).toContain(`Total  ${countsText(REPLAY_MOD_RUN.totals)}`)
  for (const [id, counts] of Object.entries(REPLAY_MOD_RUN.tasks as Record<string, ProjectmanTokenCounts>)) {
    expect(summary).toContain(`${id}  ${countsText(counts)}`)
  }
  expect(summary).toContain('Bridged 1 wait over the TTL')
})
