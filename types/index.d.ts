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

// US-PM-62-6: the sprint band above the prompt draws from `projectman.band`,
// read from the MCP server when the band is first drawn and after each turn.

/** What the sprint band shows; a part is null when there is nothing for it. */
export type ProjectmanBand = {
  /** The active sprint: its short name and live points (done stories / planned). */
  sprint: { name: string; donePoints: number; totalPoints: number } | null
  /** The first in-progress task, and how many more are in progress. */
  task: { id: string; title: string; more: number } | null
  /** The first line of the NEXT.md note. */
  note: string | null
}

/** The band's value: the last read (null when there is nothing to show). */
export type ProjectmanBandState = {
  view: ProjectmanBand | null
  /** True while a read is in flight; a second read is not started meanwhile. */
  isReading: boolean
  /** How many reads finished this session. */
  reads: number
}

// US-PM-61-6: each model request's token usage while an orchestrator run is
// active, charged to the task its loop works on. Live in `projectman.cost`;
// the run's summary is also kept in `$.store` under `costRuns`, by run id.

/** Token counts summed over some requests. */
export type ProjectmanTokenCounts = {
  requests: number
  /** Uncached input tokens. */
  input: number
  /** Input tokens the prompt cache served. */
  cacheRead: number
  /** Input tokens written to the prompt cache. */
  cacheWrite: number
  output: number
}

/** One model request of the active run, as the API reported its usage. */
export type ProjectmanCostRequest = {
  /** When the response was whole, in `$.clock.now()`'s milliseconds. */
  at: number
  /** The task it was charged to; null when none could be found. */
  taskId: string | null
  /** The subagent's loop it was made in; null for the main session. */
  agentId: string | null
  model: string
  input: number
  cacheRead: number
  cacheWrite: number
  output: number
}

/** A run's summary: what is persisted in `$.store`. */
export type ProjectmanCostRun = {
  runId: string
  startedAt: number
  updatedAt: number
  /** Counts per task id. */
  tasks: Record<string, ProjectmanTokenCounts>
  /** Requests no task could be found for. */
  unattributed: ProjectmanTokenCounts
  totals: ProjectmanTokenCounts
}

/** The live recording: the active run, its recent requests and each loop's task. */
export type ProjectmanCostState = {
  /** The active run's summary; null before any run-carrying pm call. */
  run: ProjectmanCostRun | null
  /** The active run's most recent requests, newest last. */
  requests: ProjectmanCostRequest[]
  /** Loop key (`main`, or a subagent's id) to the task it last named. */
  loops: Record<string, string>
}

declare module 'claude-code' {
  interface PluginState {
    projectman: {
      lastDenial: ProjectmanGuardDenial | null
      board: ProjectmanBoardView | null
      band: ProjectmanBandState | null
      cost: ProjectmanCostState | null
    }
  }
}
