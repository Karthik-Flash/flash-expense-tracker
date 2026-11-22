import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { openDB } from 'idb'

import { ApiError, type Api, type SendAnswer, type SendRequest } from '../api/client.ts'
import type { Category, Sender, Snapshot, SnapshotAnswer, Txn } from '../api/types.ts'
import { putOp, readLocal, readOutbox, wipeLocal } from './local.ts'
import {
  actions,
  backoffDelay,
  discard,
  drain,
  enqueue,
  markFor,
  markText,
  retry,
  startOutbox,
  stopOutbox,
  syncLine,
  syncState,
  timing,
  todoView,
  undo,
  unsynced,
  type Op,
} from './outbox.ts'
import { clearData, dataState, startData } from './store.ts'

// FAKE data only.
const FOOD: Category = { slug: 'food_drinks', name: 'Food & Drinks' }
const txn = (id: number, over: Partial<Txn> = {}): Txn => ({
  id,
  time_utc: '2026-11-10T06:00:00Z',
  amount_paise: 10000,
  direction: 'debit',
  display_name: 'Test Shop',
  person_id: null,
  role: 'spend',
  role_basis: 'engine',
  category: 'uncategorised',
  category_name: 'Uncategorised',
  category_basis: 'engine',
  label: null,
  ...over,
})
const sender = (id: string): Sender => ({
  id, display_name: `Person ${id}`, total_paise: 5000, count: 1, role: 'uncertain', basis: 'engine',
  status: 'to_confirm', last_time_utc: '2026-11-10T06:00:00Z', income_label: null,
})
const snap = { schema_version: 1, generated_at: '', owner_id: 'owner-a', engine_versions: {}, transactions: [txn(1)],
  months: [{ month: '2026-11', summary: { spent_paise: 10000 } }], todo: { senders: [], answered: [], merchants: [], unnamed: 0 },
  labels: [], categories: [FOOD] } as unknown as Snapshot

type Mode = 'ok' | 'offline' | 'lose' | 'hang' | { status: number; detail: unknown }

/** A FAKE server with the Idempotency-Key rule: the same op_id is applied once. */
function server(snapshot: () => Promise<SnapshotAnswer> = async () => ({ status: 200, etag: '"e"', snapshot: snap, bytes: 1 })) {
  const applied: string[] = []
  const defers: boolean[] = []
  const answers = new Map<string, SendAnswer>()
  let modes: Mode[] = []
  let release = () => {}
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    createInvite: async () => ({ code: 'TEST-CODE-0001' }),
    exportFile: async () => new Blob(),
    analytics: async () => ({ status: 304 }),
    deleteAccount: async () => ({ status: 200, detail: null, message: '' }),
    snapshot: () => snapshot(),
    async send(req: SendRequest) {
      const mode = modes.shift() ?? 'ok'
      defers.push(req.defer)
      if (mode === 'offline') throw new ApiError(0, 'Could not reach the server.')
      if (mode === 'hang') await new Promise<void>((r) => (release = r))
      const done = answers.get(req.op_id)
      if (done) return done
      if (typeof mode === 'object') return { status: mode.status, detail: mode.detail, message: `TEST ${mode.status}` }
      applied.push(`${req.method} ${req.path}`)
      const answer = { status: 200, detail: null, message: '' }
      answers.set(req.op_id, answer)
      if (mode === 'lose') throw new ApiError(0, 'Could not reach the server.') // applied, answer lost
      return answer
    },
  }
  return { api, applied, defers, answers, next: (...m: Mode[]) => (modes = m), release: () => release() }
}

const tap = (id: number) => actions.setCategory(txn(id), FOOD, 'transaction', 'Test Shop')
const states = () => syncState().ops.map((o) => o.state)

afterEach(async () => {
  timing.syncedMs = 2_000
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('IndexedDB version 1 to 2 keeps the stored copy and adds the outbox', async () => {
  const old = await openDB('flash', 1, {
    upgrade(d) {
      d.createObjectStore('snapshot')
      d.createObjectStore('meta')
      d.createObjectStore('timings', { autoIncrement: true })
    },
  })
  const meta = { etag: '"v1"', fetched_at: 1, owner_id: 'owner-a', user_id: 'user-a', schema_version: 1 }
  await old.put('snapshot', snap, 'current')
  await old.put('meta', meta, 'current')
  old.close()
  assert.deepEqual(await readLocal(), { snapshot: snap, meta })
  assert.deepEqual(await readOutbox(), [])
})

test('an offline tap waits on its item; no total moves', async () => {
  const s = server()
  await startData(s.api, 'user-a')
  s.next('offline', 'offline')
  await startOutbox(s.api)
  const before = dataState().snapshot
  await enqueue(tap(1))
  await drain()
  const op = syncState().ops[0]
  assert.equal(op.state, 'pending')
  const mark = markFor(syncState().ops, txn(1)).category
  assert.equal(mark?.choice, 'Food & Drinks')
  assert.equal(markText(mark!), 'Saved on phone · syncing')
  assert.equal(dataState().snapshot, before) // the snapshot (every total) is untouched
  assert.deepEqual(syncLine(syncState().ops, false), { waiting: '1 saved on phone, syncing', failed: '', signIn: false })
  assert.ok(syncState().nextAttemptAt)
})

test('back online: first in first out, one recompute at the end', async () => {
  const s = server()
  s.next('offline')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await enqueue(actions.setLabel(txn(2), { new: 'Test Trip' }, 'Test Shop'))
  await enqueue(actions.clearLabel(txn(3), 'Test Shop'))
  await drain()
  assert.deepEqual(s.applied, ['PUT /transactions/1/category', 'PUT /transactions/2/label', 'DELETE /transactions/3/label'])
  assert.deepEqual(states(), ['confirmed', 'confirmed', 'confirmed'])
  assert.deepEqual(s.defers.slice(-3), [true, true, false]) // only the last asks for the recompute
})

test('an answer lost after the server applied it: the same op_id, applied once', async () => {
  const s = server()
  s.next('lose')
  await startOutbox(s.api)
  const op = await enqueue(tap(1))
  await drain()
  assert.equal(syncState().ops[0].state, 'pending')
  await drain()
  assert.equal(syncState().ops[0].state, 'confirmed')
  assert.equal(syncState().ops[0].op_id, op.op_id)
  assert.deepEqual(s.applied, ['PUT /transactions/1/category'])
  assert.equal(s.answers.size, 1)
})

test('network, 5xx and 409 in_progress wait 5 s, 15 s, 60 s, then 5 min', async () => {
  assert.deepEqual([1, 2, 3, 4, 5, 9].map(backoffDelay), [5_000, 15_000, 60_000, 300_000, 300_000, 300_000])
  const s = server()
  s.next({ status: 503, detail: 'x' }, { status: 409, detail: 'in_progress' }, 'offline')
  await startOutbox(s.api)
  await enqueue(tap(1))
  for (const wait of [5_000, 15_000, 60_000]) {
    const at = Date.now()
    await drain()
    const due = (syncState().nextAttemptAt ?? 0) - at
    assert.ok(due >= wait && due < wait + 1000, `${due} for ${wait}`)
    assert.equal(syncState().ops[0].state, 'pending')
  }
  await drain()
  assert.equal(syncState().ops[0].state, 'confirmed')
  assert.equal(syncState().nextAttemptAt, null) // a success resets the wait
})

test('401: one token refresh, then "Sign in to sync"; nothing is dropped', async () => {
  const s = server()
  let refreshes = 0
  s.next({ status: 401, detail: null })
  await startOutbox(s.api, async () => (refreshes++, false))
  await enqueue(tap(1))
  await drain()
  assert.equal(refreshes, 1)
  assert.equal(syncState().signIn, true)
  assert.deepEqual(states(), ['pending'])
  assert.equal(syncLine(syncState().ops, syncState().signIn).signIn, true)
  assert.equal((await readOutbox()).length, 1)

  s.next({ status: 401, detail: null }, 'ok')
  await startOutbox(s.api, async () => (refreshes++, true)) // signed in again
  await drain()
  assert.equal(refreshes, 2)
  assert.deepEqual(states(), ['confirmed'])
})

test('a 4xx fails that op only; Retry keeps the op_id, Discard drops it', async () => {
  const s = server()
  s.next({ status: 404, detail: 'no such transaction' }, 'ok', { status: 422, detail: 'idempotency_key_reused' })
  await startOutbox(s.api)
  const first = await enqueue(tap(1))
  await enqueue(tap(2))
  const third = await enqueue(tap(3))
  await drain()
  assert.deepEqual(states(), ['failed', 'confirmed', 'failed'])
  assert.equal(syncState().ops[0].last_error, 'rejected')
  assert.equal(syncState().ops[0].message, 'TEST 404')
  assert.deepEqual(syncLine(syncState().ops, false).failed, '2 not saved')
  await retry(syncState().ops[0])
  await drain()
  assert.equal(syncState().ops[0].op_id, first.op_id)
  assert.equal(syncState().ops[0].state, 'confirmed')
  const reused = third.op_id
  await retry(syncState().ops[2])
  assert.notEqual(syncState().ops[2].op_id, reused) // the key was reused: a new one
  await drain()
  assert.equal(syncState().ops[2].state, 'confirmed')

  s.next({ status: 422, detail: 'not a category of the list' })
  await enqueue(tap(4))
  await drain()
  await discard(syncState().ops[3])
  assert.equal(syncState().ops.length, 3)
  assert.equal((await readOutbox()).length, 3)
})

test('Undo before sending; not once it is being sent', async () => {
  const s = server()
  s.next('hang')
  await startOutbox(s.api)
  await enqueue(tap(1))
  const second = await enqueue(tap(2))
  assert.equal(syncState().ops[0].state, 'sending')
  assert.equal(await undo(syncState().ops[0]), false)
  assert.equal(await undo(second), true)
  s.release()
  await drain()
  assert.deepEqual(s.applied, ['PUT /transactions/1/category'])
  assert.equal((await readOutbox()).length, 1)
})

test('a confirmed op stays until a snapshot asked for after it is applied', async () => {
  timing.syncedMs = 0 // the 'Synced' moment is tested in sync.test.ts
  let answerSnapshot: (a: SnapshotAnswer) => void = () => {}
  const s = server(() => new Promise((r) => (answerSnapshot = r)))
  await startData(s.api, 'user-a') // a refresh is asked for now, before the tap
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  assert.deepEqual(states(), ['confirmed'])
  answerSnapshot({ status: 200, etag: '"old"', snapshot: snap, bytes: 1 }) // asked before the tap
  await new Promise((r) => setTimeout(r, 10))
  assert.deepEqual(states(), ['confirmed'])
  answerSnapshot({ status: 200, etag: '"new"', snapshot: snap, bytes: 1 }) // the refresh after the drain
  for (let i = 0; i < 50 && states().length; i++) await new Promise((r) => setTimeout(r, 10))
  assert.deepEqual(states(), [])
  assert.deepEqual(await readOutbox(), [])
})

test('the outbox survives a reload; an op left sending is sent again', async () => {
  const s = server()
  s.next('offline')
  await startOutbox(s.api)
  await enqueue(tap(1))
  await drain()
  stopOutbox() // the app closes
  const stuck = { ...(await readOutbox())[0], seq: 2, op_id: crypto.randomUUID(), state: 'sending' } as Op
  await putOp(stuck)
  await startOutbox(s.api) // and opens again
  await drain()
  assert.deepEqual(states(), ['confirmed', 'confirmed'])
  assert.equal(s.applied.length, 2)
})

test('sign-out warning counts what is not on the server; To-do leaves out waiting answers', () => {
  const op = (state: Op['state'], targets: Op['targets'], kind = 'x'): Op =>
    ({ seq: 1, op_id: '', created_at: '', kind, item: '', choice: '', method: 'PUT', path: '/category', body: null, targets,
       state, attempts: 0, last_error: '', key_reused: false, confirmed_at: null })
  const ops = [op('pending', { senders: ['s_1'] }), op('failed', { senders: ['s_2'] }), op('confirmed', { txns: [1] }),
    op('sending', { txns: [9], merchants: ['Test Shop'] }, 'All from Test Shop: Food & Drinks')]
  assert.equal(unsynced(ops), 3)
  const todo = {
    senders: [sender('s_1'), sender('s_2'), sender('s_3')], answered: [],
    merchants: [{ name: 'Test Shop', total_paise: 1, count: 1, txn_id: 9 }, { name: 'Other Shop', total_paise: 1, count: 1, txn_id: 8 }],
    unnamed: 0,
  }
  const v = todoView(todo, ops)
  assert.deepEqual(v.senders.map((x) => x.id), ['s_2', 's_3']) // a failed answer is still to do
  assert.deepEqual(v.merchants.map((m) => m.name), ['Other Shop'])
  assert.equal(v.waiting.length, 2)
})

test('D-149: a per-credit answer and undoing a rule are outbox writes with their own paths', () => {
  const credit = actions.answerCredit({ id: 42 }, 'not_paid_back', 'Rohit V')
  assert.deepEqual([credit.method, credit.path, credit.body], ['PUT', '/transactions/42/payback', { answer: 'not_paid_back' }])
  const forget = actions.answerCredit({ id: 42 }, null, 'Rohit V')
  assert.deepEqual([forget.method, forget.path, forget.body], ['DELETE', '/transactions/42/payback', null])
  const undoRule = actions.undoRule({ party_id: 7, name: 'Swiggy', category_name: 'Food & Drinks' })
  assert.deepEqual([undoRule.method, undoRule.path, undoRule.targets], ['DELETE', '/rules/7', { rules: [7] }])
  const rule = actions.setCategory({ id: 9, display_name: 'Swiggy' }, { slug: 'groceries', name: 'Groceries' } as never, 'merchant', 'Swiggy')
  assert.ok(rule.kind.startsWith('All payments to Swiggy'))
})
