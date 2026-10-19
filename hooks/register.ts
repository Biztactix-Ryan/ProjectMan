import type { Register, ToolCallInput } from 'claude-code'
import type { ProjectmanGuardDenial } from '../types'
import { findBannedGit, GIT_RULE_REASON } from './git-guard.ts'
import { absolutize, mentionsStore, STORE_RULE_REASON, storeHit, storeRoots, targetOf } from './store-guard.ts'
import type { ResolveFn } from './store-guard.ts'
import { formatCommand, MCP_SERVER_KEY, parseYaml, PM_COMMANDS, resultText } from './pm-views.ts'
import type { Yaml } from './pm-views.ts'

// ProjectMan orchestration guards (US-PM-59). Enforce the worker rules on tool
// calls in-process instead of in skill prose.
//
// Scope: a call made inside a subagent's loop (the event carries `agentId`) is
// guarded by default; the main session is guarded only when the
// `guard_main_session` userConfig option is on, so the interactive user is
// not blocked.

const lastDenial = { plugin: 'projectman', key: 'lastDenial' } as const

export const register: Register = (on, options) => {
  const guardMain = options.guard_main_session === true
  const inScope = (e: ToolCallInput) => e.agentId !== undefined || guardMain

  // US-PM-59-7: Bash running git checkout / restore / stash.
  const bannedGit = (e: ToolCallInput): string | undefined =>
    e.tool === 'Bash' && inScope(e) ? findBannedGit(e.command) : undefined

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const hit = bannedGit(e)
    if (hit === undefined) return next(e)
    const denial: ProjectmanGuardDenial = { rule: `git ${hit}`, tool: e.tool, reason: GIT_RULE_REASON }
    try {
      await $.state.set(lastDenial, denial)
    } catch {
      // Recording is a convenience; the refusal stands without it.
    }
    return { deny: GIT_RULE_REASON }
  }).catch(($, e, next) => {
    if (next.called) return next(e)
    // Re-entry or a failed hook: judge from `e` alone, refuse if unsure.
    try {
      return bannedGit(e) === undefined ? next(e) : { deny: GIT_RULE_REASON }
    } catch {
      return { deny: `${GIT_RULE_REASON} (the ProjectMan guard failed to read this command)` }
    }
  })

  // US-PM-59-8: Write / Edit / NotebookEdit (MultiEdit where a build has it)
  // aimed at the real .project store. MCP tools (mcp__projectman__*) are a
  // different tool name and never match.
  on('tool.call', { tool: ['Write', 'Edit', 'NotebookEdit', /^MultiEdit$/] }, async ($, e, next) => {
    if (!inScope(e)) return next(e)
    const target = targetOf(e as unknown as { tool: string } & Record<string, unknown>)
    if (target === undefined) return next(e)
    // Where a path lands, every link followed; undefined when it does not stat.
    const resolve: ResolveFn = (path) =>
      $.fs
        .stat(path, { resolve: true })
        .then((s) => s.realPath)
        .catch(() => undefined)
    const root = await $.session.root()
    const cwd = await $.session.cwd()
    const roots = await storeRoots([root, cwd], resolve)
    const hit = await storeHit(absolutize(target, cwd), roots, resolve)
    if (hit === undefined) return next(e)
    const denial: ProjectmanGuardDenial = { rule: 'store write', tool: e.tool, reason: STORE_RULE_REASON }
    try {
      await $.state.set(lastDenial, denial)
    } catch {
      // Recording is a convenience; the refusal stands without it.
    }
    return { deny: STORE_RULE_REASON }
  }).catch(($, e, next) => {
    if (next.called) return next(e)
    // Re-entry or a failed hook: judge the spelling alone, refuse if it names the store.
    try {
      if (!inScope(e)) return next(e)
      const target = targetOf(e as unknown as { tool: string } & Record<string, unknown>)
      return target !== undefined && mentionsStore(target) ? { deny: STORE_RULE_REASON } : next(e)
    } catch {
      return { deny: `${STORE_RULE_REASON} (the ProjectMan guard failed to read this call)` }
    }
  })

  // US-PM-60-6: /pm-board, /pm-status-view and /pm-next-task answer from the
  // projectman MCP server through `$.mcp.call`, with no model request, so a
  // check costs no tokens. `immediate` lets them run while a turn streams.
  on('session.start', async ($, e, next) => {
    for (const command of PM_COMMANDS) {
      await $.command.register({ name: command.name, description: command.description, immediate: true })
    }
    return next(e)
  })

  // The names spelled out so `claude plugin validate` reads the matcher; a
  // mod test holds them equal to PM_COMMANDS.
  on('command.run', { command: ['pm-board', 'pm-status-view', 'pm-next-task'] }, async ($, e, next) => {
    const command = PM_COMMANDS.find((c) => c.name === e.command)
    if (command === undefined) return next(e)
    const connected = await $.mcp.connect(MCP_SERVER_KEY)
    if (!connected.isConnected) {
      return { text: `ProjectMan: the projectman MCP server is not connected (${connected.message})` }
    }
    const results: Yaml[] = []
    for (const call of command.calls) {
      const answer = await $.mcp.call(connected.server, call.tool, call.args)
      const text = resultText(answer)
      if (answer.isError) return { text: `ProjectMan: ${call.tool} failed: ${text.trim() || 'no detail'}` }
      results.push(parseYaml(text))
    }
    return { text: formatCommand(command, results) }
  }).catch(($, e) => ({ text: `ProjectMan: /${e.command} failed to read the MCP server's answer` }))
}
