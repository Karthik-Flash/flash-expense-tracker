// Checks on the phone (4F-A, D-101, D-103): Looks right, Not a payment and Count it again go
// through the outbox, wait offline, and leave "Check these payments" at once. FAKE only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import { FakeApi } from '../api/fake.ts'
import type { Snapshot, Txn } from '../api/types.ts'
import { wipeLocal } from './local.ts'
import { actions, checksView, drain, enqueue, markFor, startOutbox, stopOutbox, syncState, todoView } from './outbox.ts'
import { clearData } from './store.ts'

const row = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id,
  time_utc: '2026-11-12T07:50:00Z',
  amount_paise: 34000,
  direction: 'debit',
  display_name: 'Campus Bookshop',
  person_id: null,
  role: 'spend',
  role_basis: 'engine',
  category: 'uncategorised',
  category_name: 'Uncategorised',
  category_basis: 'engine',
  label: null,
  generic: true,
  check: true,
  ...extra,
})

function server() {
  const sent: SendRequest[] = []
  let offline = true
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      if (offline) throw new ApiError(0, 'Could not reach the server.')
      sent.push(req)
      return { status: 200, detail: null, message: '' }
    },
  }
  return { api, sent, online: () => (offline = false) }
}

afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('offline: looks right and not a payment wait, leave the check list, then sync in order', async () => {
  const s = server()
  await startOutbox(s.api)
  const a = row(1)
  const b = row(2, { display_name: 'Priya N', direction: 'credit', role: 'uncertain' })
  const c = row(3, { generic: false, check: false })
  assert.deepEqual(checksView([a, b, c], syncState().ops).map((t) => t.id), [1, 2]) // only generic rows ask
  await enqueue(actions.looksRight(a, 'Campus Bookshop'))
  await enqueue(actions.notAPayment(b, 'Priya N'))
  await enqueue(actions.countAgain(b, 'Priya N'))
  await drain()
  const ops = syncState().ops
  assert.deepEqual(ops.map((o) => o.state), ['pending', 'pending', 'pending'])
  assert.deepEqual(checksView([a, b, c], ops), []) // answered offline: gone from the list at once
  assert.equal(markFor(ops, b).counted?.choice, 'Counted again') // the newest action shows
  const empty = { senders: [], answered: [], merchants: [], unnamed: 0 }
  assert.deepEqual(todoView(empty, ops).waiting.map((o) => o.kind), ['Looks right', 'Not a payment'])

  s.online()
  await drain()
  assert.deepEqual(
    s.sent.map((r) => [r.method, r.path, r.body]),
    [
      ['PUT', '/transactions/1/check', null],
      ['PUT', '/transactions/2/ignore', null],
      ['DELETE', '/transactions/2/ignore', null],
    ],
  )
  assert.ok(s.sent.every((r) => typeof r.op_id === 'string' && r.op_id.length > 0))
})

test('demo server: check, not a payment and count again as the real one; totals only from it', async () => {
  const fake = new FakeApi()
  const signal = new AbortController().signal
  const snap = async (): Promise<Snapshot> => {
    const a = await fake.snapshot(null, signal)
    return a.status === 200 ? a.snapshot : (null as never)
  }
  const send = (method: SendRequest['method'], path: string) => fake.send({ op_id: crypto.randomUUID(), method, path, body: null, defer: false }, signal)
  const before = await snap()
  const generic = before.transactions.filter((t) => t.generic)
  assert.equal(generic.length, 3)
  assert.ok(generic.every((t) => t.check))
  const debit = generic.find((t) => t.direction === 'debit' && t.role === 'spend')!
  const nov = (s: Snapshot) => s.months.find((m) => m.month === '2026-11')!.summary.spent_paise

  assert.equal((await send('PUT', `/transactions/${debit.id}/check`)).status, 200)
  const checked = await snap()
  assert.equal(checked.transactions.find((t) => t.id === debit.id)!.check, false)
  assert.equal(nov(checked), nov(before)) // a check changes no total

  assert.equal((await send('PUT', `/transactions/${debit.id}/ignore`)).status, 200)
  const ignored = await snap()
  assert.equal(ignored.transactions.find((t) => t.id === debit.id)!.role, 'ignored')
  assert.equal(nov(ignored), nov(before) - debit.amount_paise)

  assert.equal((await send('DELETE', `/transactions/${debit.id}/ignore`)).status, 200)
  assert.equal(nov(await snap()), nov(before))
  const plain = before.transactions.find((t) => !t.generic)!
  assert.equal((await send('PUT', `/transactions/${plain.id}/check`)).status, 422)
})
