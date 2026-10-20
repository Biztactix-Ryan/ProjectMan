// The sprint band's signal to the SessionStart status block (US-PM-62-8).
//
// `projectman session-context`, the plugin's SessionStart command hook, puts
// a status block in the model's context. Where the sprint band draws, the
// person already sees sprint progress and the task in flight above the
// prompt, so the block can shrink to what steers the model (open decisions,
// the NEXT.md note, the last handoff).
//
// The signal: the mod's `classic.SessionStart` hook sets the environment
// variable PROJECTMAN_BAND_SESSION to the session's own id, or unsets it,
// before calling `next(e)`. Hooks modules sit above the non-managed settings
// and plugin command hooks in the classic chain, and `$.env.set` reaches
// every process the session starts after, so the command hook beneath reads
// the answer for this very SessionStart: same session, same moment.
//
// Where the band draws: only on a surface that raises the `AbovePrompt`
// render hook, terminal and desktop (BAND_SURFACES, from the band's own
// module). vscode and mobile list in `$.session.surfaces()` but raise no
// AbovePrompt, so a session that draws only there gets no band.
//
// Why it is safe: the CLI reduces the block only when the value equals its
// payload's `session_id` exactly. Where the band cannot draw the mod unsets
// it: nothing listed (`claude -p`, the SDK, Claude Code for VS Code, which
// attaches no surface today), or only surfaces without AbovePrompt (vscode,
// mobile), or a surface list that fails. A stale value (the session before a
// /clear, a parent session a nested `claude -p` inherits it from) names
// another id; a disabled mod sets nothing. Each of those prints today's full
// block. A surface draws the band only once the MCP read lands, which no
// SessionStart can wait for, so the block is reduced, never dropped: the
// note and a pointer to pm_context stay.

import { BAND_SURFACES } from './sprint-band.tsx'

/** True when one of the listed surfaces raises AbovePrompt, so the band can draw there. */
export function bandDraws(surfaces: readonly string[] | null): boolean {
  if (surfaces === null) return false
  return surfaces.some((s) => (BAND_SURFACES as readonly string[]).includes(s))
}

/** What the mod sets PROJECTMAN_BAND_SESSION to: the id where the band draws, else unset. */
export function bandSessionValue(sessionId: unknown, surfaces: readonly string[] | null): string | undefined {
  if (typeof sessionId !== 'string' || sessionId === '') return undefined
  if (!bandDraws(surfaces)) return undefined
  return sessionId
}
