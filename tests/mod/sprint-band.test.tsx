import type { On, RenderSurface } from 'claude-code'
import type { ProjectmanBandState } from '../../types'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import {
  BAND_KEY,
  bandFrom,
  bandLines,
  noteHead,
  sprintProgress,
  taskInFlight,
} from '../../hooks/sprint-band.tsx'
import { parseYaml } from '../../hooks/pm-views.ts'
import { movesBand, PM_WRITE_TOOLS, pmToolName } from '../../hooks/band-refresh.ts'

// US-PM-62-6: the sprint band above the prompt. The test's hooks beneath the
// plugin stand for the engine: they answer mcp.connect / mcp.call from canned
// server output (or with the error a directory with no store gets), draw a
// marker where the engine's own band would show, and record any model call.
// The clock is mocked, so the read the band's first draw schedules runs when
// the test settles it.

const SERVER = 'plugin:projectman:projectman'
const ENGINE_BAND = 'engine-band'

// What the projectman server writes (PyYAML, block style), trimmed.
const SPRINTS_YAML = `sprints:
- id: SPRINT-PM-21
  name: Sprint 20 — The Project Asks, You Answer
count: 1
`
const NO_SPRINTS_YAML = `sprints: []
count: 0
`
const SPRINT_YAML = `id: SPRINT-PM-21
name: Sprint 20 — The Project Asks, You Answer
status: active
planned_stories:
- US-PM-65
- US-PM-62
- US-PM-56
planned_points: 19
completed_points: 0
story_progress:
- story_id: US-PM-65
  title: /pm-decide works through the open decisions with you
  status: done
  tasks_done: 10
  tasks_total: 10
  points: 5
- story_id: US-PM-67
  title: Status and planning show the decision backlog
  status: done
  tasks_done: 7
  tasks_total: 7
  points: 3
- story_id: US-PM-66
  title: Answers reach the work they unblock
  status: done
  tasks_done: 6
  tasks_total: 6
  points: 3
- story_id: US-PM-62
  title: 'Mod: sprint band above the prompt'
  status: ready
  tasks_done: 0
  tasks_total: 8
  points: 3
- story_id: US-PM-56
  title: ProjectMan installs as a Claude Code plugin from this repo's marketplace
  status: ready
  tasks_done: 11
  tasks_total: 12
  points: 5
long_task_risk: []
`
const ACTIVE_YAML = `active_stories: []
active_stories_total: 0
active_tasks:
- id: US-PM-62-6
  story_id: US-PM-62
  title: Draw the sprint band above the prompt
  status: in-progress
  points: 2
  claimed_by_run: orch-2026-10-21-feb2
active_tasks_total: 1
stale_tasks: []
limit: 1
offset: 0
has_more: false
`
const NO_ACTIVE_YAML = `active_stories: []
active_stories_total: 0
active_tasks: []
active_tasks_total: 0
stale_tasks: []
limit: 1
offset: 0
has_more: false
`
// PyYAML writes a newline inside a single-quoted scalar as a blank line.
const NOTE_YAML = `note: 'Close EPIC-PM-7 once US-PM-62 lands.

  Then cut 0.12.0.'
`
const NO_NOTE_YAML = `note: null
message: no note saved
`

const ANSWERS: Record<string, string> = {
  pm_list_sprints: SPRINTS_YAML,
  pm_get_sprint: SPRINT_YAML,
  pm_active: ACTIVE_YAML,
  pm_next: NOTE_YAML,
}

const SPRINT_PART = 'Sprint 20 — 11/19 pts'
const TASK_PART = '▶ US-PM-62-6 Draw the sprint band above the prompt'
const NOTE_PART = 'next: Close EPIC-PM-7 once US-PM-62 lands.'
const FULL_LINE = `${SPRINT_PART} · ${TASK_PART} · ${NOTE_PART}`

// What the MCP server answers where the directory has no ProjectMan store.
const NO_STORE = 'Error executing tool: No .project/config.yaml found in any parent directory'

type Seen = {
  mcp: { server: string; tool: string; args: Record<string, unknown> }[]
  model: string[]
  /** Each value the plugin wrote to projectman.band, in order. */
  band: (ProjectmanBandState | null)[]
}

type EngineOpts = {
  /** Every tool answers with the no-store error. */
  noStore?: boolean
  /** This tool answers with an error. */
  errorTool?: string
  connected?: boolean
  /** Runs before each call is answered: may hold it, or throw as a server gone away. */
  onCall?: (tool: string) => Promise<void> | void
}

// `answers` and `opts` are read at each call, so a test can change them between reads.
function engine(on: On, answers: Record<string, string>, opts: EngineOpts = {}): Seen {
  const seen: Seen = { mcp: [], model: [], band: [] }
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'band') seen.band.push(e.value as ProjectmanBandState | null)
    return next(e)
  })
  on('mcp.connect', ($, e) => {
    if (opts.connected === false) return { value: { isConnected: false, reason: 'failed', message: 'did not connect' } }
    expect(e.server).toBe('projectman')
    return { value: { isConnected: true, server: SERVER } }
  })
  on('mcp.call', async ($, e) => {
    await opts.onCall?.(e.tool)
    seen.mcp.push({ server: e.server, tool: e.tool, args: e.args })
    if (opts.noStore || e.tool === opts.errorTool) return { value: { content: [{ type: 'text', text: NO_STORE }], isError: true } }
    return { value: { content: [{ type: 'text', text: answers[e.tool] ?? '' }], isError: false } }
  })
  on('model.*', ($, e, next) => {
    seen.model.push(next.event)
    return { deny: 'no model request may be made' }
  })
  // Where the plugin passes, the engine draws its own band: a marker here.
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box key={ENGINE_BAND}>
        <Text>engine</Text>
      </Box>
    )
  })
  on('turn.complete', ($, e) => ({ text: e.answer }))
  return seen
}

function bandProps(bodyColumns = 200, hasSurvey = false) {
  return { hasSurvey, isWorking: false, maxRows: 10, bodyColumns, scroll: { offset: 0, bodyRows: 9 }, view: {} }
}

const SURFACES = ['terminal', 'desktop'] as const

/** Mounts the band and lets the read its first draw scheduled run. */
async function mountBand($: Engine, clock: MockClock, surface: RenderSurface = 'terminal', bodyColumns = 200) {
  const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'AbovePrompt', props: bandProps(bodyColumns) })
  await clock.settle()
  return ui
}

/** The band's lines as drawn: its Box's Texts, in order; none when it is not drawn. */
async function bandText(ui: Awaited<ReturnType<typeof mountBand>>): Promise<string[]> {
  if ((await ui.find({ type: 'Box', key: BAND_KEY })) === undefined) return []
  return (await ui.findAll({ type: 'Text' })).map((t) => t.text ?? '')
}

const tools = (seen: Seen) => seen.mcp.map((c) => c.tool).sort()

// ------------------------------------------------- US-PM-62-1 criterion
//
// "A band above the prompt shows active sprint progress, the in-progress task
// and the NEXT.md note when one exists."

for (const surface of SURFACES) {
  test(`US-PM-62-1 criterion: on ${surface}, the band shows sprint progress, the task in flight and the note`, async ($, on) => {
    const clock = mock.clock(on)
    const seen = engine(on, ANSWERS)
    const ui = await mountBand($, clock, surface)

    expect(await ui.find({ type: 'Box', key: BAND_KEY })).toBeDefined()
    expect(await bandText(ui)).toEqual([FULL_LINE])
    expect(await ui.find({ key: ENGINE_BAND })).toBeUndefined()
    // Four MCP calls, the sprint's progress read only once its id is known; no model request.
    expect(tools(seen)).toEqual(['pm_active', 'pm_get_sprint', 'pm_list_sprints', 'pm_next'])
    expect(seen.mcp.find((c) => c.tool === 'pm_get_sprint')?.args).toEqual({ sprint_id: 'SPRINT-PM-21' })
    expect(seen.mcp.every((c) => c.server === SERVER)).toBe(true)
    expect(seen.model).toEqual([])
    await ui.unmount()
  })
}

test('US-PM-62-1 criterion: with no NEXT.md note the note part is left out', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, { ...ANSWERS, pm_next: NO_NOTE_YAML })
  const ui = await mountBand($, clock)
  expect(await bandText(ui)).toEqual([`${SPRINT_PART} · ${TASK_PART}`])
  expect(await ui.find({ text: 'next:' })).toBeUndefined()
})

test('with no task in progress the task part is left out', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, { ...ANSWERS, pm_active: NO_ACTIVE_YAML })
  const ui = await mountBand($, clock)
  expect(await bandText(ui)).toEqual([`${SPRINT_PART} · ${NOTE_PART}`])
  expect(await ui.find({ text: '▶' })).toBeUndefined()
})

test('more than one task in progress shows the first and how many more', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, { ...ANSWERS, pm_active: ACTIVE_YAML.replace('active_tasks_total: 1', 'active_tasks_total: 3') })
  const ui = await mountBand($, clock)
  expect((await bandText(ui))[0]).toContain(`${TASK_PART} (+2 more)`)
})

// No active sprint: the sprint part is left out and the sprint is not read;
// the task and note still show. With nothing at all to show the band draws nothing.
test('with no active sprint the sprint part is left out and pm_get_sprint is not called', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, { ...ANSWERS, pm_list_sprints: NO_SPRINTS_YAML })
  const ui = await mountBand($, clock)
  expect(await bandText(ui)).toEqual([`${TASK_PART} · ${NOTE_PART}`])
  expect(tools(seen)).toEqual(['pm_active', 'pm_list_sprints', 'pm_next'])
})

test('with no sprint, no task and no note the band draws nothing', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, { pm_list_sprints: NO_SPRINTS_YAML, pm_active: NO_ACTIVE_YAML, pm_next: NO_NOTE_YAML })
  const ui = await mountBand($, clock)
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()
})

// ------------------------------------------------- US-PM-62-3 criterion
//
// "The band hides itself when the directory has no ProjectMan store." Every
// projectman tool answers with an error there; the band draws nothing and the
// engine's own band shows.

for (const surface of SURFACES) {
  test(`US-PM-62-3 criterion: on ${surface}, the band hides itself where the directory has no store`, async ($, on) => {
    const clock = mock.clock(on)
    const seen = engine(on, ANSWERS, { noStore: true })
    const ui = await mountBand($, clock, surface)
    expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
    expect(await ui.find({ text: 'Sprint' })).toBeUndefined()
    expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()
    // Nothing past the first failed read: the sprint is never asked for.
    expect(seen.mcp.some((c) => c.tool === 'pm_get_sprint')).toBe(false)
    expect(seen.model).toEqual([])
  })
}

test('US-PM-62-3 criterion: a band drawn in a store hides once a re-read finds none', async ($, on) => {
  const clock = mock.clock(on)
  const opts: EngineOpts = {}
  engine(on, ANSWERS, opts)
  const ui = await mountBand($, clock)
  expect(await bandText(ui)).toEqual([FULL_LINE])

  opts.noStore = true
  await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 10, isAborted: false, reason: 'answer' })
  await clock.settle()
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()
})

test('an MCP error on any call draws nothing', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, ANSWERS, { errorTool: 'pm_get_sprint' })
  const ui = await mountBand($, clock)
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()
})

test('an unconnected server draws nothing and calls no tool', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, ANSWERS, { connected: false })
  const ui = await mountBand($, clock)
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(seen.mcp).toEqual([])
})

// ------------------------------------------------- reads and layout

test('the band is re-read after each turn, and not before one is drawn', async ($, on) => {
  const clock = mock.clock(on)
  const answers = { ...ANSWERS }
  const seen = engine(on, answers)
  const complete = () => $.turn.complete({ turnId: 't', answer: 'ok', durationMs: 10, isAborted: false, reason: 'answer' })

  // No surface has drawn the band: a turn makes no MCP call.
  expect((await complete()).text).toBe('ok')
  await clock.settle()
  expect(seen.mcp).toEqual([])

  const ui = await mountBand($, clock)
  expect(seen.mcp.length).toBe(4)

  answers.pm_active = NO_ACTIVE_YAML
  answers.pm_next = NO_NOTE_YAML
  expect((await complete()).text).toBe('ok')
  await clock.settle()
  expect(await bandText(ui)).toEqual([SPRINT_PART])
  expect(seen.mcp.length).toBe(8)
  const state = seen.band[seen.band.length - 1]
  expect(state?.reads).toBe(2)
  expect(state?.isReading).toBe(false)
})

test('a band too wide for one line puts the note on a second', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, ANSWERS)
  const ui = await mountBand($, clock, 'terminal', 80)
  expect(await bandText(ui)).toEqual([`${SPRINT_PART} · ${TASK_PART}`, NOTE_PART])
})

test('the band yields to a survey', async ($, on) => {
  const clock = mock.clock(on)
  engine(on, ANSWERS)
  await mountBand($, clock)
  const ui = await $.ui.mount({ plugin: 'projectman', surface: 'terminal', component: 'AbovePrompt', props: bandProps(200, true) })
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()
})

// ------------------------------------------------- the pure parts

test('the note head passes over a dated heading and clips a long line', async () => {
  expect(noteHead(parseYaml(NOTE_YAML))).toBe('Close EPIC-PM-7 once US-PM-62 lands.')
  expect(noteHead({ note: '### 2026-10-21\n\nShip the band.' })).toBe('Ship the band.')
  expect(noteHead({ note: '# Only a heading' })).toBe('Only a heading')
  expect(noteHead(parseYaml(NO_NOTE_YAML))).toBeNull()
  const band = bandFrom(null, null, { note: 'x'.repeat(200) })
  expect(band).not.toBeNull()
  const [line = ''] = bandLines(band!, 500)
  expect(line.length).toBe('next: '.length + 80)
  expect(line.endsWith('…')).toBe(true)
})

test('sprint progress counts done stories against the planned points', async () => {
  expect(sprintProgress(parseYaml(SPRINT_YAML))).toEqual({ name: 'Sprint 20', donePoints: 11, totalPoints: 19 })
  expect(sprintProgress({ id: 'SPRINT-X-1', name: 'Hardening', planned_points: 8, story_progress: [] })).toEqual({
    name: 'Hardening',
    donePoints: 0,
    totalPoints: 8,
  })
  expect(taskInFlight(parseYaml(NO_ACTIVE_YAML))).toBeNull()
  expect(bandFrom(null, parseYaml(NO_ACTIVE_YAML), parseYaml(NO_NOTE_YAML))).toBeNull()
})

// ------------------------------------------------- US-PM-62-2 criterion
//
// "The band updates after pm MCP tool calls that change status." A pm tool
// that writes, under either server prefix, re-reads the band once its call
// answers without error; read-only tools, errors and refusals read nothing.
// The test's tool.call hook beneath the plugin stands for the server's tool:
// it changes what the band's reads answer, as the real write would.

const PREFIXES = ['mcp__plugin_projectman_projectman__', 'mcp__projectman__'] as const

// After US-PM-62-6 is done: no task in flight, its story done (3 more points).
const SPRINT_AFTER_DONE = SPRINT_YAML.replace(
  "title: 'Mod: sprint band above the prompt'\n  status: ready",
  "title: 'Mod: sprint band above the prompt'\n  status: done",
)
const LINE_AFTER_DONE = `Sprint 20 — 14/19 pts · ${NOTE_PART}`

type ToolOpts = {
  /** What the tool answers; by default a plain result. */
  answer?: Record<string, unknown>
  /** Run as the tool writes: changes what the band reads next. */
  write?: () => void
}

/** The engine's MCP tools, beneath the plugin: records each call and answers. */
function pmTools(on: On, opts: ToolOpts = {}): string[] {
  const called: string[] = []
  on('tool.call', { tool: /^mcp__/ }, ($, e) => {
    called.push(e.tool)
    opts.write?.()
    return (opts.answer ?? { result: 'ok', text: 'ok' }) as never
  })
  return called
}

const pmCall = ($: Engine, tool: string, args: Record<string, unknown> = {}) => $.tool.call({ tool, ...args } as never)

/** The status change pm_update / pm_done_next makes when US-PM-62-6 is done. */
const finishTask = (answers: Record<string, string>) => () => {
  answers.pm_active = NO_ACTIVE_YAML
  answers.pm_get_sprint = SPRINT_AFTER_DONE
}

for (const prefix of PREFIXES) {
  test(`US-PM-62-2 criterion: the band updates after ${prefix}pm_update changes a status`, async ($, on) => {
    const clock = mock.clock(on)
    const answers = { ...ANSWERS }
    const seen = engine(on, answers)
    const called = pmTools(on, { write: finishTask(answers) })
    const ui = await mountBand($, clock)
    expect(await bandText(ui)).toEqual([FULL_LINE])
    expect(seen.mcp.length).toBe(4)

    const out = await pmCall($, `${prefix}pm_update`, { id: 'US-PM-62-6', status: 'done' })
    expect(out.result).toBe('ok')
    expect(called).toEqual([`${prefix}pm_update`])
    // The read runs on the timer, after the call has answered.
    expect(seen.mcp.length).toBe(4)

    await clock.settle()
    expect(seen.mcp.length).toBe(8)
    expect(await bandText(ui)).toEqual([LINE_AFTER_DONE])
    expect(seen.model).toEqual([])
  })
}

for (const tool of ['pm_done_next', 'pm_grab', 'pm_accept', 'pm_create_task', 'pm_update_sprint', 'pm_answer_decision']) {
  test(`US-PM-62-2 criterion: ${tool} re-reads the band`, async ($, on) => {
    const clock = mock.clock(on)
    const answers = { ...ANSWERS }
    const seen = engine(on, answers)
    pmTools(on, { write: finishTask(answers) })
    const ui = await mountBand($, clock)
    await pmCall($, `mcp__plugin_projectman_projectman__${tool}`)
    await clock.settle()
    expect(seen.mcp.length).toBe(8)
    expect(await bandText(ui)).toEqual([LINE_AFTER_DONE])
  })
}

test('read-only pm tools, and pm_next reading the note, do not re-read the band', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, ANSWERS)
  const called = pmTools(on)
  await mountBand($, clock)
  for (const prefix of PREFIXES) {
    for (const tool of ['pm_get', 'pm_board', 'pm_status', 'pm_active', 'pm_get_sprint', 'pm_next']) {
      await pmCall($, `${prefix}${tool}`)
    }
  }
  await clock.settle()
  expect(called.length).toBe(12)
  expect(seen.mcp.length).toBe(4)
})

test('pm_next saving or clearing the note re-reads the band', async ($, on) => {
  const clock = mock.clock(on)
  const answers = { ...ANSWERS }
  const seen = engine(on, answers)
  pmTools(on, { write: () => void (answers.pm_next = NO_NOTE_YAML) })
  const ui = await mountBand($, clock)

  await pmCall($, 'mcp__projectman__pm_next', { clear: true })
  await clock.settle()
  expect(seen.mcp.length).toBe(8)
  expect(await bandText(ui)).toEqual([`${SPRINT_PART} · ${TASK_PART}`])

  await pmCall($, 'mcp__plugin_projectman_projectman__pm_next', { text: 'Cut 0.12.0' })
  await clock.settle()
  expect(seen.mcp.length).toBe(12)
})

test('tools of another server never re-read the band', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, ANSWERS)
  const called = pmTools(on)
  await mountBand($, clock)
  await pmCall($, 'mcp__other__pm_update', { id: 'X-1' })
  await pmCall($, 'mcp__plugin_other_projectman__pm_update', { id: 'X-1' })
  await clock.settle()
  expect(called.length).toBe(2)
  expect(seen.mcp.length).toBe(4)
})

test('a burst of pm writes in one turn makes one re-read', async ($, on) => {
  const clock = mock.clock(on)
  const answers = { ...ANSWERS }
  const seen = engine(on, answers)
  pmTools(on, { write: finishTask(answers) })
  const ui = await mountBand($, clock)

  await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6', status: 'review' })
  await pmCall($, 'mcp__projectman__pm_accept', { id: 'US-PM-62-6' })
  await pmCall($, 'mcp__plugin_projectman_projectman__pm_grab', { id: 'US-PM-62-7' })
  await pmCall($, 'mcp__plugin_projectman_projectman__pm_update_many', { updates: [] })
  await clock.settle()

  expect(seen.mcp.length).toBe(8)
  expect(seen.band[seen.band.length - 1]?.reads).toBe(2)
  expect(await bandText(ui)).toEqual([LINE_AFTER_DONE])
})

test('a write landing while a re-read runs makes exactly one more read, which sees it', async ($, on) => {
  const clock = mock.clock(on)
  const answers = { ...ANSWERS }
  // Holds one pm_list_sprints call until released.
  let hold = false
  let isHeld = false
  let release: () => void = () => {}
  const onCall = async (tool: string) => {
    if (hold && tool === 'pm_list_sprints') {
      hold = false
      isHeld = true
      await new Promise<void>((r) => (release = r))
    }
  }
  const seen = engine(on, answers, { onCall })
  pmTools(on)
  const ui = await mountBand($, clock)

  hold = true
  await pmCall($, 'mcp__projectman__pm_grab', { id: 'US-PM-62-6' })
  await clock.settle()
  expect(isHeld).toBe(true)
  // The first re-read is in flight: two more writes arrive, then it finishes.
  finishTask(answers)()
  await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6', status: 'done' })
  await pmCall($, 'mcp__projectman__pm_done_next', { id: 'US-PM-62-6' })
  await clock.settle()
  release()
  await clock.settle()

  expect(seen.mcp.length).toBe(12)
  expect(seen.band[seen.band.length - 1]?.reads).toBe(3)
  expect(await bandText(ui)).toEqual([LINE_AFTER_DONE])
})

test('an errored or refused pm write does not re-read the band', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, ANSWERS)
  const opts: ToolOpts = { answer: { isError: true, result: 'Error: no such item', text: 'Error: no such item' } }
  pmTools(on, opts)
  await mountBand($, clock)

  const errored = await pmCall($, 'mcp__projectman__pm_update', { id: 'US-NOPE-1', status: 'done' })
  expect(errored.isError).toBe(true)
  opts.answer = { deny: 'not allowed' }
  const refused = await pmCall($, 'mcp__plugin_projectman_projectman__pm_grab', { id: 'US-PM-62-6' })
  expect(refused.deny).toBe('not allowed')
  await clock.settle()
  expect(seen.mcp.length).toBe(4)
})

test("a pm call's result passes through unchanged, error or not", async ($, on) => {
  const clock = mock.clock(on)
  engine(on, ANSWERS)
  const answer = { result: { id: 'US-PM-62-6', status: 'done' }, text: 'id: US-PM-62-6\nstatus: done\n', context: ['note'] }
  const opts: ToolOpts = { answer }
  pmTools(on, opts)
  await mountBand($, clock)

  expect(await pmCall($, 'mcp__plugin_projectman_projectman__pm_update', { id: 'US-PM-62-6', status: 'done' })).toEqual(answer)
  expect(await pmCall($, 'mcp__projectman__pm_get', { id: 'US-PM-62-6' })).toEqual(answer)
  const errored = { isError: true, result: 'boom', text: 'boom' }
  opts.answer = errored
  expect(await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6' })).toEqual(errored)
})

test('a failed re-read is swallowed: the result stands, the band hides, later writes still read', async ($, on) => {
  const clock = mock.clock(on)
  let isBroken = false
  const onCall = () => {
    if (isBroken) throw new Error('server went away')
  }
  const seen = engine(on, ANSWERS, { onCall })
  pmTools(on)
  const ui = await mountBand($, clock)
  expect(await bandText(ui)).toEqual([FULL_LINE])

  isBroken = true
  const out = await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6', status: 'done' })
  expect(out.result).toBe('ok')
  await clock.settle()
  expect(await ui.find({ key: BAND_KEY })).toBeUndefined()
  expect(await ui.find({ key: ENGINE_BAND })).toBeDefined()

  isBroken = false
  await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6', status: 'done' })
  await clock.settle()
  expect(await bandText(ui)).toEqual([FULL_LINE])
  expect(seen.mcp.length).toBe(8)
})

test('a pm write before any band is drawn makes no MCP call', async ($, on) => {
  const clock = mock.clock(on)
  const seen = engine(on, ANSWERS)
  const called = pmTools(on)
  await pmCall($, 'mcp__projectman__pm_update', { id: 'US-PM-62-6', status: 'done' })
  await clock.settle()
  expect(called.length).toBe(1)
  expect(seen.mcp).toEqual([])
})

test('the prefixes and the pm_next modes', async () => {
  expect(pmToolName('mcp__projectman__pm_update')).toBe('pm_update')
  expect(pmToolName('mcp__plugin_projectman_projectman__pm_done_next')).toBe('pm_done_next')
  expect(pmToolName('mcp__other__pm_update')).toBeUndefined()
  expect(pmToolName('pm_update')).toBeUndefined()
  expect(movesBand({ tool: 'mcp__projectman__pm_update' })).toBe(true)
  expect(movesBand({ tool: 'mcp__projectman__pm_get' })).toBe(false)
  expect(movesBand({ tool: 'mcp__projectman__pm_next' })).toBe(false)
  expect(movesBand({ tool: 'mcp__projectman__pm_next', text: null })).toBe(false)
  expect(movesBand({ tool: 'mcp__projectman__pm_next', text: 'x' })).toBe(true)
  expect(movesBand({ tool: 'mcp__projectman__pm_next', clear: true })).toBe(true)
  expect([...PM_WRITE_TOOLS].sort()).toEqual([...PM_WRITE_TOOLS])
})
