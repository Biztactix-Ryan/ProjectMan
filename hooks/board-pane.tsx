import type { BoxProps, ButtonProps, ElementConstructor, RenderElement, TextProps } from 'claude-code'
import type { ProjectmanBoardColumn, ProjectmanBoardTask, ProjectmanBoardView } from '../types'

// The board pane's tree (US-PM-60-7): a header with the refresh button, then
// the available / in progress / blocked columns side by side, stacked where
// the pane is too narrow for three. Drawn from `projectman.board` alone;
// register.ts reads that value and hands the refresh in, so this file holds
// no `$` and draws the same on every surface (only Box, Text and Button,
// which every surface's table carries).

/** The id the board pane is opened under and its `ui.render` matcher names. */
export const BOARD_PANE = 'pm-board'
export const BOARD_PANE_TITLE = 'ProjectMan board'
/** /pm-board's answer once the pane is drawn. */
export const BOARD_OPENED = 'ProjectMan board opened in a pane; press Refresh there to read it again.'

/** The keys a test (or another plugin) addresses the pane's elements by. */
export const REFRESH_KEY = 'refresh'
export const COLUMNS_KEY = 'columns'
export const columnKey = (key: ProjectmanBoardColumn['key']): string => `col-${key}`

/** Below this many body columns the three columns stack. */
const STACK_BELOW = 72
const GAP = 2

/** The elements the pane draws with: the part of any surface's table it uses. */
export type PaneElements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Button: ElementConstructor<ButtonProps>
}

function taskText(task: ProjectmanBoardTask): string {
  let text = `${task.id}  ${task.title}`
  if (task.points !== null) text += ` [${task.points}]`
  if (task.assignee) text += ` @${task.assignee}`
  if (task.isStale) text += ' (stale)'
  return text
}

function statusText(view: ProjectmanBoardView | null): string {
  if (view === null) return 'Not read yet.'
  if (view.isRefreshing) return 'Refreshing…'
  return `Read ${view.loads} time${view.loads === 1 ? '' : 's'} this session.`
}

/** The pane's tree for `view`, `bodyColumns` wide; `onRefresh` re-reads the board. */
export function boardPane(
  { Box, Text, Button }: PaneElements,
  view: ProjectmanBoardView | null,
  bodyColumns: number,
  onRefresh: () => void,
): RenderElement {
  const stacked = bodyColumns < STACK_BELOW
  const columnWidth = stacked ? undefined : Math.max(10, Math.floor((bodyColumns - GAP * 2) / 3))
  const columns = view?.columns ?? []
  return (
    <Box key="pm-board" flexDirection="column">
      <Box flexDirection="row" justifyContent="space-between" gap={GAP}>
        <Text dimColor>{statusText(view)}</Text>
        <Button key={REFRESH_KEY} label={view?.isRefreshing ? 'Refreshing…' : 'Refresh'} hotkey="r" onPress={onRefresh} />
      </Box>
      {view?.error ? <Text color="error">{view.error}</Text> : null}
      {view === null ? <Text dimColor>Press Refresh to read the board from the projectman MCP server.</Text> : null}
      <Box key={COLUMNS_KEY} flexDirection={stacked ? 'column' : 'row'} gap={stacked ? 1 : GAP}>
        {columns.map((column) => (
          <Box key={columnKey(column.key)} flexDirection="column" width={columnWidth} flexShrink={1}>
            <Text bold>{`${column.label} (${column.total})`}</Text>
            {column.tasks.length === 0 ? <Text dimColor>none</Text> : null}
            {column.tasks.map((task) => (
              <Text color={task.isStale ? 'warning' : undefined} wrap="truncate-end">
                {taskText(task)}
              </Text>
            ))}
            {column.total > column.tasks.length ? (
              <Text dimColor>{`… and ${column.total - column.tasks.length} more`}</Text>
            ) : null}
          </Box>
        ))}
      </Box>
    </Box>
  )
}
