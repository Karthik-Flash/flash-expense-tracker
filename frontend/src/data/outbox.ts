// The outbox (D-091, D-093; docs/design/phase-4b2-outbox.md). Every owner action is saved
// on the phone first, shown on its item, and sent in order with its op_id as the
// Idempotency-Key, so the server applies it once however often it is sent. Totals change
// only when a fresh snapshot arrives. An action is never dropped without the owner's say.

import { useSyncExternalStore } from 'react'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import type { Category, Sender, SenderAnswer, Snapshot, Txn } from '../api/types.ts'
import { deleteOp, putOp, readOutbox } from './local.ts'
import { asksSoFar, onApplied, onReset, refresh } from './store.ts'

export type OpState = 'pending' | 'sending' | 'confirmed' | 'failed'

export interface Targets {
  txns?: number[]
  senders?: string[]
  /** Merchant names: "All from X" covers every payment to X. */
  merchants?: string[]
  /** Names of labels being made. */
  labels?: string[]
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
  last_error: string
  /** The server said 422 idempotency_key_reused: a retry needs a new op_id. */
  key_reused: boolean
  /** ms since the epoch. */
  confirmed_at: number | null
}

export type NewOp = Pick<Op, 'kind' | 'item' | 'choice' | 'method' | 'path' | 'body' | 'targets'> & { slug?: string }

const TIMEOUT_MS = 90_000
const TICK_MS = 30_000
/** Waits after a failed try: 5 s, 15 s, 60 s, then every 5 min. */
export const BACKOFF_MS = [5_000, 15_000, 60_000, 300_000]
export const backoffDelay = (failures: number) => BACKOFF_MS[Math.min(Math.max(failures, 1), BACKOFF_MS.length) - 1]

export interface SyncState {
  ops: Op[]
  /** A lasting 401: the actions wait until the owner signs in again. */
  signIn: boolean
  lastDrain: { at: number; sent: number; ms: number } | null
  lastError: string
  /** When the next try is due after a failure (ms since the epoch), or null. */
  nextAttemptAt: number | null
}

const EMPTY: SyncState = { ops: [], signIn: false, lastDrain: null, lastError: '', nextAttemptAt: null }
let sync = EMPTY
let api: Api | null = null
let refreshToken: () => Promise<boolean> = async () => false
let failures = 0
let running: Promise<void> | null = null
let again = false
let current: AbortController | null = null
let retryTimer: ReturnType<typeof setTimeout> | undefined
let stopWatching = () => {}
const listeners = new Set<() => void>()

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
  let ops: Op[] = []
  try {
    ops = await readOutbox()
  } catch {
    // no IndexedDB
  }
  if (api !== client) return
  for (const op of ops.filter((o) => o.state === 'sending')) {
    op.state = 'pending' // the app closed while it was being sent; the key makes a resend safe
    await save(op)
  }
  publish({ ops })
  stopWatching = watch()
  void drain()
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
onApplied((ask) => {
  const done = sync.ops.filter((o) => o.state === 'confirmed' && ask > (confirmedAsk.get(o.seq) ?? 0))
  if (done.length) {
    for (const op of done) void safe(() => deleteOp(op.seq))
    publish({ ops: sync.ops.filter((o) => !done.includes(o)) })
  }
  void drain()
})

function watch(): () => void {
  if (typeof document === 'undefined') return () => {}
  const online = () => {
    failures = 0
    publish({ nextAttemptAt: null })
    void drain()
  }
  const visible = () => document.visibilityState === 'visible' && void drain()
  const tick = () => document.visibilityState === 'visible' && waiting(sync.ops) > 0 && drainIfDue()
  window.addEventListener('online', online)
  document.addEventListener('visibilitychange', visible)
  const timer = setInterval(tick, TICK_MS)
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
  })().finally(() => {
    running = null
  })
  return running
}

type Outcome = { kind: 'ok' } | { kind: 'retry' | 'failed' | 'sign-in'; message: string; reused?: boolean }

async function pass(): Promise<void> {
  const started = Date.now()
  let sent = 0
  let confirmed = 0
  while (api) {
    const op = sync.ops.find((o) => o.state === 'pending')
    if (!op) break
    const more = sync.ops.some((o) => o.state === 'pending' && o.seq > op.seq)
    op.state = 'sending'
    op.attempts += 1
    publish()
    await save(op)
    const outcome = await sendOnce(op, more)
    sent += 1
    if (outcome.kind === 'ok') {
      Object.assign(op, { state: 'confirmed', confirmed_at: Date.now(), last_error: '' })
      confirmedAsk.set(op.seq, asksSoFar())
      confirmed += 1
      failures = 0
      clearTimeout(retryTimer)
      publish({ nextAttemptAt: null, lastError: '' })
      await save(op)
      continue
    }
    if (outcome.kind === 'failed') {
      Object.assign(op, { state: 'failed', last_error: outcome.message, key_reused: Boolean(outcome.reused) })
      publish({ lastError: outcome.message })
      await save(op)
      continue
    }
    Object.assign(op, { state: 'pending', last_error: outcome.message })
    await save(op)
    if (outcome.kind === 'sign-in') {
      publish({ signIn: true, lastError: outcome.message })
    } else {
      failures += 1
      const delay = backoffDelay(failures)
      clearTimeout(retryTimer)
      retryTimer = setTimeout(drainIfDue, delay)
      publish({ nextAttemptAt: Date.now() + delay, lastError: outcome.message })
    }
    break
  }
  if (sent) publish({ lastDrain: { at: started, sent, ms: Date.now() - started } })
  if (confirmed) void refresh()
}

async function sendOnce(op: Op, defer: boolean): Promise<Outcome> {
  const client = api
  if (!client) return { kind: 'retry', message: 'Stopped.' }
  const request: SendRequest = { op_id: op.op_id, method: op.method, path: op.path, body: op.body, defer }
  const controller = new AbortController()
  current = controller
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    let answer = await client.send(request, controller.signal)
    if (answer.status === 401 || answer.status === 403) {
      // One token refresh, one more try; then the owner signs in again. Nothing is dropped.
      if (!(await refreshToken())) return { kind: 'sign-in', message: answer.message }
      answer = await client.send(request, controller.signal)
      if (answer.status === 401 || answer.status === 403) return { kind: 'sign-in', message: answer.message }
    }
    if (answer.status >= 200 && answer.status < 300) return { kind: 'ok' }
    if (answer.status >= 500 || (answer.status === 409 && answer.detail === 'in_progress')) return { kind: 'retry', message: answer.message }
    return { kind: 'failed', message: answer.message, reused: answer.detail === 'idempotency_key_reused' }
  } catch (e) {
    if (controller.signal.aborted) return { kind: 'retry', message: 'The server took too long to answer.' }
    return { kind: 'retry', message: e instanceof ApiError ? e.message : 'Could not reach the server.' }
  } finally {
    clearTimeout(timer)
    current = null
  }
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
  Object.assign(mine, { state: 'pending', last_error: '', key_reused: false, op_id: mine.key_reused ? crypto.randomUUID() : mine.op_id })
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

/** The muted text beside a shown choice. */
export const markText = (op: Op) => (op.state === 'confirmed' ? '' : 'Waiting to sync')

/** The newest action that changes this row's category or label (failed ones do not). */
export function markFor(ops: Op[], t: Txn): { category?: Op; label?: Op } {
  const live = ops.filter((o) => o.state !== 'failed')
  const last = (match: (o: Op) => boolean) => live.filter(match).at(-1)
  const spending = t.role === 'spend' || t.role === 'card_bill_counted' || t.role === 'refund'
  return {
    category: last(
      (o) =>
        o.path.endsWith('/category') &&
        (o.targets.txns?.includes(t.id) || (spending && t.display_name !== null && Boolean(o.targets.merchants?.includes(t.display_name)))),
    ),
    label: last((o) => o.path.endsWith('/label') && Boolean(o.targets.txns?.includes(t.id))),
  }
}

/** To-do without the items that already have an answer waiting; those are listed apart. */
export function todoView(todo: Snapshot['todo'], ops: Op[]) {
  const live = ops.filter((o) => o.state !== 'failed')
  const senders = new Set(live.flatMap((o) => o.targets.senders ?? []))
  const merchants = new Set(live.filter((o) => o.path.endsWith('/category')).flatMap((o) => o.targets.merchants ?? []))
  return {
    senders: todo.senders.filter((s) => !senders.has(s.id)),
    answered: todo.answered.filter((s) => !senders.has(s.id)),
    merchants: todo.merchants.filter((m) => !merchants.has(m.name)),
    waiting: live.filter((o) => o.targets.senders?.length || (o.targets.merchants?.length && o.kind.startsWith('All from'))),
  }
}

/** "3 waiting to sync" and "1 couldn't save" for the line under the month. */
export function syncLine(ops: Op[], signIn: boolean): { waiting: string; failed: string; signIn: boolean } {
  const n = waiting(ops)
  const f = failedOps(ops).length
  return { waiting: n ? `${n} waiting to sync` : '', failed: f ? `${f} couldn't save` : '', signIn }
}

// --- The six owner actions as outbox entries -----------------------------------------

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
  setCategory(t: { id: number; display_name: string | null }, c: Category, scope: 'merchant' | 'transaction', item: string): NewOp {
    const merchant = scope === 'merchant' && t.display_name
    return {
      kind: merchant ? `All from ${t.display_name}: ${c.name}` : `Category: ${c.name}`,
      item,
      choice: c.name,
      slug: c.slug,
      method: 'PUT',
      path: `/transactions/${t.id}/category`,
      body: { category: c.slug, scope },
      targets: merchant ? { txns: [t.id], merchants: [t.display_name as string] } : { txns: [t.id] },
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
}
