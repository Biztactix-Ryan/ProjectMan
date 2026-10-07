// ProjectMan mod type contract (named in .claude-plugin/plugin.json "types").
// Declares the session values the hooks module keeps in $.state; the guards
// added by US-PM-59-7/8 record their last refusal here.

export type ProjectmanGuardDenial = {
  rule: string
  tool: string
  reason: string
}

declare module 'claude-code' {
  interface PluginState {
    projectman: { lastDenial: ProjectmanGuardDenial | null }
  }
}
