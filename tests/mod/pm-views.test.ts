import type { CommandRunInput, On, RenderSurface } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import {
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

type Recorded = { mcp: { server: string; tool: string; args: Record<string, unknown> }[]; model: string[]; core: string[]; registered: unknown[] }

type EngineOpts = { asJson?: boolean; errorTool?: string; connected?: boolean; surfaces?: readonly RenderSurface[]; surfacesFail?: boolean }

// `surfaces` is where the session draws: the terminal by default (the
// drawing path), `[]` for VS Code chat and `claude -p`.
function engine(on: On, answers: Record<string, string>, opts: EngineOpts = {}): Recorded {
  const seen: Recorded = { mcp: [], model: [], core: [], registered: [] }
  on('session.surfaces', () => {
    if (opts.surfacesFail) throw new Error('no surface list')
    return { value: opts.surfaces ?? ['terminal'] }
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
  on('model.complete', ($, e) => {
    seen.model.push('model.complete')
    return { deny: 'no model request may be made' }
  })
  on('model.classify', ($, e) => {
    seen.model.push('model.classify')
    return { deny: 'no model request may be made' }
  })
  on('model.fork', ($, e) => {
    seen.model.push('model.fork')
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

test('/pm-board calls pm_board on the MCP server and formats the board, no model request', async ($, on) => {
  const seen = engine(on, ANSWERS)
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
      // The pane stub (US-PM-60-7 replaces it) answers with the full view.
      expect(ran.text).toBe(formatCommand(command, parsedAnswers(command)))
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
