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
  on('mcp.call', ($, e) => {
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
