// The person sheet (4H, D-110) and the carry-over fixes: a person's category default, the
// sender answer and "just this one" go through the outbox, wait offline on their rows and
// send in order once online; a label made offline can be picked again; a refused action
// stays on its item. The demo server applies them like the real one. FAKE data only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import { FakeApi } from '../api/fake.ts'
import type { Category, Sender, Snapshot, Txn } from '../api/types.ts'
import { wipeLocal } from './local.ts'
import {
  actions,
  drain,
  enqueue,
  markFor,
  markText,
  personCategoryMark,
  senderMark,
  startOutbox,
  stopOutbox,
  syncState,
  waitingLabels,
} from './outbox.ts'
import { clearData } from './store.ts'

const RENT: Category = { slug: 'rent_hostel', name: 'Rent & Hostel' }
const FOOD: Category = { slug: 'food_drinks', name: 'Food & Drinks' }
const row = (id: number, extra: Partial<Txn> = {}): Txn => ({
  id, time_utc: '2026-11-10T06:00:00Z', amount_paise: 10000, direction: 'debit', display_name: 'Test Ravi',
  person_id: 'p_7', role: 'spend', role_basis: 'engine', category: 'people', category_name: 'People',
  category_basis: 'engine', label: null, ...extra,
})
const sender: Sender = {
  id: 's_ravi', display_name: 'Test Ravi', total_paise: 50000, count: 2, role: 'uncertain', basis: 'engine',
  status: 'to_confirm', last_time_utc: '2026-11-10T06:00:00Z', income_label: null, person_id: 'p_7', txn_id: 3,
}
const ravi = { key: 'p_7', name: 'Test Ravi' }

/** A server that cannot be reached, then one that answers each request with the next status. */
function server(statuses: number[] = []) {
  const sent: SendRequest[] = []
  let offline = true
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    createInvite: async () => ({ code: 'TEST-CODE-0001' }),
    exportFile: async () => new Blob(),
    analytics: async () => ({ status: 304 }),
    deleteAccount: async () => ({ status: 200, detail: null, message: '' }),
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      if (offline) throw new ApiError(0, 'Could not reach the server.')
      sent.push(req)
      const status = statuses.shift() ?? 200
      return { status, detail: status === 409 ? 'conflict' : null, message: status === 409 ? 'Test conflict.' : '' }
    },
  }
  return { api, sent, online: () => (offline = false) }
}

afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('person sheet, offline: category default, answer and just-this-one wait on their rows, then send in order', async () => {
  const s = server()
  await startOutbox(s.api)
  // "Payments to them count as": the party default, by one of their payments.
  await enqueue(actions.setCategory(row(1), RENT, 'merchant', 'Test Ravi', ravi))
  // "Money from them is": Family.
  await enqueue(actions.answerSender(sender, { answer: 'income', label: 'Family' }))
  // A recent payment: just this one.
  await enqueue(actions.setCategory(row(2), FOOD, 'transaction', 'Test Ravi'))
  await drain()
  const ops = syncState().ops
  assert.deepEqual(ops.map((o) => o.state), ['pending', 'pending', 'pending']) // first in, first out: the first one tried

  // Every row of the person shows the default at once, under any name the bank used.
  const joined = row(9, { display_name: 'Test R V', identifier: '*rv@okaxis' })
  assert.equal(markFor(ops, joined).category?.choice, 'Rent & Hostel')
  assert.equal(markText(markFor(ops, joined).category!), 'Saved on phone · syncing')
  assert.equal(markFor(ops, row(2)).category?.choice, 'Food & Drinks') // the one-off is newer there
  assert.equal(markFor(ops, row(3, { person_id: 'p_8', display_name: 'Test Other' })).category, undefined)
  assert.equal(markFor(ops, row(4, { direction: 'credit', role: 'payback' })).category, undefined) // money in has no category
  assert.equal(personCategoryMark(ops, 'p_7')?.slug, 'rent_hostel')
  assert.equal(senderMark(ops, ['s_ravi'])?.choice, 'Income: Family')

  s.online()
  await drain()
  assert.deepEqual(
    s.sent.map((r) => [r.method, r.path, r.body]),
    [
      ['PUT', '/transactions/1/category', { category: 'rent_hostel', scope: 'merchant' }],
      ['PUT', '/senders/s_ravi', { answer: 'income', label: 'Family' }],
      ['PUT', '/transactions/2/category', { category: 'food_drinks', scope: 'transaction' }],
    ],
  )
  assert.ok(syncState().ops.every((o) => o.state === 'confirmed'))
})

test('person sheet, online: each answer is one write per sender, sent at once', async () => {
  const s = server()
  s.online()
  await startOutbox(s.api)
  for (const answer of [{ answer: 'friend' }, { answer: 'ignore' }, { answer: 'income', label: 'Test Stipend' }] as const) {
    await enqueue(actions.answerSender(sender, answer))
  }
  await drain()
  assert.deepEqual(
    s.sent.map((r) => r.body),
    [{ answer: 'friend' }, { answer: 'ignore' }, { answer: 'income', label: 'Test Stipend' }],
  )
  assert.equal(new Set(s.sent.map((r) => r.op_id)).size, 3) // each with its own key
})

test('a refused action stays on its item: "Not saved", the row keeps the server value', async () => {
  const s = server([409])
  s.online()
  await startOutbox(s.api)
  await enqueue(actions.setCategory(row(5), FOOD, 'transaction', 'Test Ravi'))
  await drain()
  const mark = markFor(syncState().ops, row(5))
  assert.equal(mark.category, undefined) // the choice is not shown as made
  assert.equal(mark.failed?.state, 'failed')
  assert.equal(markText(mark.failed!), 'Not saved · needs your choice')
})

test('a label made offline can be picked on another payment before it syncs', async () => {
  const s = server()
  await startOutbox(s.api)
  await enqueue(actions.setLabel(row(1), { new: 'Test Goa' }, 'Test Ravi'))
  const ops = syncState().ops
  assert.deepEqual(waitingLabels(ops, ['Test Hostel']), ['Test Goa'])
  assert.deepEqual(waitingLabels(ops, ['test goa']), []) // on the server already
  await enqueue(actions.setLabel(row(2), { new: 'Test Goa' }, 'Test Ravi'))
  await drain()
  s.online()
  await drain()
  assert.deepEqual(s.sent.map((r) => r.body), [{ new_label: 'Test Goa' }, { new_label: 'Test Goa' }])
})

test('demo server: a person default covers all their payments; a waiting label name is reused', async () => {
  const fake = new FakeApi()
  const signal = new AbortController().signal
  const snap = async (): Promise<Snapshot> => {
    const a = await fake.snapshot(null, signal)
    return a.status === 200 ? a.snapshot : (null as never)
  }
  const send = (method: SendRequest['method'], path: string, body: unknown = null) =>
    fake.send({ op_id: crypto.randomUUID(), method, path, body, defer: false }, signal)
  const before = await snap()
  const meera = before.people!.find((p) => p.name === 'Meera S')!
  const spends = before.transactions.filter((t) => t.person_id === meera.key && t.role === 'spend')
  assert.ok(spends.length >= 2)
  assert.equal((await send('PUT', `/transactions/${spends[0].id}/category`, { category: 'rent_hostel', scope: 'merchant' })).status, 200)
  const after = await snap()
  const mine = after.transactions.filter((t) => t.person_id === meera.key && t.role === 'spend')
  assert.ok(mine.every((t) => t.category === 'rent_hostel' && t.category_basis === 'owner'))
  // Totals come from the server, as before: Spent is unchanged by a category.
  assert.equal(after.months.at(-1)!.summary.spent_paise, before.months.at(-1)!.summary.spent_paise)

  const [a, b] = after.transactions.filter((t) => t.role === 'spend')
  assert.equal((await send('PUT', `/transactions/${a.id}/label`, { new_label: 'Test Trip' })).status, 200)
  assert.equal((await send('PUT', `/transactions/${b.id}/label`, { new_label: 'test  trip' })).status, 200)
  const labelled = (await snap()).transactions.filter((t) => t.label?.name === 'Test Trip')
  assert.deepEqual(labelled.map((t) => t.id).sort(), [a.id, b.id].sort())
  assert.equal((await send('POST', '/labels', { name: 'TEST TRIP' })).status, 409) // a new label: still a conflict
})
