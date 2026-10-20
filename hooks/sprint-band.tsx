import type { ElementConstructor, RenderElement, RenderSurface, TextProps, BoxProps } from 'claude-code'
import type { ProjectmanBand } from '../types'
import { asMap, asRows, num, str } from './pm-views.ts'
import type { Yaml } from './pm-views.ts'

// The sprint band above the prompt (US-PM-62-6): the active sprint's live
// points, the task in flight and the head of the NEXT.md note, e.g.
//
//   Sprint 20 — 11/19 pts · ▶ US-PM-62-6 Draw the sprint band · next: Close EPIC-PM-7
//
// so the person sees where things stand without the SessionStart hook
// putting status text in the model's context. Pure: register.ts makes the
// MCP calls below with `$.mcp.call`, hands the answers to `bandFrom`, keeps
// the result in `projectman.band` and draws it with `sprintBand`.
//
// What shows: each part only when it has something to say. No active sprint
// drops the sprint part (the task and note still show); with no part at all,
// or no store in the directory (the MCP tools answer with an error), or an
// unconnected server, the band draws nothing and the engine's own band shows.

/** One MCP call the band makes. */
export type BandCall = { tool: string; args: Record<string, unknown> }

/** The calls made on every read, together: the active sprint's id, the first task in flight, the note. */
export const BAND_SPRINTS: BandCall = { tool: 'pm_list_sprints', args: { status: 'active', fields: 'name' } }
export const BAND_ACTIVE: BandCall = { tool: 'pm_active', args: { limit: 1 } }
export const BAND_NOTE: BandCall = { tool: 'pm_next', args: {} }
/** Made only when a sprint is active: its live per-story progress. */
export const bandSprintCall = (id: string): BandCall => ({ tool: 'pm_get_sprint', args: { sprint_id: id } })

/** The key of the band's Box, which a test (or another plugin) addresses it by. */
export const BAND_KEY = 'pm-band'

/**
 * The surfaces the band draws on: those that raise the `AbovePrompt` render
 * hook, which the engine's types document as "Raised on the terminal and
 * desktop surfaces only". vscode and mobile list as surfaces but raise no
 * AbovePrompt, so the band never draws there (US-PM-62-8 reads this).
 */
export const BAND_SURFACES: readonly RenderSurface[] = ['terminal', 'desktop']

const TITLE_WIDTH = 60
const NOTE_WIDTH = 80
const SEP = ' · '

function clip(text: string, width: number): string {
  return text.length > width ? `${text.slice(0, width - 1)}…` : text
}

/** The active sprint's id from `pm_list_sprints(status=active)`, or null when none is active. */
export function activeSprintId(sprints: Yaml): string | null {
  const [first] = asRows(asMap(sprints).sprints)
  const id = first ? str(first.id) : ''
  return id === '' ? null : id
}

/** "Sprint 20 — The Project Asks" reads as "Sprint 20": the name up to its first dash. */
function shortName(name: string, id: string): string {
  const head = name.split(/\s+[—–-]\s+/)[0]?.trim() ?? ''
  return head || name.trim() || id
}

/** `pm_get_sprint`'s answer as live points: done stories' points over the planned total. */
export function sprintProgress(sprint: Yaml): ProjectmanBand['sprint'] {
  const s = asMap(sprint)
  const id = str(s.id)
  if (id === '' && s.name === undefined) return null
  const stories = asRows(s.story_progress)
  const done = stories.filter((r) => r.status === 'done').reduce((n, r) => n + (num(r.points) ?? 0), 0)
  const summed = stories.reduce((n, r) => n + (num(r.points) ?? 0), 0)
  const total = stories.length > 0 ? summed : (num(s.planned_points) ?? 0)
  return { name: shortName(str(s.name), id), donePoints: done, totalPoints: total }
}

/** The first in-progress task from `pm_active`, and how many more there are. */
export function taskInFlight(active: Yaml): ProjectmanBand['task'] {
  const a = asMap(active)
  const [first] = asRows(a.active_tasks)
  if (!first || str(first.id) === '') return null
  const total = num(a.active_tasks_total) ?? 1
  return { id: str(first.id), title: str(first.title), more: Math.max(0, total - 1) }
}

/**
 * The note's head from `pm_next`: its first line of text. A heading line
 * (`### 2026-10-21`, as an appended note opens) is passed over for the text
 * under it; a note of headings alone shows its first, the marks dropped.
 */
export function noteHead(next: Yaml): string | null {
  const note = asMap(next).note
  if (typeof note !== 'string') return null
  const lines = note.split('\n').map((l) => l.trim()).filter((l) => l !== '')
  const text = lines.find((l) => !l.startsWith('#')) ?? lines[0]?.replace(/^#+\s*/, '')
  return text ? text : null
}

/** The band from the MCP answers; null when no part has anything to show. */
export function bandFrom(sprint: Yaml, active: Yaml, next: Yaml): ProjectmanBand | null {
  const band: ProjectmanBand = {
    sprint: sprint === null ? null : sprintProgress(sprint),
    task: taskInFlight(active),
    note: noteHead(next),
  }
  return band.sprint === null && band.task === null && band.note === null ? null : band
}

/** Each part's text, in the order drawn. */
export function bandParts(band: ProjectmanBand): string[] {
  const parts: string[] = []
  if (band.sprint) parts.push(`${band.sprint.name} — ${band.sprint.donePoints}/${band.sprint.totalPoints} pts`)
  if (band.task) {
    const more = band.task.more > 0 ? ` (+${band.task.more} more)` : ''
    parts.push(`▶ ${band.task.id} ${clip(band.task.title, TITLE_WIDTH)}${more}`)
  }
  if (band.note) parts.push(`next: ${clip(band.note, NOTE_WIDTH)}`)
  return parts
}

/**
 * The band's lines for `bodyColumns`: one when it fits, else two, the note
 * (or, with no note, the task) on the second. Each line is cut at its end
 * where it is still too wide.
 */
export function bandLines(band: ProjectmanBand, bodyColumns: number): string[] {
  const parts = bandParts(band)
  const one = parts.join(SEP)
  if (parts.length < 2 || one.length <= bodyColumns) return [one]
  return [parts.slice(0, -1).join(SEP), parts[parts.length - 1] ?? '']
}

/** The elements the band draws with. */
export type BandElements = { Box: ElementConstructor<BoxProps>; Text: ElementConstructor<TextProps> }

/** The band's tree for `band`, `bodyColumns` wide. */
export function sprintBand({ Box, Text }: BandElements, band: ProjectmanBand, bodyColumns: number): RenderElement {
  return (
    <Box key={BAND_KEY} flexDirection="column">
      {bandLines(band, bodyColumns).map((line) => (
        <Text dimColor wrap="truncate-end">
          {line}
        </Text>
      ))}
    </Box>
  )
}
