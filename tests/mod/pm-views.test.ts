import type { CommandRunInput, On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { formatBoard, formatNext, formatStatus, parseYaml, PM_COMMANDS, resultText } from '../../hooks/pm-views.ts'

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

function engine(on: On, answers: Record<string, string>, opts: { asJson?: boolean; errorTool?: string; connected?: boolean } = {}): Recorded {
  const seen: Recorded = { mcp: [], model: [], core: [], registered: [] }
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
