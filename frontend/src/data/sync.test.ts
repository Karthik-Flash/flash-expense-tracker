// The outbox cannot get stuck (4F-B, D-105, D-107). Every drain path from the 4F-B report
// (0.3 a to h) must send; error codes, old entries, wording and the "Synced" moment. FAKE only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'

import { ApiError, type Api, type SendAnswer, type SendRequest } from '../api/client.ts'
import type { Category, Snapshot, SnapshotAnswer, Txn } from '../api/types.ts'
import { putOp, readOutbox, wipeLocal } from './local.ts'
import {
  actions,
  drain,
  enqueue,
  isStuck,
  markText,
  OP_VERSION,
  reasonText,
  startOutbox,
  stopOutbox,
  syncLine,
  syncState,
  timing,
  todoView,
  type Op,
  upgradeOp,
} from './outbox.ts'
import { clearData, refresh, startData } from './store.ts'

const FOOD: Category = { slug: 'food_drinks', name: 'Food & Drinks' }
const txn = (id: number): Txn => ({
  id, time_utc: '2026-11-10T06:00:00Z', amount_paise: 10000, direction: 'debit', display_name: 'Test Shop',
  person_id: null, role: 'spend', role_basis: 'engine', category: 'uncategorised', category_name: 'Uncategorised',
  category_basis: 'engine', label: null,
})
const snap = { schema_version: 1, generated_at: '', owner_id: 'owner-a', engine_versions: {}, transactions: [txn(1)],
  months: [], todo: { senders: [], answered: [], merchants: [], unnamed: 0 }, labels: [], categories: [FOOD] } as unknown as Snapshot
const tap = (id: number) => actions.setCategory(txn(id), FOOD, 'transaction', 'Test Shop')
const states = () => syncState().ops.map((o) => o.state)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
async function until(check: () => boolean, ms = 1500): Promise<void> {
  for (let waited = 0; !check() && waited < ms; waited += 10) await sleep(10)
  assert.ok(check(), 'timed out')
}

type Mode = 'ok' | 'unreachable' | 'bug' | { status: number; detail: unknown }
/** A FAKE server: each send takes the next mode; the same op_id is applied once. */
function server(snapshots: ('ok' | 'error')[] = []) {
  const applied: string[] = []
  const answers = new Map<string, SendAnswer>()
  let modes: Mode[] = []
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    createInvite: async () => ({ code: 'TEST-CODE-0001' }),
    exportFile: async () => new Blob(),
    analytics: async () => ({ status: 304 }),
    deleteAccount: async () => ({ status: 200, detail: null, message: '' }),
    async snapshot(): Promise<SnapshotAnswer> {
      if (snapshots.shift() === 'error') throw new ApiError(0, 'Could not reach the server.')
      return { status: 200, etag: '"e"', snapshot: snap, bytes: 1 }
    },
    async send(req: SendRequest) {
      const mode = modes.shift() ?? 'ok'
      if (mode === 'unreachable') throw new ApiError(0, 'Could not reach the server.')
      if (mode === 'bug') throw new TypeError('TEST: a bug in the app')
      if (typeof mode === 'object') return { status: mode.status, detail: mode.detail, message: `TEST ${mode.status}` }
      const done = answers.get(req.op_id)
      if (done) return done
      applied.push(`${req.method} ${req.path}`)
      const answer = { status: 200, detail: null, message: '' }
      answers.set(req.op_id, answer)
      return answer
    },
  }
  return { api, applied, next: (...m: Mode[]) => (modes = m) }
}

// A browser for watch(): window and document events, and navigator.onLine.
const g = globalThis as unknown as { window?: EventTarget; document?: EventTarget & { visibilityState: string } }
let online = true
beforeEach(() => {
  g.window = new EventTarget()
  g.document = Object.assign(new EventTarget(), { visibilityState: 'visible' })
  online = true
  Object.defineProperty(globalThis.navigator, 'onLine', { get: () => online, configurable: true })
})
afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
  delete g.window
  delete g.document
  Object.defineProperty(globalThis.navigator, 'onLine', { value: undefined, configurable: true })
  timing.syncedMs = 2_000
  timing.tickMs = 30_000
})

test('a: tap offline, go online with the app open: the online event sends it', async () => {
  const s = server()
  await startOutbox(s.api)
  online = false
  await enqueue(tap(1))
  await drain()
  assert.deepEqual(states(), ['pending'])
  assert.equal(syncState().ops[0].last_error, 'offline')
  assert.deepEqual(s.applied, []) // nothing tried while the phone says offline
  online = true
  g.window!.dispatchEvent(new Event('online'))
  await until(() => states()[0] === 'confirmed')
})

test('b, c: tap offline, close (or Reload offline), open online: boot sends it', async () => {
  const s = server()
  await startOutbox(s.api)
  online = false
  await enqueue(tap(1))
  await drain()
  stopOutbox()
  await startOutbox(s.api) // c: Reload while still offline
  await drain()
  assert.deepEqual(states(), ['pending'])
  stopOutbox()
  online = true
  await startOutbox(s.api) // reopened online: the drain starts after the first paint
  await until(() => states()[0] === 'confirmed')
  assert.equal(s.applied.length, 1)
})

test('d: an op left "sending" when the page was killed goes back to pending and is sent', async () => {
  const s = server()
  await startOutbox(s.api)
  online = false
  const op = await enqueue(tap(1))
  stopOutbox()
  await putOp({ ...op, state: 'sending' })
  online = true
  await startOutbox(s.api)
  await until(() => states()[0] === 'confirmed')
  assert.equal(syncState().ops[0].op_id, op.op_id)
})

test('e: the online event fires while the page is hidden: it still sends', async () => {
  const s = server()
  await startOutbox(s.api)
  online = false
  await enqueue(tap(1))
  await drain()
  g.document!.visibilityState = 'hidden'
  online = true
  g.window!.dispatchEvent(new Event('online'))
  await until(() => states()[0] === 'confirmed')
})

test('f: a snapshot refresh fails once, then works: the success drains at once', async () => {
  const s = server(['error', 'ok'])
  await startData(s.api, 'user-a') // the first refresh fails
  s.next('unreachable')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  assert.deepEqual(states(), ['pending'])
  assert.ok((syncState().nextAttemptAt ?? 0) > Date.now()) // waiting 5 s after the failure
  await refresh() // succeeds: no need to wait the 5 s
  await until(() => states()[0] === 'confirmed')
})

test('g: a 409 other than in_progress needs the owner; in_progress is retried; others go on', async () => {
  const s = server()
  s.next({ status: 409, detail: 'in_progress' }, { status: 409, detail: 'the two have different answers' }, 'ok')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  assert.deepEqual(states(), ['pending']) // in_progress: tried again later
  assert.equal(syncState().ops[0].last_error, 'timeout')
  await enqueue(tap(2))
  await drain()
  assert.deepEqual(states(), ['failed', 'confirmed'])
  const first = syncState().ops[0]
  assert.equal(first.last_error, 'needs_choice')
  assert.equal(markText(first), 'Not saved · needs your choice')
  const empty = { senders: [], answered: [], merchants: [], unnamed: 0 }
  assert.deepEqual(todoView(empty, syncState().ops).waiting, [first]) // shown with its choice
})

test('h: an exception inside the drain is recorded and the op is sent later', async () => {
  const s = server()
  s.next('bug')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  const op = syncState().ops[0]
  assert.equal(op.state, 'pending')
  assert.equal(op.last_error, 'app_error')
  assert.ok(op.last_attempt_at)
  assert.equal(syncState().lastAttempt?.result, 'app_error')
  assert.ok(syncState().nextAttemptAt) // rescheduled, never stopped
  await drain()
  assert.deepEqual(states(), ['confirmed'])
})

test('every 30 s while visible: the tick drains whatever the wait; not while hidden', async () => {
  timing.tickMs = 20
  const s = server()
  s.next('unreachable')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  assert.ok((syncState().nextAttemptAt ?? 0) - Date.now() > 4_000)
  g.document!.visibilityState = 'hidden'
  await sleep(80)
  assert.deepEqual(states(), ['pending'])
  g.document!.visibilityState = 'visible'
  await until(() => states()[0] === 'confirmed')
})

test('codes: offline, unreachable, then "blocked" once reads work; server error; sign-in', async () => {
  const s = server(['ok'])
  await startOutbox(s.api, async () => false)
  s.next('unreachable', 'unreachable', { status: 503, detail: null }, { status: 401, detail: null })
  await enqueue(tap(1))
  await drain()
  assert.equal(syncState().ops[0].last_error, 'blocked_or_unreachable')
  await sleep(5)
  await startData(s.api, 'user-a') // a read gets through after the first failure
  await until(() => syncState().lastSuccess !== undefined)
  await drain()
  assert.equal(syncState().ops[0].last_error, 'blocked') // twice, while reads work
  assert.equal(reasonText(syncState().ops[0]), 'the server refused the request')
  await drain()
  assert.equal(syncState().ops[0].last_error, 'server_error')
  await drain()
  assert.equal(syncState().ops[0].last_error, 'needs_sign_in')
  assert.equal(syncState().signIn, true)
})

test('an entry written by 57a3b48 is upgraded in place and still sent with its key', async () => {
  const old = {
    seq: 1, op_id: 'old-op-0001', created_at: '2026-11-20T17:12:00Z', kind: 'Answer: Friend', item: 'Test Person',
    choice: 'Friend', method: 'PUT', path: '/senders/s_test', body: { answer: 'friend' }, targets: { senders: ['s_test'] },
    state: 'sending', attempts: 7, last_error: 'Could not reach the server. Check the connection and try again.',
    key_reused: false, confirmed_at: null,
  } as unknown as Op
  await putOp(old)
  const s = server()
  const sent: SendRequest[] = []
  const send = s.api.send
  s.api.send = (req, signal) => (sent.push(req), send(req, signal))
  online = false // boot offline first: the upgrade happens on read, nothing is sent
  await startOutbox(s.api)
  const stored = (await readOutbox())[0]
  assert.equal(stored.v, OP_VERSION)
  assert.equal(upgradeOp(old).last_error, 'blocked_or_unreachable') // the old text, as a code
  assert.equal(stored.last_error, 'offline') // then the boot drain, still offline
  assert.equal(stored.message, 'Could not reach the server. Check the connection and try again.')
  assert.deepEqual([stored.op_id, stored.choice, stored.body, stored.state], ['old-op-0001', 'Friend', { answer: 'friend' }, 'pending'])
  online = true
  await drain()
  assert.deepEqual(sent.map((r) => [r.op_id, r.method, r.path]), [['old-op-0001', 'PUT', '/senders/s_test']])
  assert.deepEqual(states(), ['confirmed'])
})

test('wording: saved on phone, syncing; after 2 minutes the reason and details', async () => {
  const s = server()
  s.next('unreachable')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  const op = syncState().ops[0]
  assert.equal(markText(op), 'Saved on phone · syncing')
  assert.equal(syncLine(syncState().ops, false).waiting, '1 saved on phone, syncing')
  assert.equal(isStuck(op), false)
  const later = Date.parse(op.created_at) + 121_000
  assert.equal(isStuck(op, later), true)
  assert.equal(markText(op, later), "Saved on phone · not synced yet: server didn't answer")
  online = false
  assert.equal(markText({ ...op, last_error: 'offline' }, later), 'Saved on phone · not synced yet: no connection')
})

test('a confirmed op shows "Synced" a moment, then leaves once the snapshot has it', async () => {
  timing.syncedMs = 120
  const s = server()
  await startData(s.api, 'user-a')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await until(() => states()[0] === 'confirmed')
  assert.equal(markText(syncState().ops[0]), 'Synced')
  assert.ok(syncState().lastSuccess)
  await refresh() // the snapshot asked for after it
  assert.deepEqual(states(), ['confirmed']) // still showing "Synced"
  await until(() => states().length === 0)
  assert.equal(markText({ ...syncState().ops[0], state: 'confirmed', confirmed_at: 0 } as Op), '')
})
