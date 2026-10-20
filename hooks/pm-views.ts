// Board, status and next-task views (US-PM-60-6). Pure functions, no `$`:
// register.ts registers the slash commands, calls the projectman MCP server
// with `$.mcp.call` and hands the result here to be read and formatted. No
// model request is made anywhere on this path.
//
// The server answers in YAML (PyYAML `default_flow_style=False`, width
// 10000), so `parseYaml` reads that subset: block mappings and sequences,
// plain / single- / double-quoted / literal scalars, and the empty flow
// collections `[]` and `{}`. It is not a general YAML parser.

import type { ProjectmanBoardColumn, ProjectmanBoardTask } from '../types'

/** One slash command this module serves: its name, line and MCP calls. */
export type PmCommand = {
  name: string
  description: string
  /** The projectman MCP tools it calls, in order, with their arguments. */
  calls: readonly { tool: string; args: Record<string, unknown> }[]
}

// Names chosen not to clash with the plugin's skills (skills/pm, pm-status,
// pm-next, ...): /pm-status and /pm-next are skills already.
export const PM_BOARD: PmCommand = {
  name: 'pm-board',
  description: 'ProjectMan task board, read straight from the MCP server (no Claude turn)',
  calls: [{ tool: 'pm_board', args: { brief: true, limit: 10 } }],
}
export const PM_STATUS_VIEW: PmCommand = {
  name: 'pm-status-view',
  description: 'ProjectMan project status, read straight from the MCP server (no Claude turn)',
  calls: [{ tool: 'pm_status', args: {} }],
}
export const PM_NEXT_TASK: PmCommand = {
  name: 'pm-next-task',
  description: 'ProjectMan next ready task and the saved next-session note (no Claude turn)',
  calls: [
    { tool: 'pm_board', args: { brief: true, limit: 3 } },
    { tool: 'pm_next', args: {} },
  ],
}
export const PM_COMMANDS: readonly PmCommand[] = [PM_BOARD, PM_STATUS_VIEW, PM_NEXT_TASK]

/** The manifest key of the plugin's MCP server (`$.mcp.connect` takes it). */
export const MCP_SERVER_KEY = 'projectman'

// ---------------------------------------------------------------- results

type ContentBlock = { type: string; text?: string }
export type ToolResultLike = { content: readonly ContentBlock[]; isError: boolean; structuredContent?: unknown }

/**
 * The tool's text: its `text` blocks joined. FastMCP may also send the
 * string as `{"result": "..."}` (structured output); either is unwrapped.
 */
export function resultText(result: ToolResultLike): string {
  const structured = result.structuredContent as { result?: unknown } | undefined
  if (structured && typeof structured.result === 'string') return structured.result
  const text = result.content
    .filter((b) => b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text as string)
    .join('\n')
  const trimmed = text.trim()
  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as { result?: unknown }
      if (parsed && typeof parsed.result === 'string') return parsed.result
    } catch {
      // Not JSON: the text is the answer.
    }
  }
  return text
}

// ---------------------------------------------------------------- YAML subset

export type Yaml = null | boolean | number | string | Yaml[] | { [key: string]: Yaml }

type Line = { indent: number; text: string }
const BLANK: Line = { indent: -1, text: '' }

function toLines(src: string): Line[] {
  const out: Line[] = []
  for (const raw of src.replace(/\r\n?/g, '\n').split('\n')) {
    if (raw.trim() === '' || /^\s*#/.test(raw) || raw === '---' || raw === '...') {
      out.push({ indent: -1, text: '' }) // blank: kept for quoted/literal scalars
      continue
    }
    const indent = raw.length - raw.trimStart().length
    out.push({ indent, text: raw.trimEnd().slice(indent) })
  }
  return out
}

function isSeqItem(text: string): boolean {
  return text === '-' || text.startsWith('- ')
}

/** Index of the `: ` (or a final `:`) that ends a mapping key, outside quotes; -1 when none. */
function keyEnd(text: string): number {
  let i = 0
  if (text[0] === "'" || text[0] === '"') {
    const q = text[0]
    i = 1
    while (i < text.length) {
      if (q === "'" && text[i] === "'" && text[i + 1] === "'") i += 2
      else if (q === '"' && text[i] === '\\') i += 2
      else if (text[i] === q) break
      else i++
    }
    i++
  }
  for (; i < text.length; i++) {
    if (text[i] === ':' && (i + 1 === text.length || text[i + 1] === ' ')) return i
  }
  return -1
}

function plainScalar(s: string): Yaml {
  if (s === '' || s === '~' || s === 'null' || s === 'Null' || s === 'NULL') return null
  if (s === 'true' || s === 'True' || s === 'TRUE') return true
  if (s === 'false' || s === 'False' || s === 'FALSE') return false
  if (s === '[]') return []
  if (s === '{}') return {}
  if (/^[-+]?\d+$/.test(s)) return Number(s)
  if (/^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$/.test(s)) return Number(s)
  return s
}

const ESCAPES: Record<string, string> = { n: '\n', t: '\t', r: '\r', '0': '\0', '"': '"', '\\': '\\', '/': '/', ' ': ' ', _: ' ', e: '\u001b', a: '\u0007', b: '\b', f: '\f', v: '\v', N: '\u0085', L: ' ', P: ' ' }

/** Folds a quoted scalar's raw source (between the quotes) the YAML way. */
function foldQuoted(raw: string, double: boolean): string {
  // Line folding: a lone break is a space, n+1 breaks are n newlines; a
  // double-quoted line ending in `\` joins with no space.
  const parts = raw.split('\n')
  let out = ''
  let blanks = 0
  for (let i = 0; i < parts.length; i++) {
    const rawPart = parts[i] ?? ''
    let part = i === 0 ? rawPart : rawPart.trimStart()
    if (i < parts.length - 1) part = part.trimEnd()
    if (i > 0 && part === '' && i < parts.length - 1) {
      blanks++
      continue
    }
    if (i > 0) {
      const joinNoSpace = double && /(^|[^\\])(\\\\)*\\$/.test(out)
      if (joinNoSpace) out = out.slice(0, -1)
      else out += blanks > 0 ? '\n'.repeat(blanks) : ' '
    }
    blanks = 0
    out += part
  }
  if (!double) return out.replace(/''/g, "'")
  return out.replace(/\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)/g, (_, c: string) => {
    if (c.length > 1) return String.fromCodePoint(parseInt(c.slice(1), 16))
    return ESCAPES[c] ?? c
  })
}

/** Index just past the closing quote of a scalar opened at `src[0]`, or -1. */
function closingQuote(src: string): number {
  const q = src[0]
  for (let i = 1; i < src.length; i++) {
    if (q === "'" && src[i] === "'") {
      if (src[i + 1] === "'") i++
      else return i + 1
    } else if (q === '"' && src[i] === '\\') i++
    else if (q === '"' && src[i] === '"') return i + 1
  }
  return -1
}

class Parser {
  private i = 0
  constructor(private readonly lines: Line[]) {}

  private skipBlank(): void {
    while (this.i < this.lines.length && (this.lines[this.i]?.indent ?? 0) < 0) this.i++
  }

  private peek(): Line | undefined {
    this.skipBlank()
    return this.lines[this.i]
  }

  parseDocument(): Yaml {
    const first = this.peek()
    if (!first) return null
    return this.parseNode(first.indent)
  }

  private parseNode(indent: number): Yaml {
    const line = this.peek()
    if (!line || line.indent < indent) return null
    if (isSeqItem(line.text)) return this.parseSeq(line.indent)
    if (keyEnd(line.text) >= 0) return this.parseMap(line.indent)
    // A lone scalar (a document that is one value).
    return this.scalarAt(line.text, line.indent)
  }

  private parseSeq(indent: number): Yaml[] {
    const out: Yaml[] = []
    for (let line = this.peek(); line && line.indent === indent && isSeqItem(line.text); line = this.peek()) {
      const rest = line.text === '-' ? '' : line.text.slice(2).trimStart()
      const inner = indent + (line.text.length - rest.length)
      if (rest === '') {
        this.i++
        const next = this.peek()
        out.push(next && next.indent > indent ? this.parseNode(next.indent) : null)
      } else if (isSeqItem(rest) || keyEnd(rest) >= 0) {
        // `- key: value` opens a mapping (or `- - x` a sequence) at the item's column.
        this.lines[this.i] = { indent: inner, text: rest }
        out.push(this.parseNode(inner))
      } else {
        out.push(this.scalarAt(rest, indent))
      }
    }
    return out
  }

  private parseMap(indent: number): { [key: string]: Yaml } {
    const out: { [key: string]: Yaml } = {}
    for (let line = this.peek(); line && line.indent === indent && !isSeqItem(line.text); line = this.peek()) {
      const end = keyEnd(line.text)
      if (end < 0) break
      const rawKey = line.text.slice(0, end).trim()
      const key = rawKey[0] === "'" || rawKey[0] === '"' ? foldQuoted(rawKey.slice(1, -1), rawKey[0] === '"') : rawKey
      const rest = line.text.slice(end + 1).trim()
      if (rest === '') {
        this.i++
        const next = this.peek()
        if (next && (next.indent > indent || (next.indent === indent && isSeqItem(next.text)))) {
          out[key] = this.parseNode(next.indent)
        } else out[key] = null
      } else {
        out[key] = this.scalarAt(rest, indent)
      }
    }
    return out
  }

  /** Reads the scalar starting at `src` on the current line; consumes its lines. */
  private scalarAt(src: string, parentIndent: number): Yaml {
    if (src[0] === "'" || src[0] === '"') {
      let raw = src
      let close = closingQuote(raw)
      this.i++
      while (close < 0 && this.i < this.lines.length) {
        const l = this.lines[this.i++] ?? BLANK
        raw += '\n' + (l.indent < 0 ? '' : l.text)
        close = closingQuote(raw)
      }
      return foldQuoted(raw.slice(1, close < 0 ? raw.length : close - 1), src[0] === '"')
    }
    if (/^[|>][-+]?\d*$/.test(src)) {
      const chomp = src.includes('-') ? 'strip' : src.includes('+') ? 'keep' : 'clip'
      this.i++
      const body: string[] = []
      let blockIndent = -1
      while (this.i < this.lines.length) {
        const l = this.lines[this.i] ?? BLANK
        if (l.indent >= 0 && l.indent <= parentIndent) break
        if (l.indent >= 0 && blockIndent < 0) blockIndent = l.indent
        body.push(l.indent < 0 ? '' : ' '.repeat(l.indent - blockIndent) + l.text)
        this.i++
      }
      let text = src[0] === '>' ? body.join('\n').replace(/([^\n])\n(?=[^\n ])/g, '$1 ') : body.join('\n')
      if (chomp !== 'keep') text = text.replace(/\n+$/, '')
      return chomp === 'clip' && text !== '' ? text + '\n' : text
    }
    this.i++
    return plainScalar(src)
  }
}

/** Parses the YAML subset the projectman server writes. */
export function parseYaml(src: string): Yaml {
  return new Parser(toLines(src)).parseDocument()
}

// ---------------------------------------------------------------- formatting

export type Row = { [key: string]: Yaml }

export function asMap(v: Yaml | undefined): Row {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? v : {}
}
export function asRows(v: Yaml | undefined): Row[] {
  return Array.isArray(v) ? v.map(asMap) : []
}
export function num(v: Yaml | undefined): number | undefined {
  return typeof v === 'number' ? v : undefined
}
export function str(v: Yaml | undefined): string {
  return v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function pts(v: Yaml | undefined): string {
  const n = num(v)
  return n === undefined ? '' : ` [${n} pt${n === 1 ? '' : 's'}]`
}

function taskLine(row: Row): string {
  let line = `  ${str(row.id)}  ${str(row.title)}${pts(row.points)}`
  if (row.assignee) line += ` @${str(row.assignee)}`
  if (row.stale === true) line += ' (stale claim)'
  return line
}

const BOARD_GROUPS: readonly [key: string, label: string][] = [
  ['in_progress', 'In progress'],
  ['in_review', 'In review'],
  ['blocked', 'Blocked'],
  ['available', 'Available'],
  ['not_ready', 'Not ready'],
]

/** The board (`pm_board`'s answer, parsed) as transcript text. */
export function formatBoard(data: Yaml): string {
  const top = asMap(data)
  const board = asMap(top.board)
  const summary = asMap(top.summary)
  const counts = BOARD_GROUPS.map(([key, label]) => `${num(summary[key]) ?? asRows(board[key]).length} ${label.toLowerCase()}`)
  const out = [`ProjectMan board: ${counts.join(' · ')}`]
  for (const [key, label] of BOARD_GROUPS) {
    const rows = asRows(board[key])
    const total = num(summary[key]) ?? rows.length
    if (total === 0) continue
    out.push('', `${label} (${total})`)
    for (const row of rows) out.push(taskLine(row))
    if (total > rows.length) out.push(`  … and ${total - rows.length} more`)
  }
  const stale = Array.isArray(top.stale_tasks) ? top.stale_tasks.map(str) : []
  if (stale.length > 0) out.push('', `Stale claims: ${stale.join(', ')}`)
  return out.join('\n')
}

/** The board pane's columns (US-PM-60-7), in the order drawn. */
const PANE_COLUMNS: readonly [key: ProjectmanBoardColumn['key'], label: string][] = [
  ['available', 'Available'],
  ['in_progress', 'In progress'],
  ['blocked', 'Blocked'],
]

/** `pm_board`'s answer, parsed, as the pane's available / in progress / blocked columns. */
export function boardColumns(data: Yaml): ProjectmanBoardColumn[] {
  const top = asMap(data)
  const board = asMap(top.board)
  const summary = asMap(top.summary)
  const stale = new Set(Array.isArray(top.stale_tasks) ? top.stale_tasks.map(str) : [])
  return PANE_COLUMNS.map(([key, label]) => {
    const rows = asRows(board[key])
    const tasks: ProjectmanBoardTask[] = rows.map((row) => ({
      id: str(row.id),
      title: str(row.title),
      points: num(row.points) ?? null,
      assignee: row.assignee ? str(row.assignee) : null,
      isStale: row.stale === true || stale.has(str(row.id)),
    }))
    return { key, label, total: Math.max(num(summary[key]) ?? 0, tasks.length), tasks }
  })
}

/** The project status (`pm_status`'s answer, parsed) as transcript text. */
export function formatStatus(data: Yaml): string {
  const s = asMap(data)
  const name = str(s.project) || 'Project'
  const out = [`${name}: ${str(s.completion) || '?'} complete (${num(s.completed_points) ?? 0}/${num(s.total_points) ?? 0} pts)`]
  out.push(`${num(s.epics) ?? 0} epics · ${num(s.stories) ?? 0} stories · ${num(s.tasks) ?? 0} tasks`)
  const by = Object.entries(asMap(s.by_status))
  if (by.length > 0) out.push(`By status: ${by.map(([k, v]) => `${k} ${str(v)}`).join(' · ')}`)
  return out.join('\n')
}

/** The next ready task (from `pm_board`) and the saved note (`pm_next`) as text. */
export function formatNext(boardData: Yaml, noteData: Yaml): string {
  const top = asMap(boardData)
  const available = asRows(asMap(top.board).available)
  const out: string[] = []
  if (available.length === 0) {
    out.push('Next task: none ready. Run /pm-board to see what is in flight or not ready.')
  } else {
    const [first = {}, ...rest] = available
    out.push(`Next task: ${str(first.id)}  ${str(first.title)}${pts(first.points)}`)
    if (rest.length > 0) {
      out.push('Then:')
      for (const row of rest) out.push(taskLine(row))
    }
  }
  const note = asMap(noteData).note
  out.push('')
  if (typeof note === 'string' && note.trim() !== '') out.push('Note for the next session:', note.trimEnd())
  else out.push('No next-session note saved.')
  return out.join('\n')
}

/** Formats a command's MCP answers (one parsed result per call, in order). */
export function formatCommand(command: PmCommand, results: readonly Yaml[]): string {
  if (command === PM_BOARD) return formatBoard(results[0] ?? null)
  if (command === PM_STATUS_VIEW) return formatStatus(results[0] ?? null)
  return formatNext(results[0] ?? null, results[1] ?? null)
}

// ---------------------------------------------------------------- compact text
//
// US-PM-60-8: where no surface draws (VS Code chat, `claude -p`) a command
// answers with these instead of a pane: ids rather than titles, one line per
// group, a few lines in all.

/** How many ids a compact group lists before `+n more`. */
const COMPACT_IDS = 3
/** Where a compact line is cut (the note's first line, a task title). */
const COMPACT_WIDTH = 100

function clip(text: string): string {
  return text.length > COMPACT_WIDTH ? `${text.slice(0, COMPACT_WIDTH - 1)}…` : text
}

/** The board in a few lines: the counts, then the ids in each live group. */
export function summarizeBoard(data: Yaml): string {
  const top = asMap(data)
  const board = asMap(top.board)
  const summary = asMap(top.summary)
  const counts = BOARD_GROUPS.map(([key, label]) => `${num(summary[key]) ?? asRows(board[key]).length} ${label.toLowerCase()}`)
  const out = [`ProjectMan board: ${counts.join(' · ')}`]
  for (const [key, label] of BOARD_GROUPS) {
    if (key === 'not_ready') continue
    const ids = asRows(board[key]).map((row) => str(row.id))
    const total = num(summary[key]) ?? ids.length
    if (total === 0 || ids.length === 0) continue
    const shown = ids.slice(0, COMPACT_IDS)
    const more = total - shown.length
    out.push(`${label}: ${shown.join(', ')}${more > 0 ? ` (+${more} more)` : ''}`)
  }
  const stale = Array.isArray(top.stale_tasks) ? top.stale_tasks.map(str) : []
  if (stale.length > 0) out.push(`Stale claims: ${stale.join(', ')}`)
  return out.join('\n')
}

/** The project status on one line. */
export function summarizeStatus(data: Yaml): string {
  const s = asMap(data)
  const name = str(s.project) || 'Project'
  return (
    `${name}: ${str(s.completion) || '?'} complete (${num(s.completed_points) ?? 0}/${num(s.total_points) ?? 0} pts)` +
    ` · ${num(s.epics) ?? 0} epics · ${num(s.stories) ?? 0} stories · ${num(s.tasks) ?? 0} tasks`
  )
}

/** The next ready task and the note's first line, two lines. */
export function summarizeNext(boardData: Yaml, noteData: Yaml): string {
  const [first] = asRows(asMap(asMap(boardData).board).available)
  const out = [first ? clip(`Next task: ${str(first.id)}  ${str(first.title)}${pts(first.points)}`) : 'Next task: none ready.']
  const note = asMap(noteData).note
  if (typeof note === 'string' && note.trim() !== '') {
    const lines = note.trim().split('\n')
    const head = clip(`Note: ${(lines[0] ?? '').trim()}`)
    out.push(lines.length > 1 && !head.endsWith('…') ? `${head} …` : head)
  } else out.push('No next-session note saved.')
  return out.join('\n')
}

/** A command's compact text summary, for a surface that draws nothing. */
export function summarizeCommand(command: PmCommand, results: readonly Yaml[]): string {
  if (command === PM_BOARD) return summarizeBoard(results[0] ?? null)
  if (command === PM_STATUS_VIEW) return summarizeStatus(results[0] ?? null)
  return summarizeNext(results[0] ?? null, results[1] ?? null)
}
