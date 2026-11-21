// The outbox (D-091, D-093; docs/design/phase-4b2-outbox.md). Every owner action is saved
// on the phone first, shown on its item, and sent in order with its op_id as the
// Idempotency-Key, so the server applies it once however often it is sent. Totals change
// only when a fresh snapshot arrives. An action is never dropped without the owner's say.
// The queue cannot get stuck (D-105): an op left "sending" goes back to "pending" at boot; the
// drain starts after the first paint, after every snapshot, when the phone comes online or
// to the foreground, and every 30 s while visible with anything waiting; every error inside it
// is caught and recorded on its op as a short code; only a 409 "in_progress" is retried.

import { useSyncExternalStore } from 'react'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import type { Category, Person, PersonRole, Sender, SenderAnswer, Snapshot, Transfer, Txn } from '../api/types.ts'
import { deleteOp, putOp, readOutbox } from './local.ts'
import { asksSoFar, dataState, onApplied, onReset, refresh } from './store.ts'

export type OpState = 'pending' | 'sending' | 'confirmed' | 'failed'

/** Why an op is not on the server yet (D-105). Short codes, stored on the op. */
export const CODES = [
  'offline', // the phone says it is offline
  'blocked_or_unreachable', // the request failed while online (network, or blocked: CORS)
  'blocked', // twice in a row, while reads work: the server refused the request
  'timeout', // no answer in time, or the server is still working on it (409 in_progress)
  'server_error', // 5xx
  'needs_sign_in', // 401 or 403
  'needs_choice', // another 409: the owner decides
  'rejected', // another 4xx
  'app_error', // an error inside the app; it tries again
] as const
export type SyncCode = (typeof CODES)[number]
/** The format of a stored op. Entries without `v` (written before 4F-B) are upgraded on read. */
export const OP_VERSION = 2
/** Still waiting this long after it was made: the item says why. */
export const STUCK_MS = 120_000
/** A confirmed op shows "Synced" this long before it leaves (tests set it to 0). */
export const timing = { syncedMs: 2_000, tickMs: 30_000 }

export interface Targets {
  txns?: number[]
  senders?: string[]
  /** Merchant names: "All from X" covers every payment to X. */
  merchants?: string[]
  /** Names of labels being made. */
  labels?: string[]
  /** Person keys a name or join is about (D-096). */
  people?: string[]
}

export interface Op {
  /** First in, first out. */
  seq: number
  op_id: string
  /** UTC ISO. */
  created_at: string
  /** "Category: Food & Drinks". */
  kind: string
  /** What it is about: "Swiggy". */
  item: string
  /** What the item shows meanwhile: "Food & Drinks", "Friend", "No label". */
  choice: string
  /** A category choice, for its tile. */
  slug?: string
  method: SendRequest['method']
  path: string
  body: unknown
  targets: Targets
  state: OpState
  attempts: number
  /** The last failure as a short code (SyncCode); '' when none. */
  last_error: string
  /** The server said 422 idempotency_key_reused: a retry needs a new op_id. */
  key_reused: boolean
  /** ms since the epoch. */
  confirmed_at: number | null
  /** Format version (OP_VERSION). */
  v?: number
  /** The server's own words for a refusal, when it gave some. */
  message?: string
  /** ms since the epoch, of the last send attempt. */
  last_attempt_at?: number | null
  /** Write failures in a row that looked blocked, and since when (ms). */
  unreachable?: { count: number; since: number } | null
}

export type NewOp = Pick<Op, 'kind' | 'item' | 'choice' | 'method' | 'path' | 'body' | 'targets'> & { slug?: string }

const TIMEOUT_MS = 90_000
/** Waits after a failed try: 5 s, 15 s, 60 s, then every 5 min. */
export const BACKOFF_MS = [5_000, 15_000, 60_000, 300_000]
export const backoffDelay = (failures: number) => BACKOFF_MS[Math.min(Math.max(failures, 1), BACKOFF_MS.length) - 1]

export interface SyncState {
  ops: Op[]
  /** A lasting 401: the actions wait until the owner signs in again. */
  signIn: boolean
  lastDrain: { at: number; sent: number; ms: number } | null
  /** The last failure: a short code, and the server's words when it gave some. */
  lastError: string
  /** When the next try is due after a failure (ms since the epoch), or null. */
  nextAttemptAt: number | null
  /** The last send attempt and its result ('ok' or a SyncCode). */
  lastAttempt: { at: number; result: string } | null
  /** When an op last reached the server. */
  lastSuccess: number | null
}

const EMPTY: SyncState = { ops: [], signIn: false, lastDrain: null, lastError: '', nextAttemptAt: null, lastAttempt: null, lastSuccess: null }
let sync = EMPTY
let api: Api | null = null
let refreshToken: () => Promise<boolean> = async () => false
let failures = 0
let running: Promise<void> | null = null
let again = false
let current: AbortController | null = null
let retryTimer: ReturnType<typeof setTimeout> | undefined
let stopWatching = () => {}
let lastSendAt = 0
const listeners = new Set<() => void>()

const isOnline = () => typeof navigator === 'undefined' || navigator.onLine !== false
/** After the first paint in a browser; at once elsewhere (tests). */
const afterPaint = (work: () => void) =>
  typeof requestAnimationFrame === 'function' ? requestAnimationFrame(() => setTimeout(work, 0)) : void Promise.resolve().then(work)

/** An entry written by an older build, in today's format; its choice is never changed. */
export function upgradeOp(op: Op): Op {
  if (op.v === OP_VERSION) return op
  const text = op.last_error || ''
  const known = (CODES as readonly string[]).includes(text)
  const code = !text || known ? text : /reach/i.test(text) ? 'blocked_or_unreachable' : /too long/i.test(text) ? 'timeout' : op.state === 'failed' ? 'rejected' : 'server_error'
  return { ...op, v: OP_VERSION, last_error: code, message: op.message ?? (known ? '' : text), last_attempt_at: op.last_attempt_at ?? null, unreachable: op.unreachable ?? null }
}

function publish(patch: Partial<SyncState> = {}): void {
  sync = { ...sync, ...patch, ops: [...(patch.ops ?? sync.ops)] }
  for (const listener of listeners) listener()
}

async function safe(work: () => Promise<unknown>): Promise<void> {
  try {
    await work()
  } catch {
    // IndexedDB missing (a private window): the outbox lives in memory only.
  }
}

const save = (op: Op) => safe(() => putOp(op))

/** After login, once the phone copy is checked (data/store.ts startData). */
export async function startOutbox(client: Api, refresh_: () => Promise<boolean> = async () => false): Promise<void> {
  stopOutbox()
  api = client
  refreshToken = refresh_
  let stored: Op[] = []
  try {
    stored = await readOutbox()
  } catch {
    // no IndexedDB
  }
  if (api !== client) return
  const ops = stored.map(upgradeOp)
  for (const [i, op] of ops.entries()) {
    const old = op !== stored[i]
    if (op.state === 'sending') op.state = 'pending' // closed while sending; the key makes a resend safe
    if (old || stored[i].state === 'sending') await save(op)
  }
  publish({ ops })
  stopWatching = watch()
  afterPaint(() => void drain())
}

/** Stop in memory; what is stored stays (data/store.ts decides whether it is deleted). */
export function stopOutbox(): void {
  api = null
  current?.abort()
  clearTimeout(retryTimer)
  stopWatching()
  stopWatching = () => {}
  failures = 0
  confirmedAsk.clear()
  sync = EMPTY
  for (const listener of listeners) listener()
}

onReset(stopOutbox)

// A confirmed action stays on its item until a snapshot asked for after it is applied, so
// the screen never flips back to the old value. Request numbers order that exactly; a
// confirmed op loaded from storage counts as confirmed before any request of this session.
const confirmedAsk = new Map<number, number>()
let appliedAsk = 0
let sweepTimer: ReturnType<typeof setTimeout> | undefined
/** Drop confirmed ops the applied snapshot covers, once each has shown "Synced" a moment. */
function sweep(): void {
  const now = Date.now()
  const covered = sync.ops.filter((o) => o.state === 'confirmed' && appliedAsk > (confirmedAsk.get(o.seq) ?? 0))
  const done = covered.filter((o) => now - (o.confirmed_at ?? 0) >= timing.syncedMs)
  if (done.length) {
    for (const op of done) void safe(() => deleteOp(op.seq))
    publish({ ops: sync.ops.filter((o) => !done.includes(o)) })
  }
  if (done.length < covered.length) {
    clearTimeout(sweepTimer)
    sweepTimer = setTimeout(sweep, timing.syncedMs)
  }
}
onApplied((ask) => {
  appliedAsk = Math.max(appliedAsk, ask)
  sweep()
  void drain() // after every snapshot (D-105)
})

function watch(): () => void {
  if (typeof document === 'undefined') return () => {}
  const online = () => {
    failures = 0
    publish({ nextAttemptAt: null })
    void drain()
  }
  const visible = () => document.visibilityState === 'visible' && void drain()
  // Every 30 s while visible with anything waiting, whatever the wait after a failure. The
  // watchdog: a drain with no send for longer than a request can take is abandoned.
  const tick = () => {
    if (document.visibilityState !== 'visible' || waiting(sync.ops) === 0) return
    if (running && Date.now() - lastSendAt > TIMEOUT_MS + 30_000) {
      current?.abort()
      running = null
    }
    void drain()
  }
  window.addEventListener('online', online)
  document.addEventListener('visibilitychange', visible)
  const timer = setInterval(tick, timing.tickMs)
  return () => {
    window.removeEventListener('online', online)
    document.removeEventListener('visibilitychange', visible)
    clearInterval(timer)
  }
}

/** Save a new action and start sending at once. Online or offline, the same path. */
export async function enqueue(change: NewOp): Promise<Op> {
  const op: Op = {
    ...change,
    seq: Math.max(0, ...sync.ops.map((o) => o.seq)) + 1,
    op_id: crypto.randomUUID(),
    created_at: new Date().toISOString(),
    state: 'pending',
    attempts: 0,
    last_error: '',
    key_reused: false,
    confirmed_at: null,
    v: OP_VERSION,
    message: '',
    last_attempt_at: null,
    unreachable: null,
  }
  publish({ ops: [...sync.ops, op] })
  await save(op)
  void drain()
  return op
}

function drainIfDue(): void {
  if (sync.nextAttemptAt === null || Date.now() >= sync.nextAttemptAt) void drain()
}

/** Send the waiting actions, first in first out, one at a time. Never two drains at once. */
export function drain(): Promise<void> {
  if (!api || sync.signIn) return Promise.resolve()
  if (running) {
    again = true
    return running
  }
  running = (async () => {
    do {
      again = false
      await pass()
    } while (again && api && !sync.signIn && sync.nextAttemptAt === null)
  })()
    .catch(() => {}) // pass() records its own errors; a drain never rejects
    .finally(() => {
      running = null
    })
  return running
}

type Outcome = { kind: 'ok' } | { kind: 'retry' | 'failed' | 'sign-in'; code: SyncCode; message: string; reused?: boolean }

/** Wait, then drain again: 5 s, 15 s, 60 s, then every 5 min (sooner while visible). */
function later(code: string, message = ''): void {
  failures += 1
  const delay = backoffDelay(failures)
  clearTimeout(retryTimer)
  retryTimer = setTimeout(drainIfDue, delay)
  publish({ nextAttemptAt: Date.now() + delay, lastError: message ? `${code}: ${message}` : code })
}

async function pass(): Promise<void> {
  const started = Date.now()
  let sent = 0
  let confirmed = 0
  let op: Op | undefined
  try {
    while (api) {
      op = sync.ops.find((o) => o.state === 'pending')
      if (!op) break
      if (!isOnline()) {
        // No attempt while the phone says offline: the online event sends it.
        op.last_error = 'offline'
        await save(op)
        publish({ lastAttempt: { at: Date.now(), result: 'offline' } })
        later('offline')
        break
      }
      const more = sync.ops.some((o) => o.state === 'pending' && o.seq > op!.seq)
      Object.assign(op, { state: 'sending', attempts: op.attempts + 1, last_attempt_at: Date.now() })
      lastSendAt = Date.now()
      publish()
      await save(op)
      const outcome = await sendOnce(op, more)
      sent += 1
      const at = Date.now()
      if (outcome.kind === 'ok') {
        Object.assign(op, { state: 'confirmed', confirmed_at: at, last_error: '', message: '', unreachable: null })
        confirmedAsk.set(op.seq, asksSoFar())
        confirmed += 1
        failures = 0
        clearTimeout(retryTimer)
        publish({ nextAttemptAt: null, lastError: '', lastAttempt: { at, result: 'ok' }, lastSuccess: at })
        await save(op)
        continue
      }
      let code = outcome.code
      if (code === 'blocked_or_unreachable') {
        // Twice in a row while reads get through: the server refuses this request (D-105).
        const since = op.unreachable?.since ?? at
        op.unreachable = { count: (op.unreachable?.count ?? 0) + 1, since }
        if (op.unreachable.count >= 2 && (dataState().fetchedAt ?? 0) > since) code = 'blocked'
      } else {
        op.unreachable = null
      }
      Object.assign(op, { last_error: code, message: outcome.message })
      publish({ lastAttempt: { at, result: code } })
      if (outcome.kind === 'failed') {
        Object.assign(op, { state: 'failed', key_reused: Boolean(outcome.reused) })
        publish({ lastError: outcome.message ? `${code}: ${outcome.message}` : code })
        await save(op)
        continue
      }
      op.state = 'pending'
      await save(op)
      if (outcome.kind === 'sign-in') publish({ signIn: true, lastError: code })
      else later(code)
      break
    }
  } catch {
    // Anything that went wrong in here: the op waits again and the drain is rescheduled.
    if (op && op.state === 'sending') op.state = 'pending'
    if (op) {
      Object.assign(op, { last_error: 'app_error' })
      await save(op)
    }
    publish({ lastAttempt: { at: Date.now(), result: 'app_error' } })
    later('app_error')
  }
  if (sent) publish({ lastDrain: { at: started, sent, ms: Date.now() - started } })
  if (confirmed) void refresh()
}

async function sendOnce(op: Op, defer: boolean): Promise<Outcome> {
  const client = api
  if (!client) return { kind: 'retry', code: 'app_error', message: '' }
  if (!isOnline()) return { kind: 'retry', code: 'offline', message: '' }
  const request: SendRequest = { op_id: op.op_id, method: op.method, path: op.path, body: op.body, defer }
  const controller = new AbortController()
  current = controller
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  const words = (a: { message: string }) => a.message
  try {
    let answer = await client.send(request, controller.signal)
    if (answer.status === 401 || answer.status === 403) {
      // One token refresh, one more try; then the owner signs in again. Nothing is dropped.
      if (!(await refreshToken())) return { kind: 'sign-in', code: 'needs_sign_in', message: words(answer) }
      answer = await client.send(request, controller.signal)
      if (answer.status === 401 || answer.status === 403) return { kind: 'sign-in', code: 'needs_sign_in', message: words(answer) }
    }
    if (answer.status >= 200 && answer.status < 300) return { kind: 'ok' }
    if (answer.status === 409 && answer.detail === 'in_progress') return { kind: 'retry', code: 'timeout', message: '' }
    if (answer.status >= 500) return { kind: 'retry', code: 'server_error', message: words(answer) }
    if (answer.status === 409) return { kind: 'failed', code: 'needs_choice', message: words(answer) }
    return { kind: 'failed', code: 'rejected', message: words(answer), reused: answer.detail === 'idempotency_key_reused' }
  } catch (e) {
    if (controller.signal.aborted) return { kind: 'retry', code: 'timeout', message: '' }
    if (!(e instanceof ApiError)) return { kind: 'retry', code: 'app_error', message: '' }
    if (!isOnline()) return { kind: 'retry', code: 'offline', message: '' }
    // fetch refused while online: no network, or the browser blocked it (CORS, D-104).
    return { kind: 'retry', code: 'blocked_or_unreachable', message: '' }
  } finally {
    clearTimeout(timer)
    current = null
  }
}

/** "Try now" from an item's details: no wait, send at once. */
export function tryNow(): Promise<void> {
  failures = 0
  clearTimeout(retryTimer)
  publish({ nextAttemptAt: null })
  return drain()
}

/** Remove an action that has not been sent yet. */
export async function undo(op: Op): Promise<boolean> {
  const mine = sync.ops.find((o) => o.seq === op.seq)
  if (!mine || mine.state !== 'pending') return false
  publish({ ops: sync.ops.filter((o) => o !== mine) })
  await safe(() => deleteOp(mine.seq))
  return true
}

/** Send a failed action again: the same op_id, unless the server said the key was reused. */
export async function retry(op: Op): Promise<void> {
  const mine = sync.ops.find((o) => o.seq === op.seq)
  if (!mine || mine.state !== 'failed') return
  Object.assign(mine, { state: 'pending', last_error: '', message: '', key_reused: false, op_id: mine.key_reused ? crypto.randomUUID() : mine.op_id })
  failures = 0
  publish({ nextAttemptAt: null })
  await save(mine)
  void drain()
}

/** Drop a failed action: the owner's choice. */
export async function discard(op: Op): Promise<void> {
  const mine = sync.ops.find((o) => o.seq === op.seq)
  if (!mine || mine.state !== 'failed') return
  publish({ ops: sync.ops.filter((o) => o !== mine) })
  await safe(() => deleteOp(mine.seq))
}

/** Before an update reload: wait (at most `maxMs`) for an action being sent. */
export async function waitForSending(maxMs = 10_000): Promise<void> {
  const until = Date.now() + maxMs
  while (sync.ops.some((o) => o.state === 'sending') && Date.now() < until) await new Promise((r) => setTimeout(r, 100))
}

export const syncState = (): SyncState => sync
const subscribe = (onChange: () => void) => {
  listeners.add(onChange)
  return () => void listeners.delete(onChange)
}
export const useOutbox = (): SyncState => useSyncExternalStore(subscribe, syncState)

// --- Pure helpers for the screens --------------------------------------------------

export const waiting = (ops: Op[]) => ops.filter((o) => o.state === 'pending' || o.state === 'sending').length
export const failedOps = (ops: Op[]) => ops.filter((o) => o.state === 'failed')
/** What sign-out would lose. */
export const unsynced = (ops: Op[]) => ops.filter((o) => o.state !== 'confirmed').length

/** The plain reason an op is not on the server yet (D-107). */
export const REASON: Record<SyncCode, string> = {
  offline: 'no connection',
  blocked_or_unreachable: "server didn't answer",
  timeout: "server didn't answer",
  server_error: 'server error',
  blocked: 'the server refused the request',
  needs_sign_in: 'needs sign-in',
  needs_choice: 'needs your choice',
  rejected: 'the server refused the request',
  app_error: 'the app hit a problem; it tries again',
}
export const reasonText = (op: Pick<Op, 'last_error'>): string =>
  REASON[op.last_error as SyncCode] ?? (isOnline() ? "server didn't answer" : 'no connection')

/** Waiting for 2 minutes or more: the item says why and opens its details. */
export const isStuck = (op: Op, now = Date.now()) =>
  (op.state === 'pending' || op.state === 'sending') && now - Date.parse(op.created_at) >= STUCK_MS

/** The muted text beside a shown choice (D-107). */
export function markText(op: Op, now = Date.now()): string {
  if (op.state === 'confirmed') return now - (op.confirmed_at ?? 0) < timing.syncedMs ? 'Synced' : ''
  if (op.state === 'failed') return `Not saved · ${reasonText(op)}`
  return isStuck(op, now) ? `Saved on phone · not synced yet: ${reasonText(op)}` : 'Saved on phone · syncing'
}

const isCheck = (o: Op) => o.path.endsWith('/check') || o.path.endsWith('/ignore')
const isTransfer = (o: Op) => o.path.startsWith('/transfers/')

/** The newest action that changes this row's category, label or count (failed ones do not),
 *  and the newest one about the row the server refused (`failed`), so the row says so (4H). */
export function markFor(ops: Op[], t: Txn): { category?: Op; label?: Op; counted?: Op; failed?: Op } {
  const spending = t.role === 'spend' || t.role === 'card_bill_counted' || t.role === 'refund'
  const isCategory = (o: Op) =>
    o.path.endsWith('/category') &&
    (o.targets.txns?.includes(t.id) ||
      (spending && t.display_name !== null && Boolean(o.targets.merchants?.includes(t.display_name))) ||
      (spending && t.person_id !== null && Boolean(o.targets.people?.includes(t.person_id))))
  const isLabel = (o: Op) => o.path.endsWith('/label') && Boolean(o.targets.txns?.includes(t.id))
  const isCounted = (o: Op) => isCheck(o) && Boolean(o.targets.txns?.includes(t.id))
  const live = ops.filter((o) => o.state !== 'failed')
  const last = (match: (o: Op) => boolean) => live.filter(match).at(-1)
  return {
    category: last(isCategory),
    label: last(isLabel),
    counted: last(isCounted),
    failed: ops.filter((o) => o.state === 'failed' && (isCategory(o) || isLabel(o) || isCounted(o))).at(-1),
  }
}

/** The newest "Payments to them count as" choice for a person (D-110), failed ones too. */
export const personCategoryMark = (ops: Op[], key: string): Op | undefined =>
  ops.filter((o) => o.path.endsWith('/category') && (o.body as { scope?: string } | null)?.scope === 'merchant' && o.targets.people?.includes(key)).at(-1)

/** The newest answer for any of these senders (D-110), failed ones too. */
export const senderMark = (ops: Op[], ids: string[]): Op | undefined =>
  ops.filter((o) => o.targets.senders?.some((id) => ids.includes(id))).at(-1)

/** The newest refused name, join or separate of a person, for its sheet. */
export const personFailed = (ops: Op[], key: string): Op | undefined =>
  ops.filter((o) => o.state === 'failed' && o.path.startsWith('/people/') && o.targets.people?.includes(key)).at(-1)

/** Labels being made on the phone, not on the server yet: they can be picked meanwhile. */
export function waitingLabels(ops: Op[], known: string[]): string[] {
  const seen = new Set(known.map((n) => n.toLowerCase()))
  const out: string[] = []
  for (const name of ops.flatMap((o) => (o.state === 'failed' ? [] : (o.targets.labels ?? [])))) {
    if (!seen.has(name.toLowerCase())) out.push(name)
    seen.add(name.toLowerCase())
  }
  return out
}

/** Rows read automatically that still ask "Looks right?", without those answered offline. */
export function checksView(txns: Txn[], ops: Op[]): Txn[] {
  const answered = new Set(ops.filter((o) => o.state !== 'failed' && isCheck(o)).flatMap((o) => o.targets.txns ?? []))
  return txns.filter((t) => t.check && !answered.has(t.id))
}

/** The newest name, join or separate waiting for this person (failed ones do not count). */
export function personMark(ops: Op[], key: string): Op | undefined {
  return ops.filter((o) => o.state !== 'failed' && o.path.startsWith('/people/') && o.targets.people?.includes(key)).at(-1)
}

/** The name to show for a person: a waiting rename or clear first, then the server's. */
export function shownName(ops: Op[], p: Pick<Person, 'key' | 'name'>, fallback = 'Person'): string {
  const mark = personMark(ops, p.key)
  if (mark?.path.endsWith('/name')) return mark.method === 'DELETE' ? (p.name ?? fallback) : mark.choice
  return p.name ?? fallback
}

/** Both have an answer and they differ: the join must ask which one stays (D-096). */
export const roleConflict = (a: Pick<Person, 'role'>, b: Pick<Person, 'role'>): boolean =>
  a.role !== null && b.role !== null && a.role !== b.role

/** To-do without the items that already have an answer waiting; those are listed apart. */
export function todoView(todo: Snapshot['todo'], ops: Op[]) {
  const live = ops.filter((o) => o.state !== 'failed')
  const senders = new Set(live.flatMap((o) => o.targets.senders ?? []))
  const merchants = new Set(live.filter((o) => o.path.endsWith('/category')).flatMap((o) => o.targets.merchants ?? []))
  const moved = new Set(live.filter(isTransfer).map((o) => o.path))
  return {
    senders: todo.senders.filter((s) => !senders.has(s.id)),
    answered: todo.answered.filter((s) => !senders.has(s.id)),
    merchants: todo.merchants.filter((m) => !merchants.has(m.name)),
    transfers: (todo.transfers ?? []).filter((t) => !moved.has(transferPath(t))),
    waiting: [
      ...live.filter(
        (o) =>
          o.targets.senders?.length ||
          (o.targets.merchants?.length && o.kind.startsWith('All from')) ||
          (isCheck(o) && o.method === 'PUT') ||
          isTransfer(o),
      ),
      ...ops.filter((o) => o.state === 'failed' && o.last_error === 'needs_choice'), // the choice, inline (D-107)
    ],
  }
}

/** "3 saved on phone, syncing" and "1 not saved" for the line under the month (D-113 wording). */
export function syncLine(ops: Op[], signIn: boolean): { waiting: string; failed: string; signIn: boolean } {
  const n = waiting(ops)
  const f = failedOps(ops).length
  return { waiting: n ? `${n} saved on phone, syncing` : '', failed: f ? `${f} not saved` : '', signIn }
}

// --- The owner actions as outbox entries -------------------------------------------------

const transferPath = (t: Pick<Transfer, 'debit' | 'credit'>) => `/transfers/${t.debit}/${t.credit}`

const ANSWER_TEXT = { friend: 'Friend', income: 'Family', ignore: 'Ignored' } as const

export const actions = {
  answerSender(s: Sender, answer: SenderAnswer): NewOp {
    const choice = answer.answer === 'income' ? `Income: ${answer.label}` : ANSWER_TEXT[answer.answer]
    return {
      kind: `Answer: ${choice}`,
      item: s.display_name ?? 'Bank transfer in',
      choice,
      method: 'PUT',
      path: `/senders/${encodeURIComponent(s.id)}`,
      body: answer,
      targets: { senders: [s.id] },
    }
  },
  resetSender(s: Sender): NewOp {
    return {
      kind: 'Ask me again later',
      item: s.display_name ?? 'Bank transfer in',
      choice: 'Ask me again later',
      method: 'DELETE',
      path: `/senders/${encodeURIComponent(s.id)}`,
      body: null,
      targets: { senders: [s.id] },
    }
  },
  /** `person`: "Payments to them count as" in the person sheet (D-110): the party default,
   *  shown on every row of the person, whichever name or UPI ID the bank used. */
  setCategory(
    t: { id: number; display_name: string | null },
    c: Category,
    scope: 'merchant' | 'transaction',
    item: string,
    person?: { key: string; name: string },
  ): NewOp {
    const merchant = scope === 'merchant' && (person?.name ?? t.display_name)
    const targets: Targets = { txns: [t.id] }
    if (scope === 'merchant' && t.display_name) targets.merchants = [t.display_name]
    if (scope === 'merchant' && person) targets.people = [person.key]
    return {
      kind: merchant ? `All from ${merchant}: ${c.name}` : `Category: ${c.name}`,
      item,
      choice: c.name,
      slug: c.slug,
      method: 'PUT',
      path: `/transactions/${t.id}/category`,
      body: { category: c.slug, scope },
      targets,
    }
  },
  createLabel(name: string): NewOp {
    return { kind: `New label: ${name}`, item: name, choice: name, method: 'POST', path: '/labels', body: { name }, targets: { labels: [name] } }
  },
  setLabel(t: Txn, label: { id: number; name: string } | { new: string }, item: string): NewOp {
    const name = 'new' in label ? label.new : label.name
    return {
      kind: `Label: ${name}`,
      item,
      choice: name,
      method: 'PUT',
      path: `/transactions/${t.id}/label`,
      body: 'new' in label ? { new_label: label.new } : { label_id: label.id },
      targets: { txns: [t.id], ...('new' in label ? { labels: [label.new] } : {}) },
    }
  },
  clearLabel(t: Txn, item: string): NewOp {
    return { kind: 'No label', item, choice: 'No label', method: 'DELETE', path: `/transactions/${t.id}/label`, body: null, targets: { txns: [t.id] } }
  },
  // People (D-096): each names its person by one of its transactions, so a queue made
  // offline lands right after the actions before it.
  namePerson(p: Pick<Person, 'key' | 'txn_id' | 'name'>, name: string): NewOp {
    return { kind: `Name: ${name}`, item: p.name ?? 'Person', choice: name, method: 'PUT', path: `/people/${p.txn_id}/name`, body: { name }, targets: { people: [p.key] } }
  },
  clearName(p: Pick<Person, 'key' | 'txn_id' | 'name'>): NewOp {
    return { kind: 'Clear name', item: p.name ?? 'Person', choice: 'No name', method: 'DELETE', path: `/people/${p.txn_id}/name`, body: null, targets: { people: [p.key] } }
  },
  joinPerson(p: Pick<Person, 'key' | 'txn_id' | 'name'>, into: Pick<Person, 'key' | 'txn_id' | 'name'>, role: PersonRole | null): NewOp {
    const name = into.name ?? 'Person'
    return {
      kind: `Same as ${name}`,
      item: p.name ?? 'Person',
      choice: `Same as ${name}`,
      method: 'PUT',
      path: `/people/${p.txn_id}/join`,
      body: role ? { into: into.txn_id, role } : { into: into.txn_id },
      targets: { people: [p.key, into.key] },
    }
  },
  /** "Moved between your accounts?" (D-115): Yes, both legs are a transfer; No, they are not. */
  answerTransfer(t: Transfer, same: boolean, item: string): NewOp {
    const choice = same ? 'Moved between my accounts' : 'Not a transfer'
    return {
      kind: `Transfer: ${same ? 'Yes' : 'No'}`,
      item,
      choice,
      method: 'PUT',
      path: transferPath(t),
      body: { verdict: same ? 'same' : 'different' },
      targets: { txns: [t.debit, t.credit] },
    }
  },
  // Checks (D-101, D-103): a row read automatically, and Not a payment for any row.
  looksRight(t: Pick<Txn, 'id'>, item: string): NewOp {
    return { kind: 'Looks right', item, choice: 'Looks right', method: 'PUT', path: `/transactions/${t.id}/check`, body: null, targets: { txns: [t.id] } }
  },
  notAPayment(t: Pick<Txn, 'id'>, item: string): NewOp {
    return { kind: 'Not a payment', item, choice: 'Not a payment', method: 'PUT', path: `/transactions/${t.id}/ignore`, body: null, targets: { txns: [t.id] } }
  },
  countAgain(t: Pick<Txn, 'id'>, item: string): NewOp {
    return { kind: 'Count it again', item, choice: 'Counted again', method: 'DELETE', path: `/transactions/${t.id}/ignore`, body: null, targets: { txns: [t.id] } }
  },
  separate(p: Pick<Person, 'key' | 'name'>, identifier: { name: string | null; txn_id: number }): NewOp {
    const name = identifier.name ?? 'Identifier'
    return { kind: `Separate ${name}`, item: p.name ?? 'Person', choice: `Separate ${name}`, method: 'DELETE', path: `/people/${identifier.txn_id}/join`, body: null, targets: { people: [p.key] } }
  },
}
