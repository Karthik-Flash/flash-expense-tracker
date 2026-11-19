// The app's data: the snapshot (D-088), shown from the phone copy at once and refreshed in
// the background (D-089). One refresh at a time; a request made while one runs is run once
// after it. Launch timings stay on the device (D-090).

import { useSyncExternalStore } from 'react'

import type { Api } from '../api/client.ts'
import { SCHEMA_VERSION, type Snapshot } from '../api/types.ts'
import { dayLabel, timeLabel, today } from '../lib/dates.ts'
import { addTiming, readLocal, saveLocal, touchLocal, wipeLocal, type Meta, type Timing } from './local.ts'

const REFRESH_EVERY_MS = 5 * 60_000
const TIMEOUT_MS = 90_000
const SLOW_MS = 3000 // no phone copy yet: "Starting up" after this long
const COLD_MS = 10_000

/** What a screen gets: the snapshot, or why it is not there yet. */
export type Load<T> =
  | { status: 'loading'; slow: boolean }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

export interface DataState {
  snapshot: Snapshot | null
  /** When the server last confirmed what is shown (ms since the epoch). */
  fetchedAt: number | null
  refreshing: boolean
  /** The last refresh failed; what is shown is older. */
  failed: boolean
  error: string
  /** The first snapshot is slow to come (no phone copy). */
  slow: boolean
}

const EMPTY: DataState = { snapshot: null, fetchedAt: null, refreshing: false, failed: false, error: '', slow: false }

interface Session {
  api: Api
  user: string
  meta: Meta | null
  /** What is shown came from the phone copy, not yet from the server. */
  fromLocal: boolean
  /** This launch, until its first refresh ends. */
  launch: { at: number; local_ms: number | null } | null
  running: Promise<void> | null
  again: boolean
  controller: AbortController | null
  stop: () => void
}

let state = EMPTY
let session: Session | null = null
const listeners = new Set<() => void>()

function set(patch: Partial<DataState>): void {
  state = { ...state, ...patch }
  for (const listener of listeners) listener()
}

/** IndexedDB can be missing (a private window): then the app runs from memory. */
async function safe<T>(work: () => Promise<T>): Promise<T | null> {
  try {
    return await work()
  } catch {
    return null
  }
}

/** Refresh on return to the app, when the network comes back, and every 5 min while visible. */
function watch(): () => void {
  if (typeof document === 'undefined') return () => {}
  const visible = () => document.visibilityState === 'visible' && void refresh()
  const online = () => void refresh()
  document.addEventListener('visibilitychange', visible)
  window.addEventListener('online', online)
  const timer = setInterval(visible, REFRESH_EVERY_MS)
  return () => {
    document.removeEventListener('visibilitychange', visible)
    window.removeEventListener('online', online)
    clearInterval(timer)
  }
}

/** After login: show the phone copy of this login at once, then refresh. */
export async function startData(api: Api, user: string): Promise<void> {
  if (session?.api === api && session.user === user) return
  if (session) await clearData()
  const s: Session = {
    api,
    user,
    meta: null,
    fromLocal: false,
    launch: { at: Date.now(), local_ms: null },
    running: null,
    again: false,
    controller: null,
    stop: watch(),
  }
  session = s
  const local = await safe(readLocal)
  if (session !== s) return
  const usable = local && local.meta.user_id === user && local.meta.schema_version === SCHEMA_VERSION && local.snapshot.schema_version === SCHEMA_VERSION
  if (usable) {
    s.meta = local.meta
    s.fromLocal = true
    set({ snapshot: local.snapshot, fetchedAt: local.meta.fetched_at })
  } else if (local) {
    await safe(wipeLocal) // another login or another schema: never show it
  }
  void refresh()
}

/** One refresh at a time. Asked while one runs, it runs once more afterwards. */
export function refresh(): Promise<void> {
  const s = session
  if (!s) return Promise.resolve()
  if (s.running) {
    s.again = true
    return s.running
  }
  s.running = (async () => {
    do {
      s.again = false
      await pull(s)
    } while (s.again && session === s)
  })().finally(() => {
    s.running = null
  })
  return s.running
}

async function pull(s: Session): Promise<void> {
  const controller = new AbortController()
  s.controller = controller
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS)
  const slow = state.snapshot ? undefined : setTimeout(() => session === s && set({ slow: true }), SLOW_MS)
  set({ refreshing: true })
  const started = performance.now()
  let result: Timing['result'] = 'error'
  let bytes: number | null = null
  try {
    const answer = await s.api.snapshot(state.snapshot ? (s.meta?.etag ?? null) : null, controller.signal)
    if (session !== s) return
    const now = Date.now()
    if (answer.status === 304) {
      result = '304'
      if (s.meta) s.meta = { ...s.meta, fetched_at: now }
      s.fromLocal = false
      set({ fetchedAt: now, failed: false, error: '' })
      await safe(() => touchLocal(now))
    } else {
      if (answer.snapshot.schema_version !== SCHEMA_VERSION) throw new Error('The app needs an update. Close it and open it again.')
      result = '200'
      bytes = answer.bytes
      const meta: Meta = { etag: answer.etag, fetched_at: now, owner_id: answer.snapshot.owner_id, user_id: s.user, schema_version: SCHEMA_VERSION }
      if (s.meta && s.meta.owner_id !== meta.owner_id) await safe(wipeLocal)
      s.meta = meta
      s.fromLocal = false
      set({ snapshot: answer.snapshot, fetchedAt: now, failed: false, error: '' })
      await safe(() => saveLocal(answer.snapshot, meta))
    }
  } catch (e) {
    if (session !== s) return
    result = controller.signal.aborted ? 'timeout' : 'error'
    const message = result === 'timeout' ? 'The server took too long to answer. Try again.' : e instanceof Error ? e.message : 'Could not load.'
    set({ failed: true, error: message })
  } finally {
    clearTimeout(timeout)
    clearTimeout(slow)
    if (session === s) {
      s.controller = null
      set({ refreshing: false, slow: false })
    }
  }
  const launch = s.launch
  if (!launch) return
  s.launch = null
  const requestMs = Math.round(performance.now() - started)
  const fresh = result === '200' || result === '304' ? Math.round(performance.now()) : null
  await safe(() =>
    addTiming({ at: launch.at, local_ms: launch.local_ms, fresh_ms: fresh, request_ms: requestMs, result, bytes, cold: requestMs > COLD_MS }),
  )
}

/** Home calls this once it is drawn: the launch's local_ms, when drawn from the phone copy. */
export function noteHomeDrawn(): void {
  const launch = session?.launch
  if (launch && launch.local_ms === null && session?.fromLocal) launch.local_ms = Math.round(performance.now())
}

/** Sign-out or another login: stop, forget, and delete the phone copy. */
export async function clearData(): Promise<void> {
  const s = session
  session = null
  s?.stop()
  s?.controller?.abort()
  set(EMPTY)
  await safe(wipeLocal)
}

export function dataState(): DataState {
  return state
}

const subscribe = (onChange: () => void) => {
  listeners.add(onChange)
  return () => void listeners.delete(onChange)
}

export function useData(): DataState {
  return useSyncExternalStore(subscribe, dataState)
}

const retry = () => void refresh()

/** The snapshot as a load: ready from the phone copy or the server, else loading or failed. */
export function useSnapshot(): [Load<Snapshot>, () => void] {
  const d = useData()
  if (d.snapshot) return [{ status: 'ready', data: d.snapshot }, retry]
  if (d.failed && !d.refreshing) return [{ status: 'error', message: d.error }, retry]
  return [{ status: 'loading', slow: d.slow }, retry]
}

/** "just now", "5 min ago", "2 h ago", "yesterday 21:40", "Tue 17 Nov 21:40" (IST). */
export function agoPhrase(then: number, now = Date.now()): string {
  const minutes = Math.floor((now - then) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (today(then) === today(now)) return `${Math.floor(minutes / 60)} h ago`
  const iso = new Date(then).toISOString()
  if (today(then) === today(now - 86_400_000)) return `yesterday ${timeLabel(iso)}`
  return `${dayLabel(iso)} ${timeLabel(iso)}`
}

/** The muted line under the month: how fresh the numbers are. */
export function freshnessLine(d: Pick<DataState, 'fetchedAt' | 'refreshing' | 'failed'>, now = Date.now()): string {
  if (d.refreshing) return 'Updating…'
  if (d.fetchedAt === null) return ''
  const when = agoPhrase(d.fetchedAt, now)
  return d.failed ? `Offline · showing data from ${when}` : `Updated ${when}`
}

/** The Speed sheet's table: time (IST), phone copy in ms, fresh data in s, result. */
export function speedRows(timings: Timing[]): { when: string; local: string; fresh: string; result: string }[] {
  return timings.map((t) => {
    const iso = new Date(t.at).toISOString()
    return {
      when: `${dayLabel(iso)} ${timeLabel(iso)}`,
      local: t.local_ms === null ? '–' : `${t.local_ms} ms`,
      fresh: t.fresh_ms === null ? '–' : `${(t.fresh_ms / 1000).toFixed(1)} s`,
      result: t.cold ? `${t.result}, cold` : t.result,
    }
  })
}
