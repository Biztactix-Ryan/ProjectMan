import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { register } from '../../hooks/register.ts'

// US-PM-59-7: the Bash guard against git checkout / restore / stash.
// The test's own tool.call hook stands for the engine: a call that reaches it
// "ran"; a refused call never does. Nothing here runs a real shell.

// The loop id a subagent's tool.call carries. Spread in, as the testing
// kit's $.tool.call input type does not list `agentId`; the engine passes it.
const IN_SUBAGENT = { agentId: 'agent-worker-1' }
const lastDenial = { plugin: 'projectman', key: 'lastDenial' } as const

const BANNED = [
  'git checkout main',
  'git checkout -- src/app.py',
  'git restore src/app.py',
  'git restore --staged .',
  'git stash',
  'git stash pop',
  'git stash list',
  'git -C /tmp/repo checkout x',
  'git -c core.pager=cat checkout x',
  'git --no-pager stash show',
  'git --git-dir=.git --work-tree=. restore x',
  '/usr/bin/git checkout x',
  'git status && git checkout x',
  'git status; git stash',
  'false || git restore x',
  'git diff | git stash',
  'echo $(git stash)',
  'echo "$(git checkout x)"',
  'echo `git restore x`',
  '(cd sub && git checkout x)',
  'git status\ngit stash',
  'env GIT_DIR=.git git checkout x',
  'FOO=1 git stash',
  'command git restore x',
  'sudo -E git checkout x',
  "bash -c 'git stash'",
  'sh -lc "cd x && git checkout y"',
  'eval git stash',
  'git 2>/dev/null checkout x',
]

const ALLOWED = [
  'git status',
  'git log --oneline -- checkout.py',
  'git diff -- src/restore.ts',
  'grep -rn checkout src',
  'echo "git stash"',
  "echo 'git checkout main && git restore .'",
  'git commit -m "explain why not git stash"',
  'git switch -c feature',
  'git checkout-index -a',
  'ls stash checkout restore',
  'uv run pytest tests/test_checkout.py -q # git stash',
]

function engineBeneath(on: On, ran: string[]) {
  on('tool.call', { tool: 'Bash' }, ($, e) => {
    ran.push(e.command)
    return { result: 'ran' }
  })
}

test('banned git commands are refused inside a subagent, naming the rule', async ($, on) => {
  const ran: string[] = []
  engineBeneath(on, ran)

  for (const command of BANNED) {
    const out = await $.tool.call({ tool: 'Bash', command, ...IN_SUBAGENT })
    expect(out.deny).toContain('ProjectMan worker rule')
    expect(out.deny).toContain('git checkout, git restore or git stash')
  }
  expect(ran).toEqual([])
})

test('allowed commands pass inside a subagent', async ($, on) => {
  const ran: string[] = []
  engineBeneath(on, ran)

  for (const command of ALLOWED) {
    const out = await $.tool.call({ tool: 'Bash', command, ...IN_SUBAGENT })
    expect(out.deny).toBeUndefined()
    expect(out.result).toBe('ran')
  }
  expect(ran).toEqual(ALLOWED)
})

test('a refusal is recorded as projectman.lastDenial', async ($, on) => {
  engineBeneath(on, [])
  const written: unknown[] = []
  on('state.set', ($, e, next) => {
    if (e.plugin === lastDenial.plugin && e.key === lastDenial.key) written.push(e.value)
    return next(e)
  })

  await $.tool.call({ tool: 'Bash', command: 'git status && git stash pop', ...IN_SUBAGENT })

  expect(written).toHaveLength(1)
  expect(written[0]).toEqual({
    rule: 'git stash',
    tool: 'Bash',
    reason: expect.stringContaining('ProjectMan worker rule'),
  })
})

test('the main session is not guarded by default', async ($, on) => {
  const ran: string[] = []
  engineBeneath(on, ran)

  const out = await $.tool.call({ tool: 'Bash', command: 'git stash' })

  expect(out.result).toBe('ran')
  expect(ran).toEqual(['git stash'])
})

test('guard_main_session extends the guard to the main session', { options: { guard_main_session: true } }, async ($, on) => {
  const ran: string[] = []
  engineBeneath(on, ran)

  const refused = await $.tool.call({ tool: 'Bash', command: 'git -C . checkout main' })
  const allowed = await $.tool.call({ tool: 'Bash', command: 'git status' })

  expect(refused.deny).toContain('ProjectMan worker rule')
  expect(allowed.result).toBe('ran')
  expect(ran).toEqual(['git status'])
})

// "Including inside subagents", by the Agent tool path. The kit runs no model,
// and a test's own hooks cannot issue tool calls ("its hooks module does not
// call it"), so the test body plays each subagent's loop: the Agent hook below
// stands for the engine starting a subagent and answers the child's loop id,
// and the body then makes that child's calls under it, a grandchild's too.
// A nested subagent's calls carry only their own loop's `agentId`
// (`parentAgentId` lives on `agent.spawn`, never on `tool.call`), so agentId-set
// is the one signal the guard has, and needs, at any depth.
function agentsBeneath(on: On, spawned: { id: string; parent?: string }[]) {
  on('tool.call', { tool: 'Agent' }, ($, e) => {
    const id = `agent-${spawned.length + 1}`
    spawned.push({ id, parent: e.agentId })
    return { result: id }
  })
}

test('a subagent spawned through the Agent tool, and its own subagent, are refused naming the rule', async ($, on) => {
  const ran: string[] = []
  const spawned: { id: string; parent?: string }[] = []
  engineBeneath(on, ran)
  agentsBeneath(on, spawned)

  const child = await $.tool.call({ tool: 'Agent', description: 'worker', prompt: 'do the task' })
  expect(child.deny).toBeUndefined()
  const childId = child.result as string
  const childCalls = ['git checkout main', 'git status']
  const childOut = []
  for (const command of childCalls) childOut.push(await $.tool.call({ tool: 'Bash', command, agentId: childId }))

  const grandchild = await $.tool.call({ tool: 'Agent', description: 'nested', prompt: 'sub-task', agentId: childId })
  expect(grandchild.deny).toBeUndefined()
  const grandId = grandchild.result as string
  const grandCalls = ['git restore x', 'git stash', 'git log -1']
  const grandOut = []
  for (const command of grandCalls) grandOut.push(await $.tool.call({ tool: 'Bash', command, agentId: grandId }))

  expect(spawned).toEqual([{ id: 'agent-1', parent: undefined }, { id: 'agent-2', parent: 'agent-1' }])
  expect(ran).toEqual(['git status', 'git log -1'])
  for (const out of [childOut[0], grandOut[0], grandOut[1]]) {
    expect(out.deny).toContain('ProjectMan worker rule')
    expect(out.deny).toContain('git checkout, git restore or git stash')
  }
  expect(childOut[1].result).toBe('ran')
  expect(grandOut[2].result).toBe('ran')
})

for (const sub of ['checkout', 'restore', 'stash'] as const) {
  test(`git ${sub} in a subagent is refused with the rule's reason and recorded by name`, async ($, on) => {
    const ran: string[] = []
    engineBeneath(on, ran)
    const written: unknown[] = []
    on('state.set', ($, e, next) => {
      if (e.plugin === lastDenial.plugin && e.key === lastDenial.key) written.push(e.value)
      return next(e)
    })

    const out = await $.tool.call({ tool: 'Bash', command: `git ${sub} x`, ...IN_SUBAGENT })

    expect(out.deny).toMatch(/^ProjectMan worker rule: never run git checkout, git restore or git stash/)
    expect(written).toEqual([{ rule: `git ${sub}`, tool: 'Bash', reason: out.deny }])
    expect(ran).toEqual([])
  })
}

// US-PM-59-4: the scope matrix. Main-session calls pass unless
// guard_main_session is the boolean true; subagent calls are refused whatever
// the option says.
for (const value of [false, true] as const) {
  test(`a subagent's banned git is refused with guard_main_session=${value}`, { options: { guard_main_session: value } }, async ($, on) => {
    const ran: string[] = []
    engineBeneath(on, ran)

    const out = await $.tool.call({ tool: 'Bash', command: 'git stash', ...IN_SUBAGENT })

    expect(out.deny).toContain('ProjectMan worker rule')
    expect(ran).toEqual([])
  })
}

test('guard_main_session=false behaves like the default: the main session is not guarded', { options: { guard_main_session: false } }, async ($, on) => {
  const ran: string[] = []
  engineBeneath(on, ran)

  const out = await $.tool.call({ tool: 'Bash', command: 'git checkout main' })

  expect(out.deny).toBeUndefined()
  expect(out.result).toBe('ran')
  expect(ran).toEqual(['git checkout main'])
})

// Decision: only the boolean true turns the main-session guard on.
// Two layers hold it. The engine validates options against plugin.json's
// boolean field and will not load the module with the string "true" (the kit
// reports "options do not fit plugin.json userConfig ... must be a boolean"),
// so a session never runs the guard with it. And the module itself reads
// `options.guard_main_session === true`, so were a non-boolean to reach it,
// the main session would still not be guarded. The second layer is checked
// here by calling `register` directly with a stand-in `on`.
test('a non-boolean guard_main_session ("true" string) does not guard the main session', async () => {
  type Hook = (...args: unknown[]) => unknown
  const hooks: { matcher: unknown; hook: Hook }[] = []
  const fakeOn = ((event: string, matcher: unknown, hook: Hook) => {
    if (event === 'tool.call') hooks.push({ matcher, hook })
    return { catch: () => undefined }
  }) as never
  register(fakeOn, { guard_main_session: 'true' } as never)

  const bash = hooks.find((h) => (h.matcher as { tool: unknown }).tool === 'Bash')
  expect(bash).toBeDefined()
  const passed: unknown[] = []
  const next = (e: unknown) => {
    passed.push(e)
    return { result: 'ran' }
  }
  const $ = { state: { set: async () => undefined } }
  const main = await bash!.hook($, { tool: 'Bash', command: 'git stash' }, next)
  const sub = await bash!.hook($, { tool: 'Bash', command: 'git stash', ...IN_SUBAGENT }, next)

  expect(main).toEqual({ result: 'ran' })
  expect((sub as { deny?: string }).deny).toContain('ProjectMan worker rule')
  expect(passed).toHaveLength(1)
})
