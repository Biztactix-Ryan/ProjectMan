// Locates a Write/Edit/NotebookEdit target and tells whether it lies inside
// the real ProjectMan store (US-PM-59-8). No `$` here: the stat function is
// passed in, so the path logic is plain and testable; register.ts decides
// scope and answers the refusal.
//
// "The real store" is `<project root>/.project` (and `<cwd>/.project` when
// the session's cwd differs), resolved to its real path: symlinks followed,
// `.` and `..` folded. In this repo `.project` is a git worktree checkout;
// resolving it makes the comparison independent of how a tool spells it.
//
// A target is placed by its real path: the file itself when it exists, else
// its nearest existing ancestor resolved plus the missing tail folded
// lexically (the missing directories will be created as plain directories,
// so `..` in the tail lands where the fold says). Only a target placed under
// a resolved store is refused; a tmp_path fixture's own `.project`, or a
// sibling like `.project-backup/` or `my.project/`, resolves elsewhere.

export const STORE_RULE_REASON =
  'ProjectMan worker rule: never write to the real .project store directly — ' +
  'use the pm MCP tools; tests must use a tmp_path store.'

export const STORE_DIR = '.project'

/** Answers where a path lands (`realPath`), or undefined when it cannot stat it. */
export type ResolveFn = (path: string) => Promise<string | undefined>

/** The tools whose target file the guard checks, and the field naming it. */
export const GUARDED_TOOLS = {
  Write: 'file_path',
  Edit: 'file_path',
  MultiEdit: 'file_path',
  NotebookEdit: 'notebook_path',
} as const

/** The target path a guarded tool call names, if it names one. */
export function targetOf(e: { tool: string } & Record<string, unknown>): string | undefined {
  const field = (GUARDED_TOOLS as Record<string, string>)[e.tool]
  const value = field === undefined ? undefined : e[field]
  return typeof value === 'string' ? value : undefined
}

const SEP = /[\\/]/

function sepOf(path: string): string {
  return path.includes('\\') && !path.includes('/') ? '\\' : '/'
}

function trimSep(path: string): string {
  return path.length > 1 ? path.replace(/[\\/]+$/, '') : path
}

/** True when `real` is `root` itself or lies beneath it. */
export function isUnder(real: string, root: string): boolean {
  const r = trimSep(root)
  const p = trimSep(real)
  if (p === r) return true
  const base = /[\\/]$/.test(r) ? r : r + sepOf(r)
  return p.startsWith(base)
}

/** `path` made absolute against `cwd` when it is relative (as the tools read it). */
export function absolutize(path: string, cwd: string): string {
  if (path === '' || /^[\\/]/.test(path) || /^[A-Za-z]:/.test(path)) return path
  return `${trimSep(cwd)}${sepOf(cwd)}${path}`
}

/** True when some segment of the spelling is exactly `.project`. */
export function mentionsStore(path: string): boolean {
  return path.split(SEP).includes(STORE_DIR)
}

/**
 * Where `path` lands: its own real path when it exists, else the nearest
 * existing ancestor's real path joined with the missing tail (`.` folded).
 * `..` is applied to the real path of what precedes it, as the kernel does.
 * Undefined when no ancestor resolves.
 */
export async function placePath(path: string, resolve: ResolveFn, depth = 0): Promise<string | undefined> {
  if (path === '' || depth > 32) return undefined
  // `..` after a symlink climbs from where the link lands (the kernel's
  // order), not from its spelling, and $.fs.stat folds `..` by spelling
  // first: so place what comes before the first `..`, then go on from that
  // real path's parent.
  const segs = path.split(SEP)
  const up = segs.indexOf('..')
  if (up > 0) {
    const head = await placePath(segs.slice(0, up).join('/') || '/', resolve, depth + 1)
    if (head === undefined) return undefined
    const parent = head.replace(/[\\/][^\\/]*$/, '') || '/'
    const rest = segs.slice(up + 1).join('/')
    return placePath(rest ? `${trimSep(parent)}/${rest}` : parent, resolve, depth + 1)
  }
  const own = await resolve(path)
  if (own !== undefined) return own

  const absolute = /^[\\/]/.test(path) || /^[A-Za-z]:[\\/]/.test(path)
  const parts = path.split(SEP)
  const tail: string[] = []
  while (parts.length > 0) {
    tail.unshift(parts.pop() as string)
    let folder = parts.join('/')
    if (folder === '') folder = absolute ? '/' : '.'
    if (/^[A-Za-z]:$/.test(folder)) folder += '/'
    const base = await resolve(folder)
    if (base === undefined) {
      if (folder === '.' || folder === '/' || /^[A-Za-z]:\/$/.test(folder)) return undefined
      continue
    }
    const sep = sepOf(base)
    const out = trimSep(base).split(SEP)
    const rootPrefix = out[0] === '' ? [''] : /^[A-Za-z]:$/.test(out[0] ?? '') ? [out[0] as string] : []
    let folded = false
    for (const seg of tail) {
      if (seg === '' || seg === '.') continue
      if (seg === '..') {
        folded = true
        if (out.length > rootPrefix.length) out.pop()
      } else out.push(seg)
    }
    const raw = out.join(sep)
    const joined = raw === '' || /^[A-Za-z]:$/.test(raw) ? raw + sep : raw
    // A `..` may have climbed back onto existing ground (a symlink, the
    // store): place the folded spelling again.
    return folded ? placePath(joined, resolve, depth + 1) : joined
  }
  return undefined
}

/**
 * `path` with `.` and `..` folded by spelling alone, the way a tool that
 * normalises its path before opening it reads it; `..` above a relative
 * start is kept.
 */
export function foldLexically(path: string): string {
  const absolute = /^[\\/]/.test(path)
  const out: string[] = []
  for (const seg of path.split(SEP)) {
    if (seg === '' || seg === '.') continue
    if (seg === '..' && out.length > 0 && out[out.length - 1] !== '..') out.pop()
    else if (seg !== '..' || !absolute) out.push(seg)
  }
  const body = out.join('/')
  return absolute ? '/' + body : body === '' ? '.' : body
}

/**
 * The resolved store roots for the given project directories: each
 * `<dir>/.project` that exists, by real path, without duplicates.
 */
export async function storeRoots(dirs: readonly string[], resolve: ResolveFn): Promise<string[]> {
  const roots: string[] = []
  for (const dir of new Set(dirs)) {
    const real = await resolve(`${trimSep(dir)}/${STORE_DIR}`)
    if (real !== undefined && !roots.includes(real)) roots.push(real)
  }
  return roots
}

/** The store root `path` lands under, or undefined when it lands outside all. */
export async function storeHit(
  path: string,
  roots: readonly string[],
  resolve: ResolveFn,
): Promise<string | undefined> {
  if (roots.length === 0) return undefined
  // Read both ways a tool may open it: as given (links first, then `..`, as
  // the kernel does) and folded by spelling first (as a normalising tool does).
  const spellings = [path]
  if (!/^[A-Za-z]:/.test(path)) {
    const folded = foldLexically(path)
    if (folded !== path) spellings.push(folded)
  }
  for (const spelling of spellings) {
    const real = await placePath(spelling, resolve)
    // Unplaceable: refuse only a spelling that names the store.
    if (real === undefined) {
      if (mentionsStore(spelling)) return STORE_DIR
      continue
    }
    const hit = roots.find((root) => isUnder(real, root))
    if (hit !== undefined) return hit
  }
  return undefined
}
