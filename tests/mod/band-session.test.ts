import type { On, RenderSurface } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { bandDraws, bandSessionValue } from '../../hooks/band-session.ts'
import { BAND_SURFACES } from '../../hooks/sprint-band.tsx'

// US-PM-62-8: the mod's classic.SessionStart hook sets PROJECTMAN_BAND_SESSION
// to the session's id where a listed surface draws the band (one that raises
// AbovePrompt: terminal, desktop), and unsets it everywhere else (nothing
// listed, or only vscode / mobile, which raise no AbovePrompt), before the chain reaches the plugin's SessionStart command hook
// (`projectman session-context`, which tests/test_session_context_band.py
// pins). The test's hooks stand for the engine: `session.surfaces` answers
// where the session draws, `env.set` records each write with the moment it
// happened, and the test's own `classic.SessionStart` stands for the command
// hook beneath, recording the variable as it would see it.

const VAR = 'PROJECTMAN_BAND_SESSION'
const BLOCK = '## ProjectMan context (/repo/.project)'

type EngineOpts = { surfaces?: readonly RenderSurface[]; surfacesFail?: boolean; envFails?: boolean }
type Seen = {
  /** Every write to the variable, in order: the value, or undefined for an unset. */
  writes: (string | undefined)[]
  /** The variable as each run of the command hook beneath saw it. */
  atCommand: (string | undefined)[]
  /** The variable now. */
  env: Map<string, string>
}

function engine(on: On, opts: EngineOpts = {}): Seen {
  const seen: Seen = { writes: [], atCommand: [], env: new Map() }
  on('session.surfaces', () => {
    if (opts.surfacesFail) throw new Error('no surface list')
    return { value: opts.surfaces ?? ['terminal'] }
  })
  on('env.set', ($, e) => {
    if (opts.envFails) throw new Error('env refused')
    if (e.name === VAR) seen.writes.push(e.value)
    if (e.value === undefined) seen.env.delete(e.name)
    else seen.env.set(e.name, e.value)
    return { value: {} }
  })
  on('classic.SessionStart', () => {
    seen.atCommand.push(seen.env.get(VAR))
    return { additionalContext: [BLOCK] }
  })
  return seen
}

const DRAWS: { name: string; surfaces: readonly RenderSurface[] }[] = [
  { name: 'terminal', surfaces: ['terminal'] },
  { name: 'desktop', surfaces: ['desktop'] },
  { name: 'vscode + terminal', surfaces: ['vscode', 'terminal'] },
  { name: 'mobile + desktop', surfaces: ['mobile', 'desktop'] },
]

for (const { name, surfaces } of DRAWS) {
  test(`US-PM-62-4 criterion: on ${name} the variable names this session before the command hook runs`, async ($, on) => {
    const seen = engine(on, { surfaces })
    const result = await $.classic.SessionStart({ source: 'startup', session_id: 'sid-1' })
    expect(seen.writes).toEqual(['sid-1'])
    expect(seen.atCommand).toEqual(['sid-1'])
    expect(result.additionalContext).toEqual([BLOCK])
  })
}

// vscode and mobile list as surfaces but raise no AbovePrompt: no band draws.
const NO_BAND: { name: string; surfaces: readonly RenderSurface[] }[] = [
  { name: 'vscode only', surfaces: ['vscode'] },
  { name: 'mobile only', surfaces: ['mobile'] },
  { name: 'vscode + mobile', surfaces: ['vscode', 'mobile'] },
]

for (const { name, surfaces } of NO_BAND) {
  test(`US-PM-62-5 criterion: on ${name} (no AbovePrompt) the variable is unset`, async ($, on) => {
    const seen = engine(on, { surfaces })
    seen.env.set(VAR, 'sid-1') // even a value naming this very session is cleared
    const result = await $.classic.SessionStart({ source: 'startup', session_id: 'sid-1' })
    expect(seen.writes).toEqual([undefined])
    expect(seen.atCommand).toEqual([undefined])
    expect(result.additionalContext).toEqual([BLOCK])
  })
}

test('US-PM-62-5 criterion: where nothing is listed (claude -p, the SDK, Claude Code for VS Code) the variable is unset', async ($, on) => {
  const seen = engine(on, { surfaces: [] })
  seen.env.set(VAR, 'sid-0') // left by an earlier session in this process
  const result = await $.classic.SessionStart({ source: 'startup', session_id: 'sid-1' })
  expect(seen.writes).toEqual([undefined])
  expect(seen.atCommand).toEqual([undefined])
  expect(result.additionalContext).toEqual([BLOCK])
})

test('US-PM-62-5 criterion: a surface list that fails is no evidence: the variable is unset', async ($, on) => {
  const seen = engine(on, { surfacesFail: true })
  await $.classic.SessionStart({ source: 'startup', session_id: 'sid-1' })
  expect(seen.writes).toEqual([undefined])
  expect(seen.atCommand).toEqual([undefined])
})

test('a /clear overwrites the variable with the new session id', async ($, on) => {
  const seen = engine(on, { surfaces: ['terminal'] })
  await $.classic.SessionStart({ source: 'startup', session_id: 'before-clear' })
  await $.classic.SessionStart({ source: 'clear', session_id: 'after-clear' })
  expect(seen.writes).toEqual(['before-clear', 'after-clear'])
  expect(seen.atCommand).toEqual(['before-clear', 'after-clear'])
})

test('a resume and a compaction name the session they start', async ($, on) => {
  const seen = engine(on, { surfaces: ['terminal'] })
  await $.classic.SessionStart({ source: 'resume', session_id: 'resumed' })
  await $.classic.SessionStart({ source: 'compact', session_id: 'resumed' })
  expect(seen.atCommand).toEqual(['resumed', 'resumed'])
})

test('a refused env write still runs the command hook and passes its answer through', async ($, on) => {
  const seen = engine(on, { surfaces: ['terminal'], envFails: true })
  const result = await $.classic.SessionStart({ source: 'startup', session_id: 'sid-1' })
  expect(seen.atCommand).toEqual([undefined])
  expect(result.additionalContext).toEqual([BLOCK])
})

test('the band surfaces are the AbovePrompt ones: terminal and desktop', async () => {
  expect([...BAND_SURFACES]).toEqual(['terminal', 'desktop'])
  expect(bandDraws(['terminal'])).toBe(true)
  expect(bandDraws(['desktop'])).toBe(true)
  expect(bandDraws(['vscode', 'terminal'])).toBe(true)
  expect(bandDraws(['vscode'])).toBe(false)
  expect(bandDraws(['mobile'])).toBe(false)
  expect(bandDraws(['some-future-surface'])).toBe(false)
  expect(bandDraws([])).toBe(false)
  expect(bandDraws(null)).toBe(false)
})

test('the value: the id where the band draws, else unset', async () => {
  expect(bandSessionValue('sid', ['terminal'])).toBe('sid')
  expect(bandSessionValue('sid', ['desktop', 'mobile'])).toBe('sid')
  expect(bandSessionValue('sid', ['vscode', 'terminal'])).toBe('sid')
  expect(bandSessionValue('sid', ['vscode'])).toBeUndefined()
  expect(bandSessionValue('sid', ['mobile'])).toBeUndefined()
  expect(bandSessionValue('sid', [])).toBeUndefined()
  expect(bandSessionValue('sid', null)).toBeUndefined()
  expect(bandSessionValue('', ['terminal'])).toBeUndefined()
  expect(bandSessionValue(undefined, ['terminal'])).toBeUndefined()
  expect(bandSessionValue(17, ['terminal'])).toBeUndefined()
})
