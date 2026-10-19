import type { CommandRunInput, On, RenderSurface } from 'claude-code'
import type { ProjectmanBoardView } from '../../types'
import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import {
  boardColumns,
  formatBoard,
  formatCommand,
  formatNext,
  formatStatus,
  parseYaml,
  PM_COMMANDS,
  resultText,
  summarizeBoard,
  summarizeNext,
  summarizeStatus,
} from '../../hooks/pm-views.ts'
import { viewMode, viewModeFor } from '../../hooks/surface.ts'
import { BOARD_OPENED, BOARD_PANE, BOARD_PANE_TITLE, COLUMNS_KEY, columnKey, REFRESH_KEY } from '../../hooks/board-pane.tsx'

// US-PM-60-6: /pm-board, /pm-status-view and /pm-next-task register at
// session start and answer from the projectman MCP server via $.mcp.call,
// with no model request. The test's hooks beneath the plugin stand for the
// engine: they answer mcp.connect / mcp.call from canned server output and
// record any model call or core command run, which must never happen.

const SERVER = 'plugin:projectman:projectman'

// What the projectman server writes (PyYAML, block style), trimmed.
const BOARD_YAML = `board:
  available:
  - id: US-PM-56-12
    title: Clean-machine install from the GitHub marketplace URL with TUI reload
    points: 1
  - id: US-PM-56-4
    title: 'Test: On a machine with no prior setup, installing works'
    points: 2
  not_ready:
  - id: US-PM-60-1
    title: 'Test: Board, status and next commands return their view'
    points: 1
  in_progress:
  - id: US-PM-60-6
    title: Register board, status and next commands that call MCP directly
    points: 3
    assignee: claude
    claim_age: 101
    claimed_by_run: orch-2026-10-20-de86
  in_review: []
  blocked: []
summary:
  available: 5
  not_ready: 68
  in_progress: 1
  in_review: 0
  blocked: 0
stale_tasks: []
stale_after_hours: 2.0
limit: 10
note: 'blocked = a status a human set on the task. not_ready = derived each build.'
`

const STATUS_YAML = `project: ProjectMan
epics: 21
stories: 116
tasks: 918
total_points: 1698
completed_points: 1551
completion: 91%
by_status:
  done: 908
  todo: 73
  in-progress: 1
`

// PyYAML writes a newline inside a single-quoted scalar as a blank line.
const NOTE_YAML = `note: 'Fix the board pane next.

  Then the text fallback, it''s US-PM-60-8.'
`

type Recorded = {
  mcp: { server: string; tool: string; args: Record<string, unknown> }[]
  model: string[]
  core: string[]
  registered: unknown[]
  opened: { id: string; title?: string }[]
  /** Each value the plugin wrote to projectman.board, in order. */
  board: (ProjectmanBoardView | null)[]
}

type EngineOpts = {
  asJson?: boolean
  errorTool?: string
  connected?: boolean
  surfaces?: readonly RenderSurface[]
  surfacesFail?: boolean
  placed?: boolean
  openFails?: boolean
}

// `surfaces` is where the session draws: the terminal by default (the
// drawing path), `[]` for VS Code chat and `claude -p`. `placed: false` is a
// surface that cannot seat the pane now, `openFails` one whose ui.open
// rejects. `answers` and `opts` are read at
// each call, so a test can change what the server answers between reads.
function engine(on: On, answers: Record<string, string>, opts: EngineOpts = {}): Recorded {
  const seen: Recorded = { mcp: [], model: [], core: [], registered: [], opened: [], board: [] }
  on('session.surfaces', () => {
    if (opts.surfacesFail) throw new Error('no surface list')
    return { value: opts.surfaces ?? ['terminal'] }
  })
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'board') seen.board.push(e.value as ProjectmanBoardView | null)
    return next(e)
  })
  on('ui.open', ($, e) => {
    seen.opened.push({ id: e.id, title: e.title })
    if (opts.openFails) throw new Error('no pane host')
    return { value: opts.placed === false ? { isPlaced: false, reason: 'the terminal is 80 columns wide' } : { isPlaced: true } }
  })
  on('command.register', ($, e) => {
    seen.registered.push(e)
    return { value: { command: e.name } }
  })
  on('mcp.connect', ($, e) => {
    if (opts.connected === false) return { value: { isConnected: false, reason: 'failed', message: 'did not connect' } }
    expect(e.server).toBe('projectman')
    return { value: { isConnected: true, server: SERVER } }
  })
  on('mcp.call', ($, e) => {
    seen.mcp.push({ server: e.server, tool: e.tool, args: e.args })
    if (e.tool === opts.errorTool) return { value: { content: [{ type: 'text', text: 'Error: no .project here' }], isError: true } }
    const body = answers[e.tool] ?? ''
    const text = opts.asJson ? JSON.stringify({ result: body }) : body
    return { value: { content: [{ type: 'text', text }], isError: false } }
  })
  // Every model call on `$` (complete, classify, fork and any added later),
  // and the side doors to one: a raw HTTP request or a process (`claude -p`).
  // Each is refused and recorded; the tests require `seen.model` stay empty.
  on('model.*', ($, e, next) => {
    seen.model.push(next.event)
    return { deny: 'no model request may be made' }
  })
  for (const door of ['http.fetch', 'process.run'] as const) {
    on(door, () => {
      seen.model.push(door)
      return { deny: 'no model request may be made' }
    })
  }
  // process.spawn streams, so its hook is an async generator.
  on('process.spawn', async function* () {
    seen.model.push('process.spawn')
    return { deny: 'no model request may be made' }
  })
  on('command.run', ($, e) => {
    seen.core.push(e.command)
    return { text: 'core ran' }
  })
  return seen
}

// command.run as the engine raises it for a person's Enter.
function run(command: string): CommandRunInput {
  return { command, args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } } as CommandRunInput
}

const ANSWERS = { pm_board: BOARD_YAML, pm_status: STATUS_YAML, pm_next: NOTE_YAML }

test('session start registers the three commands, runnable mid-turn', async ($, on) => {
  const seen = engine(on, ANSWERS)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/work/proj', surface: 'terminal', isInteractive: true })

  expect(seen.registered).toEqual([
    expect.objectContaining({ name: 'pm-board', immediate: true }),
    expect.objectContaining({ name: 'pm-status-view', immediate: true }),
    expect.objectContaining({ name: 'pm-next-task', immediate: true }),
  ])
})

test('every command in PM_COMMANDS is answered by the plugin, not core', async ($, on) => {
  const seen = engine(on, ANSWERS)
  expect(PM_COMMANDS.map((c) => c.name)).toEqual(['pm-board', 'pm-status-view', 'pm-next-task'])
  for (const command of PM_COMMANDS) await $.command.run(run(command.name))
  expect(seen.core).toEqual([])
  expect(seen.model).toEqual([])
  // Another command passes through to core untouched.
  const other = await $.command.run(run('compact'))
  expect(other.text).toBe('core ran')
  expect(seen.core).toEqual(['compact'])
})

test('command names do not clash with the plugin skills', async () => {
  // skills/ holds pm, pm-autoscope, pm-cleanup, pm-do, pm-next, pm-orchestrate, pm-plan, pm-status.
  const skills = ['pm', 'pm-autoscope', 'pm-cleanup', 'pm-do', 'pm-next', 'pm-orchestrate', 'pm-plan', 'pm-status']
  for (const command of PM_COMMANDS) expect(skills.includes(command.name)).toBe(false)
})

// The full board as text: what /pm-board answers where a pane cannot be seated.
test('/pm-board calls pm_board on the MCP server and formats the board, no model request', async ($, on) => {
  const seen = engine(on, ANSWERS, { placed: false })
  const ran = await $.command.run(run('pm-board'))

  expect(seen.mcp).toEqual([{ server: SERVER, tool: 'pm_board', args: { brief: true, limit: 10 } }])
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
  expect(ran.text).toContain('ProjectMan board: 1 in progress · 0 in review · 0 blocked · 5 available · 68 not ready')
  expect(ran.text).toContain('  US-PM-60-6  Register board, status and next commands that call MCP directly [3 pts] @claude')
  expect(ran.text).toContain('  US-PM-56-4  Test: On a machine with no prior setup, installing works [2 pts]')
  expect(ran.text).toContain('  … and 3 more')
  expect(ran.context).toBeUndefined()
})

test('/pm-status-view calls pm_status and formats the summary, no model request', async ($, on) => {
  const seen = engine(on, ANSWERS)
  const ran = await $.command.run(run('pm-status-view'))

  expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_status'])
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
  expect(ran.text).toBe(
    'ProjectMan: 91% complete (1551/1698 pts)\n' +
      '21 epics · 116 stories · 918 tasks\n' +
      'By status: done 908 · todo 73 · in-progress 1',
  )
})

test('/pm-next-task reads the board and the saved note, no model request', async ($, on) => {
  const seen = engine(on, ANSWERS)
  const ran = await $.command.run(run('pm-next-task'))

  expect(seen.mcp).toEqual([
    { server: SERVER, tool: 'pm_board', args: { brief: true, limit: 3 } },
    { server: SERVER, tool: 'pm_next', args: {} },
  ])
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
  expect(ran.text).toContain('Next task: US-PM-56-12  Clean-machine install from the GitHub marketplace URL with TUI reload [1 pt]')
  expect(ran.text).toContain("Note for the next session:\nFix the board pane next.\nThen the text fallback, it's US-PM-60-8.")
})

test('a JSON-wrapped {"result": ...} answer is unwrapped the same', async ($, on) => {
  engine(on, ANSWERS, { asJson: true })
  const ran = await $.command.run(run('pm-status-view'))
  expect(ran.text).toContain('ProjectMan: 91% complete')
})

test('an MCP error is reported as text, not thrown', async ($, on) => {
  const seen = engine(on, ANSWERS, { errorTool: 'pm_status' })
  const ran = await $.command.run(run('pm-status-view'))
  expect(ran.text).toBe('ProjectMan: pm_status failed: Error: no .project here')
  expect(seen.model).toEqual([])
})

test('an unconnected server is reported as text and no tool is called', async ($, on) => {
  const seen = engine(on, ANSWERS, { connected: false })
  const ran = await $.command.run(run('pm-board'))
  expect(ran.text).toContain('not connected')
  expect(seen.mcp).toEqual([])
})

test('parseYaml reads the server subset', async () => {
  expect(parseYaml(STATUS_YAML)).toEqual({
    project: 'ProjectMan',
    epics: 21,
    stories: 116,
    tasks: 918,
    total_points: 1698,
    completed_points: 1551,
    completion: '91%',
    by_status: { done: 908, todo: 73, 'in-progress': 1 },
  })
  const board = parseYaml(BOARD_YAML) as { board: { in_review: unknown; available: unknown[] }; stale_after_hours: unknown }
  expect(board.board.in_review).toEqual([])
  expect(board.board.available.length).toBe(2)
  expect(board.stale_after_hours).toBe(2)
  expect(parseYaml('note: null\nmessage: no note saved\n')).toEqual({ note: null, message: 'no note saved' })
  expect(parseYaml('a: "x\\ty"\nb: |-\n  one\n  two\nc: ~\n')).toEqual({ a: 'x\ty', b: 'one\ntwo', c: null })
  expect(parseYaml('- - 1\n  - 2\n- k: v\n')).toEqual([[1, 2], { k: 'v' }])
})

test('formatters cope with empty answers', async () => {
  expect(formatNext(parseYaml('board:\n  available: []\n'), parseYaml('note: null\nmessage: no note saved\n'))).toBe(
    'Next task: none ready. Run /pm-board to see what is in flight or not ready.\n\nNo next-session note saved.',
  )
  expect(formatBoard(null)).toBe('ProjectMan board: 0 in progress · 0 in review · 0 blocked · 0 available · 0 not ready')
  expect(formatStatus(null)).toContain('Project: ? complete')
  expect(resultText({ content: [], isError: false, structuredContent: { result: 'x: 1' } })).toBe('x: 1')
})

// US-PM-60-8: where nothing draws (VS Code chat, `claude -p`: no surface
// attached) each command answers with a compact text summary; where a
// surface draws, the drawing path is taken (a stub returning the full view
// until US-PM-60-7 opens a pane).

const BOARD_SUMMARY =
  'ProjectMan board: 1 in progress · 0 in review · 0 blocked · 5 available · 68 not ready\n' +
  'In progress: US-PM-60-6\n' +
  'Available: US-PM-56-12, US-PM-56-4 (+3 more)'
const STATUS_SUMMARY = 'ProjectMan: 91% complete (1551/1698 pts) · 21 epics · 116 stories · 918 tasks'
const NEXT_SUMMARY =
  'Next task: US-PM-56-12  Clean-machine install from the GitHub marketplace URL with TUI reload [1 pt]\n' +
  'Note: Fix the board pane next. …'

function parsedAnswers(command: (typeof PM_COMMANDS)[number]) {
  return command.calls.map((c) => parseYaml(ANSWERS[c.tool as keyof typeof ANSWERS]))
}

test('the capability check: any attached surface draws, none means text', async () => {
  expect(viewModeFor([])).toBe('text')
  for (const surface of ['terminal', 'desktop', 'mobile', 'vscode'] as const) expect(viewModeFor([surface])).toBe('pane')
  expect(viewModeFor(['terminal', 'mobile'])).toBe('pane')
  expect(await viewMode({ session: { surfaces: async () => [] } })).toBe('text')
  expect(await viewMode({ session: { surfaces: async () => ['desktop'] } })).toBe('pane')
  expect(await viewMode({ session: { surfaces: () => Promise.reject(new Error('gone')) } })).toBe('text')
})

test('with no surface attached, /pm-board answers with a compact summary', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: [] })
  const ran = await $.command.run(run('pm-board'))
  expect(ran.text).toBe(BOARD_SUMMARY)
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
})

test('with no surface attached, /pm-status-view answers with a one-line summary', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: [] })
  const ran = await $.command.run(run('pm-status-view'))
  expect(ran.text).toBe(STATUS_SUMMARY)
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
})

test('with no surface attached, /pm-next-task answers with the task and the note head', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: [] })
  const ran = await $.command.run(run('pm-next-task'))
  expect(ran.text).toBe(NEXT_SUMMARY)
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
})

test('a surface list that cannot be read falls back to the text summary', async ($, on) => {
  engine(on, ANSWERS, { surfacesFail: true })
  const ran = await $.command.run(run('pm-status-view'))
  expect(ran.text).toBe(STATUS_SUMMARY)
})

test('the compact summaries are shorter than the full views', async ($, on) => {
  engine(on, ANSWERS, { surfaces: [] })
  for (const command of PM_COMMANDS) {
    const ran = await $.command.run(run(command.name))
    expect((ran.text ?? '').length).toBeLessThan(formatCommand(command, parsedAnswers(command)).length)
    expect((ran.text ?? '').split('\n').length).toBeLessThanOrEqual(4)
  }
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`on the ${surface} surface each command takes the drawing path, not the summary`, async ($, on) => {
    engine(on, ANSWERS, { surfaces: [surface] })
    for (const command of PM_COMMANDS) {
      const ran = await $.command.run(run(command.name))
      // The board opens as a pane (US-PM-60-7); status and next answer with the full view.
      if (command.name === 'pm-board') expect(ran.text).toBe(BOARD_OPENED)
      else expect(ran.text).toBe(formatCommand(command, parsedAnswers(command)))
      expect([BOARD_SUMMARY, STATUS_SUMMARY, NEXT_SUMMARY]).not.toContain(ran.text)
    }
  })
}

test('compact summaries cope with empty answers', async () => {
  expect(summarizeBoard(null)).toBe('ProjectMan board: 0 in progress · 0 in review · 0 blocked · 0 available · 0 not ready')
  expect(summarizeStatus(null)).toBe('Project: ? complete (0/0 pts) · 0 epics · 0 stories · 0 tasks')
  expect(summarizeNext(parseYaml('board:\n  available: []\n'), parseYaml('note: null\n'))).toBe(
    'Next task: none ready.\nNo next-session note saved.',
  )
  expect(summarizeNext(null, parseYaml(`note: '${'x'.repeat(200)}'\n`)).split('\n')[1]?.length).toBe(100)
  expect(summarizeBoard(parseYaml('board:\n  blocked:\n  - id: T-1\nstale_tasks:\n- T-1\n'))).toBe(
    'ProjectMan board: 0 in progress · 0 in review · 1 blocked · 0 available · 0 not ready\nBlocked: T-1\nStale claims: T-1',
  )
})

// ---------------------------------------------------------------- board pane
//
// US-PM-60-7: on a drawing surface /pm-board writes the board to
// projectman.board and opens it as a pane; the pane draws available / in
// progress / blocked columns and its refresh button re-calls pm_board. Each
// test body runs on the terminal and the desktop surface.

// The board after work moved: US-PM-60-6 done, US-PM-60-7 picked up, one blocked.
const BOARD_YAML_REFRESHED = `board:
  available:
  - id: US-PM-56-4
    title: 'Test: On a machine with no prior setup, installing works'
    points: 2
  in_progress:
  - id: US-PM-60-7
    title: Draw the board as a pane with a refresh button
    points: 3
    assignee: claude
  blocked:
  - id: US-PM-56-12
    title: Clean-machine install from the GitHub marketplace URL with TUI reload
    points: 1
summary:
  available: 4
  in_progress: 1
  blocked: 1
stale_tasks: []
`

// The Pane props a surface hands the hook: docked, `bodyColumns` wide.
function paneProps(bodyColumns = 120) {
  return { title: BOARD_PANE_TITLE, isFocused: false, bodyColumns, placement: 'dock' as const, scroll: { offset: 0, bodyRows: 30 }, view: {} }
}

const PANE_SURFACES = ['terminal', 'desktop'] as const

for (const surface of PANE_SURFACES) {
  test(`on ${surface}, /pm-board opens the pane with available / in progress / blocked columns`, async ($, on) => {
    const seen = engine(on, ANSWERS, { surfaces: [surface] })
    const ran = await $.command.run(run('pm-board'))
    expect(ran.text).toBe(BOARD_OPENED)
    expect(seen.opened).toEqual([{ id: BOARD_PANE, title: BOARD_PANE_TITLE }])

    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    for (const key of ['available', 'in_progress', 'blocked'] as const) {
      expect(await ui.find({ type: 'Box', key: columnKey(key) })).toBeDefined()
    }
    expect(await ui.find({ key: 'col-not_ready' })).toBeUndefined()
    expect((await ui.find({ key: COLUMNS_KEY }))?.props.flexDirection).toBe('row')
    expect(await ui.find({ type: 'Text', text: 'Available (5)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'In progress (1)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Blocked (0)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'US-PM-56-12  Clean-machine install' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-6  Register board, status and next commands that call MCP directly [3] @claude' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '… and 3 more' })).toBeDefined()
    // Not-ready tasks are not on the pane.
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-1' })).toBeUndefined()
    expect((await ui.find({ type: 'Button', key: REFRESH_KEY }))?.text).toBe('Refresh')
    expect(seen.model).toEqual([])
    await ui.unmount()
  })

  test(`on ${surface}, the refresh button re-calls pm_board and redraws the pane from $.state`, async ($, on) => {
    const answers: Record<string, string> = { ...ANSWERS }
    const seen = engine(on, answers, { surfaces: [surface] })
    await $.command.run(run('pm-board'))
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    expect(await ui.find({ type: 'Text', text: 'Blocked (0)' })).toBeDefined()

    answers.pm_board = BOARD_YAML_REFRESHED
    await ui.press({ key: REFRESH_KEY })

    expect(seen.mcp).toEqual([
      { server: SERVER, tool: 'pm_board', args: { brief: true, limit: 10 } },
      { server: SERVER, tool: 'pm_board', args: { brief: true, limit: 10 } },
    ])
    expect(seen.model).toEqual([])
    expect(await ui.find({ type: 'Text', text: 'Blocked (1)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Available (4)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-7  Draw the board as a pane' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-6' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: 'Read 2 times this session.' })).toBeDefined()
    // The command's write, then the refresh: in flight, then the new read.
    expect(seen.board.map((v) => [v?.loads, v?.isRefreshing])).toEqual([
      [1, false],
      [1, true],
      [2, false],
    ])
    expect(seen.board.at(-1)?.columns.map((c) => c.total)).toEqual([4, 1, 1])
    await ui.unmount()
  })

  test(`on ${surface}, a failed refresh keeps the columns and shows why`, async ($, on) => {
    const opts: { errorTool?: string; surfaces: RenderSurface[] } = { surfaces: [surface] }
    const seen = engine(on, ANSWERS, opts)
    await $.command.run(run('pm-board'))
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })

    opts.errorTool = 'pm_board'
    await ui.press({ key: REFRESH_KEY })

    expect(await ui.find({ type: 'Text', text: 'ProjectMan: pm_board failed: Error: no .project here' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Available (5)' })).toBeDefined()
    expect(seen.board.at(-1)).toMatchObject({ loads: 1, isRefreshing: false, error: 'ProjectMan: pm_board failed: Error: no .project here' })
    await ui.unmount()
  })

  test(`on ${surface}, a pane drawn before any read offers the refresh, which loads it`, async ($, on) => {
    const seen = engine(on, ANSWERS, { surfaces: [surface] })
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    expect(await ui.find({ type: 'Text', text: 'Press Refresh' })).toBeDefined()
    expect(await ui.find({ key: columnKey('available') })).toBeUndefined()

    await ui.press({ key: REFRESH_KEY })

    expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board'])
    expect(await ui.find({ type: 'Text', text: 'Press Refresh' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: 'In progress (1)' })).toBeDefined()
    await ui.unmount()
  })

  test(`on ${surface}, a narrow pane stacks the columns`, async ($, on) => {
    engine(on, ANSWERS, { surfaces: [surface] })
    await $.command.run(run('pm-board'))
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps(50) })
    expect((await ui.find({ key: COLUMNS_KEY }))?.props.flexDirection).toBe('column')
    expect(await ui.find({ type: 'Text', text: 'Blocked (0)' })).toBeDefined()
    await ui.unmount()
  })
}

test('a pane the surface cannot seat leaves /pm-board answering with the full board', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: ['terminal'], placed: false })
  const ran = await $.command.run(run('pm-board'))
  expect(seen.opened).toEqual([{ id: BOARD_PANE, title: BOARD_PANE_TITLE }])
  expect(ran.text).toBe(formatBoard(parseYaml(BOARD_YAML)))
})

test('the text path opens no pane', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: [] })
  const ran = await $.command.run(run('pm-board'))
  expect(seen.opened).toEqual([])
  expect(ran.text).toBe(BOARD_SUMMARY)
})

test('boardColumns reads available / in progress / blocked from pm_board', async () => {
  expect(boardColumns(null).map((c) => [c.key, c.total, c.tasks.length])).toEqual([
    ['available', 0, 0],
    ['in_progress', 0, 0],
    ['blocked', 0, 0],
  ])
  const [available, inProgress] = boardColumns(parseYaml(BOARD_YAML))
  expect(available?.total).toBe(5)
  expect(available?.tasks[0]).toEqual({ id: 'US-PM-56-12', title: 'Clean-machine install from the GitHub marketplace URL with TUI reload', points: 1, assignee: null, isStale: false })
  expect(inProgress?.tasks[0]?.assignee).toBe('claude')
  expect(boardColumns(parseYaml('board:\n  in_progress:\n  - id: T-1\nstale_tasks:\n- T-1\n'))[1]?.tasks[0]?.isStale).toBe(true)
})

// ------------------------------------------------- US-PM-60 criterion
//
// "Board, status and next commands return their view with no model request
// made." Each command on each path (text: no surface; drawing: terminal and
// desktop, the board's refresh included) returns its view, answered from the
// MCP server alone: no model call, no HTTP or process side door, no core
// command, and no hidden `context` handed to the model.

// The host refuses any `$` call a hooks module's source scan does not list,
// and `claude plugin validate .` lists register.ts's calls: mcp, session,
// state, ui, fs.stat, command.register, nothing on model, http or process.
// So a model call is refused before it is made; the hook below, whose module
// lists none, shows the rule, and the stand-ins above record anything that
// would get past it.
test('US-PM-60 guard: a model call the module does not list is refused before any request', async ($, on) => {
  const errs: string[] = []
  on('session.start', async ($, e) => {
    await $.model.classify('x', ['a', 'b']).catch((x) => errs.push(String(x)))
    await $.model.complete({ model: 'any', prompt: 'x' }).catch((x) => errs.push(String(x)))
    return { cwd: e.cwd }
  })
  const seen = engine(on, ANSWERS)
  await $.session.start({ cwd: '/work/proj', surface: 'terminal', isInteractive: true })
  expect(errs.length).toBe(2)
  for (const err of errs) expect(err).toContain('refused')
  expect(seen.model).toEqual([])
})

const VIEW_PATHS = [
  { path: 'text', surfaces: [] as RenderSurface[] },
  { path: 'terminal', surfaces: ['terminal'] as RenderSurface[] },
  { path: 'desktop', surfaces: ['desktop'] as RenderSurface[] },
] as const

function expectedView(name: string, path: string): string {
  const command = PM_COMMANDS.find((c) => c.name === name)!
  if (path === 'text') return { 'pm-board': BOARD_SUMMARY, 'pm-status-view': STATUS_SUMMARY, 'pm-next-task': NEXT_SUMMARY }[name]!
  if (name === 'pm-board') return BOARD_OPENED
  return formatCommand(command, parsedAnswers(command))
}

for (const { path, surfaces } of VIEW_PATHS) {
  for (const name of ['pm-board', 'pm-status-view', 'pm-next-task'] as const) {
    test(`US-PM-60 criterion: /${name} on the ${path} path returns its view with no model request`, async ($, on) => {
      const seen = engine(on, ANSWERS, { surfaces })
      const ran = await $.command.run(run(name))

      expect(ran.text).toBe(expectedView(name, path))
      expect(ran.context).toBeUndefined()
      expect(seen.mcp.length).toBeGreaterThan(0)
      expect(seen.mcp.every((c) => c.server === SERVER)).toBe(true)
      expect(seen.model).toEqual([])
      expect(seen.core).toEqual([])
      // Only the drawing path opens the board pane, and only for /pm-board.
      expect(seen.opened.length).toBe(path !== 'text' && name === 'pm-board' ? 1 : 0)
    })
  }
}

for (const surface of PANE_SURFACES) {
  test(`US-PM-60 criterion: on ${surface}, the board pane draws and refreshes with no model request`, async ($, on) => {
    const answers: Record<string, string> = { ...ANSWERS }
    const seen = engine(on, answers, { surfaces: [surface] })
    const ran = await $.command.run(run('pm-board'))
    expect(ran.text).toBe(BOARD_OPENED)

    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    expect(await ui.find({ type: 'Text', text: 'Available (5)' })).toBeDefined()
    expect(seen.model).toEqual([])

    answers.pm_board = BOARD_YAML_REFRESHED
    await ui.press({ key: REFRESH_KEY })
    expect(await ui.find({ type: 'Text', text: 'Available (4)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Blocked (1)' })).toBeDefined()

    // A third read, on an empty answer, stays off the model too.
    answers.pm_board = ''
    await ui.press({ key: REFRESH_KEY })
    expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board', 'pm_board', 'pm_board'])
    expect(seen.model).toEqual([])
    expect(seen.core).toEqual([])
    await ui.unmount()
  })
}

// ------------------------------- US-PM-60 criterion: board pane (US-PM-60-2)
//
// "The board opens as a pane in the terminal and the Desktop Code tab and
// refreshes on demand." On each surface: /pm-board opens the pane and the
// surface places it; the pane draws exactly the available / in progress /
// blocked columns from a fixture pm_board answer; Refresh, pressed as its
// button and as its `r` hotkey, re-calls pm_board and the pane shows the
// changed board; and refresh after refresh keeps working. The harness
// presses a Button by key, as a click or its hotkey does, so the hotkey is
// held to the one Button armed with `r` and pressed through the engine's
// `$.ui.press` on that surface.

// A third board: everything moved to in progress.
const BOARD_YAML_THIRD = `board:
  available: []
  in_progress:
  - id: US-PM-60-2
    title: 'Test: The board opens as a pane and refreshes on demand'
    points: 1
    assignee: claude
  - id: US-PM-56-4
    title: 'Test: On a machine with no prior setup, installing works'
    points: 2
  blocked: []
summary:
  available: 0
  in_progress: 2
  blocked: 0
stale_tasks: []
`

// What each fixture answer draws: each column's heading, and a task line it shows.
const BOARDS = [
  { yaml: BOARD_YAML, headings: ['Available (5)', 'In progress (1)', 'Blocked (0)'], shows: 'US-PM-60-6  Register board' },
  { yaml: BOARD_YAML_REFRESHED, headings: ['Available (4)', 'In progress (1)', 'Blocked (1)'], shows: 'US-PM-60-7  Draw the board as a pane' },
  { yaml: BOARD_YAML_THIRD, headings: ['Available (0)', 'In progress (2)', 'Blocked (0)'], shows: 'US-PM-60-2  Test: The board opens' },
] as const

const COLUMN_KEYS = (['available', 'in_progress', 'blocked'] as const).map(columnKey)

for (const surface of PANE_SURFACES) {
  test(`US-PM-60 criterion: on ${surface}, the board opens as a pane and refreshes on demand`, async ($, on) => {
    const answers: Record<string, string> = { ...ANSWERS }
    const seen = engine(on, answers, { surfaces: [surface] })

    // /pm-board opens the pane and the surface seats it ({ isPlaced: true });
    // the command answers BOARD_OPENED only for a placed pane (a pane not
    // placed answers the board as text, held below under "not placed").
    const ran = await $.command.run(run('pm-board'))
    expect(ran.text).toBe(BOARD_OPENED)
    expect(seen.opened).toEqual([{ id: BOARD_PANE, title: BOARD_PANE_TITLE }])

    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    // Exactly the three columns, in order, under the columns row.
    const drawn = async () => (await ui.findAll({ type: 'Box' })).map((b) => b.key).filter((k) => k?.startsWith('col-'))
    const shows = async (i: number) => {
      const board = BOARDS[i]!
      for (const heading of board.headings) expect(await ui.find({ type: 'Text', text: heading })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: board.shows })).toBeDefined()
      expect(await drawn()).toEqual(COLUMN_KEYS)
    }
    expect(await ui.find({ key: COLUMNS_KEY })).toBeDefined()
    await shows(0)

    // The refresh is one Button, keyed `refresh` and armed with hotkey `r`.
    const buttons = await ui.findAll({ type: 'Button' })
    const armed = buttons.filter((b) => b.props.hotkey === 'r')
    expect(armed.map((b) => b.key)).toEqual([REFRESH_KEY])
    expect(armed[0]?.text).toBe('Refresh')

    // The button: pm_board re-called, the changed board drawn.
    answers.pm_board = BOARD_YAML_REFRESHED
    await ui.press({ key: REFRESH_KEY })
    expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board', 'pm_board'])
    await shows(1)
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-6' })).toBeUndefined()

    // The hotkey `r`: the engine pressing the Button it arms, on this surface.
    answers.pm_board = BOARD_YAML_THIRD
    await $.ui.press({ plugin: 'projectman', key: armed[0]!.key!, surface })
    expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board', 'pm_board', 'pm_board'])
    await shows(2)
    expect(await ui.find({ type: 'Text', text: 'US-PM-60-7' })).toBeUndefined()

    // Refresh after refresh keeps working: each press one read, each read drawn.
    for (let n = 0; n < 6; n++) {
      const i = n % BOARDS.length
      answers.pm_board = BOARDS[i]!.yaml
      if (n % 2 === 0) await ui.press({ key: REFRESH_KEY })
      else await $.ui.press({ plugin: 'projectman', key: REFRESH_KEY, surface })
      expect(seen.mcp.length).toBe(4 + n)
      await shows(i)
      expect(await ui.find({ type: 'Text', text: `Read ${4 + n} times this session.` })).toBeDefined()
      expect((await ui.find({ type: 'Button', key: REFRESH_KEY }))?.text).toBe('Refresh')
    }
    expect(seen.mcp.every((c) => c.server === SERVER && c.tool === 'pm_board')).toBe(true)
    expect(seen.board.at(-1)).toMatchObject({ loads: 9, isRefreshing: false, error: null })
    expect(seen.opened.length).toBe(1)
    expect(seen.model).toEqual([])
    expect(seen.core).toEqual([])
    await ui.unmount()
  })
}

// ----------------------- US-PM-60 criterion: both surfaces (US-PM-60-5)
//
// "UI tests mount the pane on both the terminal and desktop surfaces." One
// test mounts the board pane through the harness's `$.ui.mount` on each of
// PANE_SURFACES in turn, holds each drawing to its surface and to the pane's
// tree (the three columns, in order, and the Refresh button), and requires
// the surfaces mounted be exactly terminal and desktop, so dropping either
// from PANE_SURFACES (which every pane test above loops over) fails here.

test('US-PM-60 criterion: UI tests mount the pane on both the terminal and desktop surfaces', async ($, on) => {
  const seen = engine(on, ANSWERS, { surfaces: [...PANE_SURFACES] })
  expect((await $.command.run(run('pm-board'))).text).toBe(BOARD_OPENED)

  const mounted: RenderSurface[] = []
  for (const surface of PANE_SURFACES) {
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    expect(ui.surface).toBe(surface)
    expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'pm-board' } })
    const columns = (await ui.findAll({ type: 'Box' })).map((b) => b.key).filter((k) => k?.startsWith('col-'))
    expect(columns).toEqual(COLUMN_KEYS)
    for (const heading of BOARDS[0].headings) expect(await ui.find({ type: 'Text', text: heading })).toBeDefined()
    const refresh = await ui.find({ type: 'Button', key: REFRESH_KEY })
    expect(refresh?.text).toBe('Refresh')
    mounted.push(ui.surface)
    await ui.unmount()
  }

  expect([...new Set(mounted)].sort()).toEqual(['desktop', 'terminal'])
  expect(mounted.length).toBe(2)
  expect(seen.model).toEqual([])
  expect(seen.core).toEqual([])
})

// ------------------------------------------- US-PM-60 criterion: mid-turn
//
// "Commands work while a Claude turn is in progress." The commands register
// `immediate`, so the engine runs `/pm-board` typed over a streaming turn at
// once instead of queueing it for the turn's end. Each test holds a main-loop
// turn in flight (its `turn.start` raised, its first model step streaming and
// parked on a gate beneath, as a response still arriving is) and runs the
// command or presses the pane's refresh over it: the view comes back while
// the step is still unsettled, from the MCP server alone, and the turn then
// finishes as it would have, its answer untouched.

const TURN_ID = 'turn-mid'
const TURN_TEXT = 'Working through the refactor…'

type InFlight = {
  /** What happened on the turn, in order. */
  log: string[]
  /** True once the parked step has streamed its end. */
  isSettled: () => boolean
  /** Lets the parked step finish, reads it to its end and completes the turn. */
  finish: () => Promise<{ answer: string; stopReason: unknown }>
}

type TurnHooks = { log: string[]; open: () => void }

// The engine's side of a turn, beneath the plugin (registered before the
// test's first `$` call): `turn.start` answered, and one `turn.step` that
// streams a first piece and then waits on a gate.
function turnHooks(on: On): TurnHooks {
  const log: string[] = []
  let open!: () => void
  const gate = new Promise<void>((resolve) => (open = resolve))
  on('turn.start', ($, e) => {
    log.push('turn.start')
    return { turnId: e.turnId }
  })
  on('turn.step', async function* ($, e) {
    log.push('step.streaming')
    yield { kind: 'text', index: 0, text: TURN_TEXT }
    await gate
    log.push('step.end')
    yield { kind: 'stop', stopReason: 'end_turn', usage: null }
    return { turnId: e.turnId, index: e.index, answer: TURN_TEXT, toolUses: [], stopReason: 'end_turn', usage: null }
  })
  on('turn.complete', ($, e) => {
    log.push(`turn.complete ${e.reason}`)
    return { text: e.answer }
  })
  return { log, open }
}

// Starts the main-loop turn and leaves its first step streaming, parked on the gate.
async function turnInFlight($: Engine, { log, open }: TurnHooks): Promise<InFlight> {
  expect(await $.turn.start({ text: 'refactor the parser', turnId: TURN_ID })).toEqual({ turnId: TURN_ID })
  const step = $.turn.step({ turnId: TURN_ID, index: 0, model: 'claude-opus', messageCount: 1 })
  const first = await step.next()
  expect(first.value).toMatchObject({ kind: 'text', text: TURN_TEXT })
  // Pull the next piece: it waits on the gate, so the step stays in flight.
  let settled = false
  const rest = step.next().then((r) => {
    settled = true
    return r
  })
  return {
    log,
    isSettled: () => settled,
    finish: async () => {
      open()
      let piece = await rest
      while (!piece.done) piece = await step.next()
      const result = piece.value
      await $.turn.complete({ turnId: TURN_ID, answer: result.answer, durationMs: 1200, isAborted: false, reason: 'answer' })
      return { answer: result.answer, stopReason: result.stopReason }
    },
  }
}

const TURN_DONE = ['turn.start', 'step.streaming', 'step.end', 'turn.complete answer']

for (const { path, surfaces } of VIEW_PATHS) {
  for (const name of ['pm-board', 'pm-status-view', 'pm-next-task'] as const) {
    test(`US-PM-60 criterion: /${name} on the ${path} path works mid-turn`, async ($, on) => {
      const seen = engine(on, ANSWERS, { surfaces })
      const hooks = turnHooks(on)
      on('session.start', ($, e) => ({ cwd: e.cwd }))
      await $.session.start({ cwd: '/work/proj', surface: 'terminal', isInteractive: true })
      // Declared immediate: typed mid-turn, the engine runs it at once.
      expect(seen.registered).toContainEqual(expect.objectContaining({ name, immediate: true }))

      const turn = await turnInFlight($, hooks)
      const ran = await $.command.run(run(name))

      // The view is back while the turn's step is still streaming.
      expect(turn.isSettled()).toBe(false)
      expect(turn.log).toEqual(['turn.start', 'step.streaming'])
      expect(ran.text).toBe(expectedView(name, path))
      expect(ran.context).toBeUndefined()
      expect(seen.mcp.length).toBeGreaterThan(0)
      expect(seen.model).toEqual([])
      expect(seen.core).toEqual([])

      // The turn then ends as it would have; the command did not touch it.
      expect(await turn.finish()).toEqual({ answer: TURN_TEXT, stopReason: 'end_turn' })
      expect(turn.log).toEqual(TURN_DONE)
    })
  }
}

test('US-PM-60 criterion: all three commands run back to back over one in-flight turn', async ($, on) => {
  const seen = engine(on, ANSWERS)
  const turn = await turnInFlight($, turnHooks(on))
  for (const name of ['pm-board', 'pm-status-view', 'pm-next-task'] as const) {
    const ran = await $.command.run(run(name))
    expect(ran.text).toBe(expectedView(name, 'terminal'))
    expect(turn.isSettled()).toBe(false)
  }
  expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board', 'pm_status', 'pm_board', 'pm_next'])
  expect(seen.model).toEqual([])
  expect((await turn.finish()).answer).toBe(TURN_TEXT)
  expect(turn.log).toEqual(TURN_DONE)
})

for (const surface of PANE_SURFACES) {
  test(`US-PM-60 criterion: on ${surface}, the board pane's refresh works mid-turn`, async ($, on) => {
    const answers: Record<string, string> = { ...ANSWERS }
    const seen = engine(on, answers, { surfaces: [surface] })
    const hooks = turnHooks(on)
    expect((await $.command.run(run('pm-board'))).text).toBe(BOARD_OPENED)
    const ui = await $.ui.mount({ plugin: 'projectman', surface, component: 'Pane', requestId: BOARD_PANE, props: paneProps() })
    expect(await ui.find({ type: 'Text', text: 'Blocked (0)' })).toBeDefined()

    const turn = await turnInFlight($, hooks)
    answers.pm_board = BOARD_YAML_REFRESHED
    await ui.press({ key: REFRESH_KEY })

    // Redrawn from the new read while the turn's step is still streaming.
    expect(turn.isSettled()).toBe(false)
    expect(turn.log).toEqual(['turn.start', 'step.streaming'])
    expect(seen.mcp.map((c) => c.tool)).toEqual(['pm_board', 'pm_board'])
    expect(await ui.find({ type: 'Text', text: 'Blocked (1)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Available (4)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Read 2 times this session.' })).toBeDefined()
    expect((await ui.find({ type: 'Button', key: REFRESH_KEY }))?.text).toBe('Refresh')
    expect(seen.model).toEqual([])
    expect(seen.core).toEqual([])

    expect(await turn.finish()).toEqual({ answer: TURN_TEXT, stopReason: 'end_turn' })
    expect(turn.log).toEqual(TURN_DONE)
    // The pane outlives the turn, as the refresh left it.
    expect(await ui.find({ type: 'Text', text: 'Blocked (1)' })).toBeDefined()
    await ui.unmount()
  })
}

// ------------------------------------------------- US-PM-60 criterion
//
// "On surfaces that do not draw, the commands reply with a text summary."
// Each command, where nothing draws, answers with a text summary and opens
// no pane: no surface attached (a plain `claude -p` run, Claude Code for VS
// Code chat) and a surface list that cannot be read. And a drawing surface
// that cannot seat the board pane now (refused, or ui.open failing) falls
// back to the board as text; status and next never ask for a pane.

const TEXT_SUMMARY: Record<string, string> = {
  'pm-board': BOARD_SUMMARY,
  'pm-status-view': STATUS_SUMMARY,
  'pm-next-task': NEXT_SUMMARY,
}

const NOTHING_DRAWS: { where: string; opts: EngineOpts }[] = [
  { where: 'no surface attached (claude -p, VS Code chat)', opts: { surfaces: [] } },
  { where: 'a surface list that cannot be read', opts: { surfacesFail: true } },
]

for (const { where, opts } of NOTHING_DRAWS) {
  for (const name of ['pm-board', 'pm-status-view', 'pm-next-task'] as const) {
    test(`US-PM-60 criterion: text summary where nothing draws, /${name} with ${where}`, async ($, on) => {
      const seen = engine(on, ANSWERS, opts)
      const ran = await $.command.run(run(name))

      expect(ran.text).toBe(TEXT_SUMMARY[name])
      expect((ran.text ?? '').split('\n').length).toBeLessThanOrEqual(4)
      expect(ran.text).not.toBe(BOARD_OPENED)
      expect(ran.context).toBeUndefined()
      // No pane opened, and the board pane's state left unwritten.
      expect(seen.opened).toEqual([])
      expect(seen.board).toEqual([])
      expect(seen.model).toEqual([])
      expect(seen.core).toEqual([])
    })
  }
}

const PANE_UNSEATED: { why: string; opts: EngineOpts }[] = [
  { why: 'the surface cannot seat the pane now', opts: { placed: false } },
  { why: 'opening the pane fails', opts: { openFails: true } },
]

for (const surface of PANE_SURFACES) {
  for (const { why, opts } of PANE_UNSEATED) {
    test(`US-PM-60 criterion: text summary where the pane is not placed, /pm-board on ${surface} when ${why}`, async ($, on) => {
      const seen = engine(on, ANSWERS, { surfaces: [surface], ...opts })
      const ran = await $.command.run(run('pm-board'))

      // The pane was asked for once and not seated, so the board answers as text.
      expect(seen.opened).toEqual([{ id: BOARD_PANE, title: BOARD_PANE_TITLE }])
      expect(ran.text).toBe(formatBoard(parseYaml(BOARD_YAML)))
      expect(ran.text).not.toBe(BOARD_OPENED)
      expect(ran.context).toBeUndefined()
      expect(seen.model).toEqual([])
      expect(seen.core).toEqual([])
    })

    for (const name of ['pm-status-view', 'pm-next-task'] as const) {
      test(`US-PM-60 criterion: text where the pane is not placed, /${name} on ${surface} when ${why}`, async ($, on) => {
        const seen = engine(on, ANSWERS, { surfaces: [surface], ...opts })
        const command = PM_COMMANDS.find((c) => c.name === name)!
        const ran = await $.command.run(run(name))

        // These views never ask for a pane; they answer as text either way.
        expect(ran.text).toBe(formatCommand(command, parsedAnswers(command)))
        expect(seen.opened).toEqual([])
        expect(seen.model).toEqual([])
        expect(seen.core).toEqual([])
      })
    }
  }
}
