import { expect, test } from 'claude-code/testing'

test('the skeleton passes a tool call through unchanged', async ($, on) => {
  const seen: string[] = []
  on('tool.call', { tool: 'Bash' }, ($, e) => {
    seen.push(e.command)
    return { result: 'ran' }
  })

  const ran = await $.tool.call({ tool: 'Bash', command: 'git status' })

  expect(ran.deny).toBeUndefined()
  expect(ran.result).toBe('ran')
  expect(seen).toEqual(['git status'])
})
