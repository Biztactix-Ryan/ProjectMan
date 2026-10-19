import type { RenderSurface } from 'claude-code'

// Does this surface draw panes? (US-PM-60-8). The board, status and next
// views open a pane where a surface draws one and answer with a compact
// text summary where none does; US-PM-60-7's pane branches on this too.
//
// `$.session.surfaces()` lists every surface the session draws on: the
// terminal under the REPL, Claude Code Desktop, the mobile app. It is empty
// where nothing draws: a plain `claude -p` run, and Claude Code for VS Code,
// which attaches no surface yet (hooks and commands run, nothing drawn shows).

/** How a view answers: drawn as a pane, or as transcript text. */
export type ViewMode = 'pane' | 'text'

/** The part of `$` the check reads, so a test can hand it a stand-in. */
export type SurfaceSource = { session: { surfaces: () => Promise<readonly RenderSurface[]> } }

/** `pane` when any surface draws, `text` when the list is empty. */
export function viewModeFor(surfaces: readonly string[]): ViewMode {
  return surfaces.length > 0 ? 'pane' : 'text'
}

/** Asks the session where it draws; `text` when it cannot say. */
export async function viewMode($: SurfaceSource): Promise<ViewMode> {
  try {
    return viewModeFor(await $.session.surfaces())
  } catch {
    return 'text'
  }
}
