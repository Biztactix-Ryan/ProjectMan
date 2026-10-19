// ProjectMan mod type contract (named in .claude-plugin/plugin.json "types").
// Declares the session values the hooks module keeps in $.state; the guards
// added by US-PM-59-7/8 record their last refusal here.

export type ProjectmanGuardDenial = {
  rule: string
  tool: string
  reason: string
}

// US-PM-60-7: the board pane draws from `projectman.board`, written when
// /pm-board reads `pm_board` and again by the pane's refresh button.

/** One task on the board pane. */
export type ProjectmanBoardTask = {
  id: string
  title: string
  points: number | null
  assignee: string | null
  isStale: boolean
}

/** One column of the board pane: the tasks listed and the server's total. */
export type ProjectmanBoardColumn = {
  key: 'available' | 'in_progress' | 'blocked'
  label: string
  total: number
  tasks: ProjectmanBoardTask[]
}

/** What the board pane draws. */
export type ProjectmanBoardView = {
  columns: ProjectmanBoardColumn[]
  /** How many times the board was read from the MCP server this session. */
  loads: number
  /** True while the refresh button's `pm_board` call is in flight. */
  isRefreshing: boolean
  /** Why the last read failed; the columns then are the previous read's. */
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    projectman: { lastDenial: ProjectmanGuardDenial | null; board: ProjectmanBoardView | null }
  }
}
