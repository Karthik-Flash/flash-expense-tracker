import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { SendRequest } from './client.ts'
import { FakeApi } from './fake.ts'
import type { Snapshot } from './types.ts'

const signal = new AbortController().signal

async function read(api: FakeApi): Promise<Snapshot> {
  const answer = await api.snapshot(null, signal)
  assert.equal(answer.status, 200)
  return (answer as { snapshot: Snapshot }).snapshot
}

const month = (s: Snapshot, m: string) => s.months.find((x) => x.month === m)!

/** One owner write through send(), as the outbox makes it. */
function act(api: FakeApi, method: SendRequest['method'], path: string, body: unknown = null, op_id: string = crypto.randomUUID()) {
  return api.send({ op_id, method, path, body, defer: false }, signal)
}

test('demo snapshot: the server figures add up like the real one', async () => {
  const s = await read(new FakeApi())
  assert.deepEqual(s.months.map((m) => m.month), ['2026-10', '2026-11'])
  for (const m of s.months) {
    const sum = m.summary
    assert.equal(sum.categories.reduce((total, c) => total + c.amount_paise, 0), sum.spent_paise)
    assert.equal(sum.net_paise, sum.spent_paise - sum.paid_back_paise)
    assert.ok(sum.to_confirm.amount_paise > 0 && sum.to_confirm.senders > 0)
    for (const c of sum.categories.filter((x) => x.slug !== 'people')) {
      assert.equal(m.merchants[c.slug].reduce((total, g) => total + g.total_paise, 0), c.amount_paise)
    }
    assert.equal(m.people.reduce((total, p) => total + p.to_confirm_paise, 0), sum.to_confirm.amount_paise)
    assert.equal(m.chart.slices.reduce((total, x) => total + x.amount_paise, 0), m.chart.total_paise)
  }
  assert.ok(s.transactions.every((t) => Number.isInteger(t.amount_paise) && t.time_utc.endsWith('Z')))
  assert.ok(s.transactions.every((t, i, all) => i === 0 || all[i - 1].time_utc >= t.time_utc))
  assert.ok(s.todo.merchants.length > 0 && s.todo.senders.length > 0)
})

test('the same data gives 304', async () => {
  const api = new FakeApi()
  const first = await api.snapshot(null, signal)
  assert.equal(first.status, 200)
  const etag = (first as { etag: string }).etag
  assert.deepEqual(await api.snapshot(etag, signal), { status: 304 })
  await act(api, 'POST', '/labels', { name: 'Test Fest' })
  assert.equal((await api.snapshot(etag, signal)).status, 200)
})

test('answers change the snapshot the way the API does', async () => {
  const api = new FakeApi()
  const before = await read(api)
  const friend = before.todo.senders.find((s) => s.display_name === 'Arjun K')!
  const key = crypto.randomUUID()
  assert.equal((await act(api, 'PUT', `/senders/${friend.id}`, { answer: 'friend' }, key)).status, 200)
  const after = await read(api)
  assert.equal(month(after, '2026-11').summary.paid_back_paise, month(before, '2026-11').summary.paid_back_paise + 80000)

  // The same op_id again: the same answer, applied once (the server's Idempotency-Key rule).
  assert.equal((await act(api, 'PUT', `/senders/${friend.id}`, { answer: 'friend' }, key)).status, 200)
  assert.equal(month(await read(api), '2026-11').summary.paid_back_paise, month(after, '2026-11').summary.paid_back_paise)

  const vending = before.todo.merchants.find((m) => m.name === 'Vendmart Block B')!
  await act(api, 'PUT', `/transactions/${vending.txn_id}/category`, { category: 'food_drinks', scope: 'merchant' })
  assert.ok(!(await read(api)).todo.merchants.some((m) => m.name === 'Vendmart Block B'))

  assert.equal((await act(api, 'POST', '/labels', { name: 'Test Fest' })).status, 201)
  assert.equal((await act(api, 'POST', '/labels', { name: ' test  FEST ' })).status, 409)
  const made = (await read(api)).labels.find((l) => l.name === 'Test Fest')!
  await act(api, 'PUT', `/transactions/${vending.txn_id}/label`, { label_id: made.id })
  assert.equal((await read(api)).labels.find((l) => l.id === made.id)?.transactions, 1)
  await act(api, 'DELETE', `/transactions/${vending.txn_id}/label`)
  assert.equal((await read(api)).labels.find((l) => l.id === made.id)?.transactions, 0)
  await act(api, 'PUT', `/transactions/${vending.txn_id}/label`, { new_label: 'Test Made' })
  assert.equal((await read(api)).labels.find((l) => l.name === 'Test Made')?.transactions, 1)
  assert.equal(vending.last_time_utc?.endsWith('Z'), true)
})

test('ignored senders, a reset, and the income label', async () => {
  const api = new FakeApi()
  const [first, second] = (await read(api)).todo.senders
  await act(api, 'PUT', `/senders/${first.id}`, { answer: 'ignore' })
  await act(api, 'PUT', `/senders/${second.id}`, { answer: 'income', label: ' Pocket   money ' })
  const answered = (await read(api)).todo.answered
  assert.equal(answered.find((s) => s.id === first.id)?.status, 'ignored')
  assert.equal(answered.find((s) => s.id === second.id)?.income_label, 'Pocket money')
  await act(api, 'DELETE', `/senders/${first.id}`)
  await act(api, 'DELETE', `/senders/${second.id}`)
  const open = (await read(api)).todo.senders.map((s) => s.id)
  assert.ok(open.includes(first.id) && open.includes(second.id))
})

test('previous month and changes', async () => {
  const s = await read(new FakeApi())
  const november = month(s, '2026-11')
  assert.equal(november.summary.previous.month, '2026-10')
  assert.equal(november.changes.spent_paise, november.summary.spent_paise - november.summary.previous.spent_paise)
})

test('demo states', async () => {
  const api = new FakeApi()
  api.setState('error')
  await assert.rejects(api.snapshot(null, signal), /not ready/)
  api.setState('stale')
  assert.equal(month(await read(api), '2026-11').summary.stale, true)
  api.setState('empty')
  const empty = await read(api)
  assert.deepEqual([empty.months.length, empty.transactions.length], [0, 0])
})
