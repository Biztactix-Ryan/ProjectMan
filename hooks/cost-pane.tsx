import type { BoxProps, ElementConstructor, RenderElement, TextProps } from 'claude-code'
import type { ProjectmanCostRequest, ProjectmanCostRun, ProjectmanCostState, ProjectmanTokenCounts } from '../types'
import { CACHE_TTL_MS, HEARTBEAT_BUCKET, UNATTRIBUTED_BUCKET } from './cost-record.ts'

// The cache-cost pane's tree (US-PM-61-7): the active (or most recent) run's
// per-task input / cache-read / cache-write totals, the heartbeat requests in
// their own bucket with the cache writes they avoided, and the recent
// requests with a marker on each that followed a gap over the cache TTL.
// Drawn from `projectman.cost` (US-PM-61-6) alone, or the last summary kept
// in `$.store` when no run is live; register.ts reads those and hands them in,
// so this file holds no `$` and draws the same on every surface (only Box and
// Text, which every surface's table carries). /pm-cost opens it; where no
// surface draws, `costSummary` is the same content as text.

/** The id the cost pane is opened under and its `ui.render` matcher names. */
export const COST_PANE = 'pm-cost'
export const COST_PANE_TITLE = 'ProjectMan cache cost'
/** The slash command that opens it. */
export const COST_COMMAND = 'pm-cost'
export const COST_COMMAND_DESCRIPTION = 'Cache reads vs. writes per task for the current orchestrator run (no Claude turn)'
/** /pm-cost's answer once the pane is drawn. */
export const COST_OPENED = 'ProjectMan cache cost opened in a pane; it updates with each request of the run.'

/** The keys a test (or another plugin) addresses the pane's sections by. */
export const COST_TASKS_KEY = 'cost-tasks'
export const COST_HEARTBEAT_KEY = 'cost-heartbeat'
export const COST_REQUESTS_KEY = 'cost-requests'

/** How many of the most recent requests the pane lists. */
export const RECENT_REQUESTS = 12

/** The marker on a request that followed a gap over the TTL. */
export const PAST_TTL_MARK = '▲ past TTL'

/** What the pane draws: a run, live or kept, and the live run's recent requests. */
export type CostView = {
  run: ProjectmanCostRun
  /** Newest last; empty for a kept run, whose requests are not kept. */
  requests: readonly ProjectmanCostRequest[]
  /** True for the run being recorded now, false for the last one kept. */
  isLive: boolean
  ttlMs: number
}

/** The view for the live state, else the kept run; null when neither has a run. */
export function costView(
  state: ProjectmanCostState | null,
  kept: ProjectmanCostRun | null,
  ttlMs: number = CACHE_TTL_MS,
): CostView | null {
  if (state?.run) return { run: state.run, requests: state.requests, isLive: true, ttlMs }
  if (kept) return { run: kept, requests: [], isLive: false, ttlMs }
  return null
}

/** The elements the pane draws with: the part of any surface's table it uses. */
export type CostPaneElements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
}

/** A token count, short: 600, 20.5k, 1.2M. */
export function tokens(n: number): string {
  const short = (v: number, unit: string) => `${v.toFixed(1).replace(/\.0$/, '')}${unit}`
  if (n < 1000) return String(n)
  if (n < 1_000_000) return short(n / 1000, 'k')
  return short(n / 1_000_000, 'M')
}

/** A gap, short: 40s, 12m, 1h02m. */
export function duration(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}m`
}

/** `3 req · input 5 · cache read 40.5k · cache write 600`. */
export function countsText(counts: ProjectmanTokenCounts): string {
  return (
    `${counts.requests} req · input ${tokens(counts.input)} · ` +
    `cache read ${tokens(counts.cacheRead)} · cache write ${tokens(counts.cacheWrite)}`
  )
}

/** ` · 2 past TTL` for a bucket with requests after a gap over the TTL, else ''. */
function pastText(run: ProjectmanCostRun, bucket: string): string {
  const past = run.pastTtl?.[bucket] ?? 0
  return past > 0 ? ` · ${past} past TTL` : ''
}

/** The header lines: which run, whether live, how many requests, the TTL. */
export function headerLines(view: CostView): string[] {
  const { run } = view
  const past = Object.values(run.pastTtl ?? {}).reduce((a, b) => a + b, 0)
  return [
    `Run ${run.runId} · ${view.isLive ? 'live' : 'last kept, not live'}`,
    `${run.totals.requests} requests · cache TTL ${duration(view.ttlMs)} · ${past} past TTL`,
  ]
}

/** One line per task, in the order first charged, then unattributed and the total. */
export function taskLines(run: ProjectmanCostRun): { text: string; isWarning: boolean }[] {
  const lines = Object.entries(run.tasks).map(([id, counts]) => ({
    text: `${id}  ${countsText(counts)}${pastText(run, id)}`,
    isWarning: (run.pastTtl?.[id] ?? 0) > 0,
  }))
  if (run.unattributed.requests > 0) {
    lines.push({
      text: `unattributed  ${countsText(run.unattributed)}${pastText(run, UNATTRIBUTED_BUCKET)}`,
      isWarning: (run.pastTtl?.[UNATTRIBUTED_BUCKET] ?? 0) > 0,
    })
  }
  lines.push({ text: `Total  ${countsText(run.totals)}`, isWarning: false })
  return lines
}

/** The heartbeat bucket: its counts and the cache writes it avoided. */
export function heartbeatLines(run: ProjectmanCostRun): string[] {
  const beat = run.heartbeat
  if (beat === undefined) return ['No heartbeat requests yet.']
  const lines = [`${countsText(beat)}${pastText(run, HEARTBEAT_BUCKET)}`]
  lines.push(
    `Bridged ${beat.bridged} wait${beat.bridged === 1 ? '' : 's'} over the TTL · ` +
      `avoided ${tokens(beat.avoidedWrites)} cache-write tokens`,
  )
  return lines
}

/** One request: `+1h02m  US-PM-61-7 (worker)  input 3 · read 20k · write 500  ▲ past TTL`. */
export function requestLine(request: ProjectmanCostRequest): string {
  const gap = request.gapMs === null ? 'first' : `+${duration(request.gapMs)}`
  const who = request.isHeartbeat ? 'heartbeat' : (request.taskId ?? 'unattributed')
  const loop = request.agentId === null ? '' : ' (worker)'
  const counts = `input ${tokens(request.input)} · read ${tokens(request.cacheRead)} · write ${tokens(request.cacheWrite)}`
  return `${gap}  ${who}${loop}  ${counts}${request.isPastTtl ? `  ${PAST_TTL_MARK}` : ''}`
}

/** The most recent requests, newest first. */
function recent(view: CostView): ProjectmanCostRequest[] {
  return view.requests.slice(-RECENT_REQUESTS).reverse()
}

const NO_RUN =
  'No orchestrator run recorded yet. Requests are recorded once a pm call carries a run_id (/pm-orchestrate passes one).'

/** The pane's tree for `view`. */
export function costPane({ Box, Text }: CostPaneElements, view: CostView | null): RenderElement {
  if (view === null) {
    return (
      <Box key="pm-cost" flexDirection="column">
        <Text dimColor>{NO_RUN}</Text>
      </Box>
    )
  }
  const [title, status] = headerLines(view)
  return (
    <Box key="pm-cost" flexDirection="column" gap={1}>
      <Box flexDirection="column">
        <Text bold>{title}</Text>
        <Text dimColor>{status}</Text>
      </Box>
      <Box key={COST_TASKS_KEY} flexDirection="column">
        <Text bold>Per task</Text>
        {taskLines(view.run).map((line) => (
          <Text color={line.isWarning ? 'warning' : undefined} wrap="truncate-end">
            {line.text}
          </Text>
        ))}
      </Box>
      <Box key={COST_HEARTBEAT_KEY} flexDirection="column">
        <Text bold>Heartbeats</Text>
        {heartbeatLines(view.run).map((line) => (
          <Text wrap="truncate-end">{line}</Text>
        ))}
      </Box>
      <Box key={COST_REQUESTS_KEY} flexDirection="column">
        <Text bold>Recent requests</Text>
        {view.isLive ? null : <Text dimColor>Requests are listed for the live run only.</Text>}
        {view.isLive && view.requests.length === 0 ? <Text dimColor>none yet</Text> : null}
        {recent(view).map((request) => (
          <Text color={request.isPastTtl ? 'warning' : undefined} wrap="truncate-end">
            {requestLine(request)}
          </Text>
        ))}
      </Box>
    </Box>
  )
}

/** The pane's content as text, for /pm-cost where no surface draws or the pane cannot be seated. */
export function costSummary(view: CostView | null): string {
  if (view === null) return `ProjectMan cache cost: ${NO_RUN}`
  const [title, status] = headerLines(view)
  const lines = [`ProjectMan cache cost: ${title}`, status, '', 'Per task:']
  for (const line of taskLines(view.run)) lines.push(`  ${line.text}`)
  lines.push('', 'Heartbeats:')
  for (const line of heartbeatLines(view.run)) lines.push(`  ${line}`)
  const marked = view.requests.filter((r) => r.isPastTtl)
  if (marked.length > 0) {
    lines.push('', 'Requests past TTL (most recent first):')
    for (const request of marked.slice(-RECENT_REQUESTS).reverse()) lines.push(`  ${requestLine(request)}`)
  }
  return lines.join('\n')
}
