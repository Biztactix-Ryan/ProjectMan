import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { register } from '../../hooks/register.ts'

// US-PM-59-8: the Write / Edit / NotebookEdit guard against the real .project
// store. Nothing here touches a disk: the test's hooks beneath the plugin
// answer `$.session.root()`, `$.session.cwd()` and `$.fs.stat()` from an
// in-memory tree, and its tool.call hook stands for the engine (a call that
// reaches it "ran"; a refused call never does).

const IN_SUBAGENT = { agentId: 'agent-worker-1' }
const ROOT = '/work/proj'
// The real store, as a worktree checkout would be: a plain directory whose
// `.git` is a file. `/work/proj/.project` itself is a symlink to it, so the
// guard must compare real paths.
const STORE_REAL = '/work/proj-store'

const DIRS = new Set([
  '/',
  '/work',
  ROOT,
  `${ROOT}/src`,
  STORE_REAL,
  `${STORE_REAL}/stories`,
  `${ROOT}/.project-backup`,
  `${ROOT}/my.project`,
  '/tmp',
  '/tmp/pytest-of-u',
  '/tmp/pytest-of-u/test_x0',
  '/tmp/pytest-of-u/test_x0/.project',
  '/tmp/pytest-of-u/test_x0/.project/stories',
])
const FILES = new Set([
  `${STORE_REAL}/.git`,
  `${STORE_REAL}/stories/US-1.md`,
  `${ROOT}/src/app.py`,
  '/tmp/pytest-of-u/test_x0/.project/stories/US-1.md',
])
const LINKS: Record<string, string> = {
  [`${ROOT}/.project`]: STORE_REAL,
  [`${ROOT}/src/sneaky`]: `${STORE_REAL}/stories`,
}

/** Folds `.`/`..` and follows LINKS segment by segment; undefined when missing. */
function realpath(path: string, cwd: string): string | undefined {
  const parts = (path.startsWith('/') ? path : `${cwd}/${path}`).split('/')
  let out: string[] = []
  for (const seg of parts) {
    if (seg === '' || seg === '.') continue
    if (seg === '..') {
      out.pop()
      continue
    }
    out.push(seg)
    let here = '/' + out.join('/')
    for (let hops = 0; LINKS[here] !== undefined && hops < 8; hops++) {
      here = LINKS[here] as string
      out = here.split('/').filter(Boolean)
    }
    if (!DIRS.has(here) && !FILES.has(here)) return undefined
  }
  return '/' + out.join('/')
}

function fakeProject(on: On, ran: string[], cwd = ROOT) {
  // A test hook answering a call on `$` answers `{ value }`.
  on('session.root', () => ({ value: ROOT }))
  on('session.cwd', () => ({ value: cwd }))
  on('fs.stat', ($, e) => {
    const real = realpath(e.path, cwd)
    if (real === undefined) throw Object.assign(new Error(`ENOENT: ${e.path}`), { code: 'ENOENT' })
    return {
      value: {
        kind: DIRS.has(real) ? 'dir' : 'file',
        size: 0,
        mtimeMs: 0,
        isLink: LINKS[e.path] !== undefined,
        ...(e.resolve ? { realPath: real } : {}),
      },
    }
  })
  on('tool.call', { tool: ['Write', 'Edit', 'NotebookEdit'] }, ($, e) => {
    ran.push(e.tool === 'NotebookEdit' ? e.notebook_path : e.file_path)
    return { result: 'ran' }
  })
  on('tool.call', { tool: 'mcp__projectman__pm_update' }, ($, e) => {
    ran.push(e.tool)
    return { result: 'ran' }
  })
}

const write = (file_path: string, extra: Record<string, unknown> = IN_SUBAGENT) =>
  ({ tool: 'Write', file_path, content: 'x', ...extra }) as const
const edit = (file_path: string) =>
  ({ tool: 'Edit', file_path, old_string: 'a', new_string: 'b', ...IN_SUBAGENT }) as const

const REFUSED = [
  write(`${ROOT}/.project/stories/US-1.md`), // existing, absolute
  write(`${ROOT}/.project/stories/US-99.md`), // new file
  write(`${ROOT}/.project/epics/new/EPIC-1.md`), // new file in new dirs
  write('.project/stories/US-1.md'), // relative
  write('.project/new.md'), // relative, new
  write(`${ROOT}/src/../.project/stories/US-1.md`), // via ..
  write(`${ROOT}/src/missing/../../.project/x.md`), // via .. through a missing dir
  write(`${ROOT}/src/sneaky/US-1.md`), // via a symlink into the store
  write(`${ROOT}/src/sneaky/US-new.md`), // new file via the symlink
  write(`${ROOT}/src/sneaky/../US-top.md`), // the kernel reads the link before ..
  write(`${STORE_REAL}/stories/US-1.md`), // the store's real path
  write(`${ROOT}/.project`), // the store directory itself
  edit(`${ROOT}/.project/stories/US-1.md`),
  edit('./.project/../.project/stories/US-1.md'),
  // MultiEdit is not a built-in on every build; matched by name where it is.
  { tool: 'MultiEdit', file_path: `${ROOT}/.project/stories/US-1.md`, edits: [], ...IN_SUBAGENT } as unknown as ReturnType<
    typeof edit
  >,
  {
    tool: 'NotebookEdit',
    notebook_path: `${ROOT}/.project/nb.ipynb`,
    new_source: 'x',
    ...IN_SUBAGENT,
  } as const,
]

const ALLOWED = [
  write(`${ROOT}/src/app.py`),
  write('src/new.py'),
  write('/tmp/pytest-of-u/test_x0/.project/stories/US-1.md'), // tmp_path fixture store
  write('/tmp/pytest-of-u/test_x0/.project/stories/US-2.md'),
  write(`${ROOT}/.project-backup/US-1.md`),
  write(`${ROOT}/my.project/US-1.md`),
  write(`${ROOT}/.projectx`),
  edit(`${ROOT}/src/app.py`),
]

test('writes into the real store are refused inside a subagent, naming the rule', async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  const passed: string[] = []
  for (const call of REFUSED) {
    const out = await $.tool.call(call)
    if (out.deny === undefined) passed.push(call.tool === 'NotebookEdit' ? call.notebook_path : call.file_path)
    else expect(out.deny).toContain('use the pm MCP tools')
  }
  expect(passed).toEqual([])
  expect(ran).toEqual([])
})

test('tmp fixtures, sibling names and ordinary files pass inside a subagent', async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  for (const call of ALLOWED) {
    const out = await $.tool.call(call)
    expect(out.deny).toBeUndefined()
    expect(out.result).toBe('ran')
  }
  expect(ran).toEqual(ALLOWED.map((c) => c.file_path))
})

test('pm MCP tools are never matched', async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  const out = await $.tool.call({
    tool: 'mcp__projectman__pm_update',
    id: 'US-1',
    file_path: `${ROOT}/.project/stories/US-1.md`,
    ...IN_SUBAGENT,
  })

  expect(out.deny).toBeUndefined()
  expect(ran).toEqual(['mcp__projectman__pm_update'])
})

test('a subagent running in another cwd is still kept out of the project store', async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran, `${ROOT}/src`)

  const refused = await $.tool.call(write('../.project/stories/US-1.md'))
  const allowed = await $.tool.call(write('app.py'))

  expect(refused.deny).toContain('ProjectMan worker rule')
  expect(allowed.result).toBe('ran')
})

test('a refusal is recorded as projectman.lastDenial', async ($, on) => {
  fakeProject(on, [])
  const written: unknown[] = []
  on('state.set', ($, e, next) => {
    if (e.plugin === 'projectman' && e.key === 'lastDenial') written.push(e.value)
    return next(e)
  })

  await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`))

  expect(written).toEqual([
    { rule: 'store write', tool: 'Write', reason: expect.stringContaining('ProjectMan worker rule') },
  ])
})

test('the main session is not guarded by default', async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  const out = await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`, {}))

  expect(out.result).toBe('ran')
  expect(ran).toEqual([`${ROOT}/.project/stories/US-1.md`])
})

test('guard_main_session extends the guard to the main session', { options: { guard_main_session: true } }, async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  const refused = await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`, {}))
  const allowed = await $.tool.call(write(`${ROOT}/src/app.py`, {}))

  expect(refused.deny).toContain('ProjectMan worker rule')
  expect(allowed.result).toBe('ran')
  expect(ran).toEqual([`${ROOT}/src/app.py`])
})

// US-PM-59-3: in one subagent, Write and Edit at the real store are refused
// with the rule's reason, then the pm MCP tools (whose arguments name .project
// paths) still reach the engine with their arguments exactly as sent.
test('after Write and Edit are refused, pm MCP calls in the same subagent pass through untouched', async ($, on) => {
  const ran: string[] = []
  const seen: Record<string, unknown>[] = []
  // Registered before fakeProject's hooks so it is the first engine stand-in the MCP calls reach.
  on('tool.call', { tool: ['mcp__projectman__pm_update', 'mcp__projectman__pm_update_doc'] }, ($, e) => {
    seen.push({ ...e })
    return { result: 'ok' }
  })
  fakeProject(on, ran)

  const refusedWrite = await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`))
  const refusedEdit = await $.tool.call(edit(`${ROOT}/.project/stories/US-1.md`))
  for (const out of [refusedWrite, refusedEdit]) {
    expect(out.deny).toMatch(/^ProjectMan worker rule: never write to the real \.project store directly/)
    expect(out.deny).toContain('use the pm MCP tools')
  }

  const update = {
    tool: 'mcp__projectman__pm_update',
    id: 'US-1',
    note: 'see .project/stories/US-1.md',
    file_path: `${ROOT}/.project/stories/US-1.md`,
    ...IN_SUBAGENT,
  }
  const updateDoc = {
    tool: 'mcp__projectman__pm_update_doc',
    name: 'ARCHITECTURE',
    content: 'x',
    path: `${ROOT}/.project/ARCHITECTURE.md`,
    ...IN_SUBAGENT,
  }
  const outs = [await $.tool.call(update as never), await $.tool.call(updateDoc as never)]

  for (const out of outs) {
    expect((out as { deny?: string }).deny).toBeUndefined()
    expect((out as { result?: unknown }).result).toBe('ok')
  }
  // Exactly as sent; the engine stamps only the call's tool_use_id.
  const stamped = { tool_use_id: expect.any(String) }
  expect(seen).toEqual([{ ...update, ...stamped }, { ...updateDoc, ...stamped }])
  expect(ran).toEqual([]) // the refused Write/Edit never reached the engine
})

// US-PM-59-4: the scope matrix. Main-session writes pass unless
// guard_main_session is the boolean true; subagent writes into the store are
// refused whatever the option says.
for (const value of [false, true] as const) {
  test(`a subagent's store write is refused with guard_main_session=${value}`, { options: { guard_main_session: value } }, async ($, on) => {
    const ran: string[] = []
    fakeProject(on, ran)

    const out = await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`))

    expect(out.deny).toContain('ProjectMan worker rule')
    expect(ran).toEqual([])
  })
}

test('guard_main_session=false behaves like the default: the main session is not guarded', { options: { guard_main_session: false } }, async ($, on) => {
  const ran: string[] = []
  fakeProject(on, ran)

  const out = await $.tool.call(write(`${ROOT}/.project/stories/US-1.md`, {}))

  expect(out.deny).toBeUndefined()
  expect(out.result).toBe('ran')
  expect(ran).toEqual([`${ROOT}/.project/stories/US-1.md`])
})

// Decision: only the boolean true turns the main-session guard on. The engine
// will not load the module with a non-boolean value for this boolean field
// (see git-guard.test.ts); the module's own `=== true` is checked here by
// calling `register` directly with a stand-in `on` and `$`.
test('a non-boolean guard_main_session ("true" string) does not guard main-session store writes', async () => {
  type Hook = (...args: unknown[]) => unknown
  const hooks: { matcher: unknown; hook: Hook }[] = []
  const fakeOn = ((event: string, matcher: unknown, hook: Hook) => {
    if (event === 'tool.call') hooks.push({ matcher, hook })
    return { catch: () => undefined }
  }) as never
  register(fakeOn, { guard_main_session: 'true' } as never)

  const store = hooks.find((h) => Array.isArray((h.matcher as { tool: unknown }).tool))
  expect(store).toBeDefined()
  const $ = {
    state: { set: async () => undefined },
    session: { root: async () => ROOT, cwd: async () => ROOT },
    fs: {
      stat: async (path: string) => {
        const real = realpath(path, ROOT)
        if (real === undefined) throw new Error(`ENOENT: ${path}`)
        return { realPath: real }
      },
    },
  }
  const passed: unknown[] = []
  const next = (e: unknown) => {
    passed.push(e)
    return { result: 'ran' }
  }
  const main = await store!.hook($, write(`${ROOT}/.project/stories/US-1.md`, {}), next)
  const sub = await store!.hook($, write(`${ROOT}/.project/stories/US-1.md`), next)

  expect(main).toEqual({ result: 'ran' })
  expect((sub as { deny?: string }).deny).toContain('ProjectMan worker rule')
  expect(passed).toHaveLength(1)
})
