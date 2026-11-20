// How each launch started (D-095): the path to the first screen, the time to it, and the
// last boot errors. Kept in localStorage on this device only, for the Speed sheet; it is
// read by index.html too, which writes its own error when the app's code never starts.

export type BootPath = 'local copy' | 'online' | 'login' | 'error screen'

export interface BootRecord {
  /** ms since the epoch, when the launch started. */
  at: number
  path: BootPath
  /** Navigation start to the first screen. */
  paint_ms: number
}

export interface BootError {
  at: number
  message: string
}

export interface BootLog {
  last: BootRecord | null
  /** Newest first, at most 5. */
  errors: BootError[]
}

const KEY = 'flash-boot'
const KEEP_ERRORS = 5
/** Nothing drawn this long after start: draw the best state there is. */
export const WATCHDOG_MS = 3000

const startedAt = Date.now()
let painted: BootPath | null = null

export function readBoot(): BootLog {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<BootLog>
    return { last: raw.last ?? null, errors: Array.isArray(raw.errors) ? raw.errors.slice(0, KEEP_ERRORS) : [] }
  } catch {
    return { last: null, errors: [] }
  }
}

function write(log: BootLog): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(log))
  } catch {
    // Storage blocked: the launch still works, it is just not recorded.
  }
}

/** The first screen of this launch is up. Later calls change nothing. */
export function markPainted(path: BootPath): void {
  if (painted) return
  painted = path
  write({ ...readBoot(), last: { at: startedAt, path, paint_ms: Math.round(performance.now()) } })
}

/** This launch's path so far; null until the first screen. */
export function bootPath(): BootPath | null {
  return painted
}

/** Sign-out or another login: this device's boot record goes with the phone copy (4E). */
export function clearBoot(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Storage blocked: nothing was kept.
  }
}

export function noteBootError(message: string): void {
  const log = readBoot()
  write({ ...log, errors: [{ at: Date.now(), message: message.slice(0, 300) }, ...log.errors].slice(0, KEEP_ERRORS) })
}

/** After `ms`, when nothing is drawn yet, note it and call `fire`. Returns a cancel. */
export function startWatchdog(fire: () => void, ms = WATCHDOG_MS): () => void {
  const timer = setTimeout(() => {
    if (painted) return
    noteBootError(`Nothing drawn ${ms / 1000} s after start`)
    fire()
  }, ms)
  return () => clearTimeout(timer)
}
