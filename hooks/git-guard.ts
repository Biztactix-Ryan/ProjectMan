// Detects shell commands that run `git checkout`, `git restore` or
// `git stash` (US-PM-59-7). Pure functions, no `$`: the tool.call hook in
// register.ts decides scope and answers the refusal.
//
// Best-effort shell reading, not a full parser:
// - the command is split into simple commands on `&&`, `||`, `;`, `|`, `&`,
//   newlines, `(`, `)`, `{`/`}` words, `$(...)` and backticks;
// - quoted text stays one literal word, so `echo "git stash"` and
//   `git commit -m 'no git checkout'` pass; command substitutions inside
//   double quotes (`"$(git stash)"`) are still read as commands;
// - `bash -c '...'` / `sh -c` / `eval ...` scripts are read recursively;
// - leading `VAR=value` assignments and `env`, `command`, `exec`, `sudo`,
//   `nohup`, `time`, `nice` prefixes are skipped;
// - git's global options before the subcommand (`-C path`, `-c k=v`,
//   `--no-pager`, `--git-dir=...`) are skipped.
// `git stash` is refused in every form, `stash list`/`show` included: the
// worker rule bans stash outright and a worker has no need to read stashes.

export const BANNED_GIT_SUBCOMMANDS = ['checkout', 'restore', 'stash'] as const

export const GIT_RULE_REASON =
  'ProjectMan worker rule: never run git checkout, git restore or git stash — ' +
  "earlier tasks' uncommitted work lives in the working tree " +
  'and these commands discard it. Undo your own edits with the Edit/Write tools instead.'

const SEPARATOR = Symbol('separator')
type Token = string | typeof SEPARATOR

const GIT_OPTS_WITH_ARG = new Set([
  '-C',
  '-c',
  '--git-dir',
  '--work-tree',
  '--namespace',
  '--super-prefix',
  '--config-env',
])
const PREFIX_COMMANDS = new Set(['env', 'command', 'exec', 'sudo', 'nohup', 'time', 'nice', 'builtin'])
const SHELL_KEYWORDS = new Set(['!', 'if', 'then', 'else', 'elif', 'do', 'while', 'until', '{', '}'])
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh'])
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/
const REDIRECT = /^\d*(?:[<>]|&>)/

/** Reads `src` from `start` (just past the opener) to the matching `)`. */
function readParenGroup(src: string, start: number): [string, number] {
  let depth = 1
  let i = start
  let quote: string | null = null
  for (; i < src.length; i++) {
    const c = src[i]
    if (quote) {
      if (c === '\\' && quote === '"') i++
      else if (c === quote) quote = null
      continue
    }
    if (c === '\\') i++
    else if (c === "'" || c === '"') quote = c
    else if (c === '(') depth++
    else if (c === ')' && --depth === 0) break
  }
  return [src.slice(start, i), i]
}

/** Splits a command line into words and separators; collects nested scripts. */
function tokenize(src: string, nested: string[]): Token[] {
  const tokens: Token[] = []
  let word = ''
  let inWord = false
  const endWord = () => {
    if (inWord) tokens.push(word)
    word = ''
    inWord = false
  }
  const sep = () => {
    endWord()
    tokens.push(SEPARATOR)
  }

  for (let i = 0; i < src.length; i++) {
    const c = src[i]
    if (c === '\\') {
      if (src[i + 1] === '\n') {
        i++
        continue
      }
      word += src[i + 1] ?? ''
      inWord = true
      i++
    } else if (c === "'") {
      const end = src.indexOf("'", i + 1)
      const stop = end === -1 ? src.length : end
      word += src.slice(i + 1, stop)
      inWord = true
      i = stop
    } else if (c === '"') {
      inWord = true
      for (i++; i < src.length && src[i] !== '"'; i++) {
        const d = src[i]
        if (d === '\\') {
          word += src[i + 1] ?? ''
          i++
        } else if (d === '$' && src[i + 1] === '(') {
          const [inner, end] = readParenGroup(src, i + 2)
          nested.push(inner)
          word += '$(...)'
          i = end
        } else if (d === '`') {
          const end = src.indexOf('`', i + 1)
          const stop = end === -1 ? src.length : end
          nested.push(src.slice(i + 1, stop))
          word += '`...`'
          i = stop
        } else word += d
      }
    } else if (c === '#' && !inWord) {
      while (i < src.length && src[i] !== '\n') i++
      sep()
    } else if (c === ' ' || c === '\t') {
      endWord()
    } else if (c === '\n' || c === ';' || c === '|' || c === '(' || c === ')' || c === '`') {
      sep()
    } else if (c === '&') {
      // `2>&1` / `>&2` stay part of the redirection word.
      if (inWord && /[<>]$/.test(word)) word += c
      else sep()
    } else if (c === '$' && src[i + 1] === '(') {
      sep()
      i++ // the `(` ; the closing `)` is a separator too
    } else {
      word += c
      inWord = true
    }
  }
  endWord()
  return tokens
}

function splitCommands(tokens: Token[]): string[][] {
  const commands: string[][] = []
  let current: string[] = []
  for (const t of tokens) {
    if (t === SEPARATOR) {
      if (current.length) commands.push(current)
      current = []
    } else current.push(t)
  }
  if (current.length) commands.push(current)
  return commands
}

function basename(word: string): string {
  return word.slice(word.lastIndexOf('/') + 1)
}

/** The banned git subcommand a simple command runs, if any. */
function bannedInSimple(words: string[], nested: string[]): string | undefined {
  const at = (j: number): string => words[j] ?? ''
  let i = 0
  const skipRedirects = () => {
    while (i < words.length && REDIRECT.test(at(i))) {
      // `> file` (operator alone) also consumes its target.
      i += /^\d*(?:[<>]{1,2}|&>)$/.test(at(i)) ? 2 : 1
    }
  }
  for (;;) {
    skipRedirects()
    if (i >= words.length) return undefined
    const w = at(i)
    if (ASSIGNMENT.test(w) || SHELL_KEYWORDS.has(w)) {
      i++
      continue
    }
    if (PREFIX_COMMANDS.has(basename(w))) {
      i++
      while (i < words.length && (at(i).startsWith('-') || ASSIGNMENT.test(at(i)) || /^\d+$/.test(at(i)))) i++
      continue
    }
    break
  }

  const cmd = basename(at(i))
  if (SHELLS.has(cmd)) {
    for (let j = i + 1; j < words.length; j++) {
      if (/^-[A-Za-z]*c[A-Za-z]*$/.test(at(j)) && j + 1 < words.length) {
        nested.push(at(j + 1))
        break
      }
    }
    return undefined
  }
  if (cmd === 'eval') {
    nested.push(words.slice(i + 1).join(' '))
    return undefined
  }
  if (cmd !== 'git') return undefined

  for (i++; i < words.length; i++) {
    const w = at(i)
    if (GIT_OPTS_WITH_ARG.has(w)) {
      i++
      continue
    }
    if (w.startsWith('-') || REDIRECT.test(w)) continue
    return (BANNED_GIT_SUBCOMMANDS as readonly string[]).includes(w) ? w : undefined
  }
  return undefined
}

/**
 * The banned git subcommand (`checkout`, `restore` or `stash`) the shell
 * command runs anywhere in it, or undefined when it runs none.
 */
export function findBannedGit(command: string, depth = 0): string | undefined {
  if (depth > 4) return undefined
  const nested: string[] = []
  for (const words of splitCommands(tokenize(command, nested))) {
    const hit = bannedInSimple(words, nested)
    if (hit) return hit
  }
  for (const inner of nested) {
    const hit = findBannedGit(inner, depth + 1)
    if (hit) return hit
  }
  return undefined
}
