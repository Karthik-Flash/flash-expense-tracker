// The app's data: the snapshot (D-088), shown from the phone copy at once and refreshed in
// the background (D-089). One refresh at a time; a request made while one runs is run once
// after it. Launch timings stay on the device (D-090).

import { useSyncExternalStore } from 'react'

import type { Api } from '../api/client.ts'
import { bootPath } from '../boot.ts'
import { SCHEMA_VERSION, type Snapshot } from '../api/types.ts'
import { dayLabel, timeLabel, today } from '../lib/dates.ts'
import { addTiming, dropSnapshot, readLocal, saveLocal, touchLocal, wipeLocal, type Meta, type Timing } from './local.ts'

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
  /** What is shown came from the phone copy, not yet from the server. */
  local: boolean
}

const EMPTY: DataState = { snapshot: null, fetchedAt: null, refreshing: false, failed: false, error: '', slow: false, local: false }

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
  /** While the phone copy is being read: stop waiting for it (the boot watchdog). */
  settle: (() => void) | null
}

let state = EMPTY
let session: Session | null = null
const listeners = new Set<() => void>()
const appliedHooks = new Set<(ask: number) => void>()
let asks = 0

/** How many snapshot requests have been started: a later request has a higher number. */
export const asksSoFar = () => asks
const resetHooks = new Set<() => void>()

/** After a snapshot (200 or 304) is applied; `ask` is the number of its request. */
export function onApplied(hook: (ask: number) => void): void {
  appliedHooks.add(hook)
}

/** When the data stops: sign-out, a lost session, another login. */
export function onReset(hook: () => void): void {
  resetHooks.add(hook)
}

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
    settle: null,
  }
  session = s
  const local = await new Promise<Awaited<ReturnType<typeof readLocal>> | 'late'>((resolve) => {
    s.settle = () => resolve('late')
    void safe(readLocal).then(resolve)
  })
  s.settle = null
  if (session !== s) return
  if (local === 'late') {
    // ponytail: IndexedDB did not answer within the boot watchdog (D-095): go to the server
    // and leave what is stored alone. A stuck database is not a reason to wipe it.
  } else if (!local || local.meta.user_id !== user) {
    await safe(wipeLocal) // another login (or nothing to say whose it is): never show it
  } else if (local.snapshot && local.meta.schema_version === SCHEMA_VERSION && local.snapshot.schema_version === SCHEMA_VERSION) {
    s.meta = local.meta
    s.fromLocal = true
    set({ snapshot: local.snapshot, fetchedAt: local.meta.fetched_at, local: true })
  } else {
    s.meta = { ...local.meta, etag: '' }
    await safe(dropSnapshot) // another schema: fetch fresh, keep the outbox
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
  const ask = ++asks
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
      set({ fetchedAt: now, failed: false, error: '', local: false })
      for (const hook of appliedHooks) hook(ask)
      await safe(() => touchLocal(now))
    } else {
      if (answer.snapshot.schema_version !== SCHEMA_VERSION) throw new Error('The app needs an update. Close it and open it again.')
      result = '200'
      bytes = answer.bytes
      const meta: Meta = { etag: answer.etag, fetched_at: now, owner_id: answer.snapshot.owner_id, user_id: s.user, schema_version: SCHEMA_VERSION }
      if (s.meta && s.meta.owner_id !== meta.owner_id) await safe(wipeLocal)
      s.meta = meta
      s.fromLocal = false
      set({ snapshot: answer.snapshot, fetchedAt: now, failed: false, error: '', local: false })
      for (const hook of appliedHooks) hook(ask)
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
    addTiming({ at: launch.at, local_ms: launch.local_ms, fresh_ms: fresh, request_ms: requestMs, result, bytes, cold: requestMs > COLD_MS, boot: bootPath() }),
  )
}

/** Home calls this once it is drawn: the launch's local_ms, when drawn from the phone copy. */
export function noteHomeDrawn(): void {
  const launch = session?.launch
  if (launch && launch.local_ms === null && session?.fromLocal) launch.local_ms = Math.round(performance.now())
}

/** The boot watchdog (D-095): stop waiting for the phone copy and ask the server. */
export function settleData(): void {
  session?.settle?.()
}

/** Stop and forget in memory; the phone copy and the outbox stay (a lost session, D-093). */
export function pauseData(): void {
  const s = session
  session = null
  s?.stop()
  s?.controller?.abort()
  set(EMPTY)
  for (const hook of resetHooks) hook()
}

/** Sign-out or another login: stop, forget, and delete the phone copy and the outbox. */
export async function clearData(): Promise<void> {
  pauseData()
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

/** The muted line under the month: how fresh the numbers are. `signIn`: the failure is a
 *  session to renew, not the network (D-095). */
export function freshnessLine(d: Pick<DataState, 'fetchedAt' | 'refreshing' | 'failed'>, now = Date.now(), signIn = false): string {
  if (d.refreshing) return 'Updating…'
  if (d.fetchedAt === null) return ''
  const when = agoPhrase(d.fetchedAt, now)
  return d.failed ? `${signIn ? 'Not synced' : 'Offline'} · showing data from ${when}` : `Updated ${when}`
}

/** The Speed sheet's table: time (IST), boot path, phone copy in ms, fresh data in s, result. */
export function speedRows(timings: Timing[]): { when: string; boot: string; local: string; fresh: string; result: string }[] {
  return timings.map((t) => {
    const iso = new Date(t.at).toISOString()
    return {
      when: `${dayLabel(iso)} ${timeLabel(iso)}`,
      boot: t.boot ?? '–',
      local: t.local_ms === null ? '–' : `${t.local_ms} ms`,
      fresh: t.fresh_ms === null ? '–' : `${(t.fresh_ms / 1000).toFixed(1)} s`,
      result: t.cold ? `${t.result}, cold` : t.result,
    }
  })
}
