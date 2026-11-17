import assert from 'node:assert/strict'
import { test } from 'node:test'

import { allTransactions, ApiError, spentEffect } from './client.ts'
import { FakeApi } from './fake.ts'

test('demo month: the breakdown adds up to Spent, Net = Spent - Paid back', async () => {
  const api = new FakeApi()
  for (const month of ['2026-10', '2026-11']) {
    const s = await api.summary(month)
    assert.equal(s.categories.reduce((sum, c) => sum + c.amount_paise, 0), s.spent_paise)
    assert.equal(s.net_paise, s.spent_paise - s.paid_back_paise)
    assert.ok(s.to_confirm.amount_paise > 0 && s.to_confirm.senders > 0)
    const txns = await allTransactions(api, { month })
    assert.equal(txns.reduce((sum, t) => sum + spentEffect(t), 0), s.spent_paise)
    assert.ok(txns.every((t) => Number.isInteger(t.amount_paise) && t.time_utc.endsWith('Z')))
  }
  const empty = await api.summary('2026-12')
  assert.deepEqual([empty.spent_paise, empty.categories.length], [0, 0])
})

test('pages follow the cursor without repeats', async () => {
  const api = new FakeApi()
  const all = await allTransactions(api, { month: '2026-11' })
  const first = await api.transactions({ month: '2026-11', limit: 10 })
  assert.equal(first.items.length, 10)
  const second = await api.transactions({ month: '2026-11', limit: 10, cursor: first.next_cursor ?? '' })
  assert.deepEqual([...first.items, ...second.items].map((t) => t.id), all.slice(0, 20).map((t) => t.id))
})

test('answers change the totals the way the API does', async () => {
  const api = new FakeApi()
  const before = await api.summary('2026-11')
  const open = await api.senders('to_confirm')
  const friend = open.find((s) => s.display_name === 'Arjun K')!
  await api.answerSender(friend.id, { answer: 'friend' })
  const after = await api.summary('2026-11')
  assert.equal(after.paid_back_paise, before.paid_back_paise + 80000)
  assert.equal(after.net_paise, before.net_paise - 80000)

  const vending = (await allTransactions(api, { category: 'uncategorised' })).find(
    (t) => t.display_name === 'Vendmart Block B',
  )!
  await api.setCategory(vending.id, 'food_drinks', 'merchant')
  const left = await allTransactions(api, { category: 'uncategorised' })
  assert.ok(!left.some((t) => t.display_name === 'Vendmart Block B'))

  const made = await api.createLabel('Test Fest')
  await assert.rejects(api.createLabel(' test  FEST '), (e: ApiError) => e.status === 409)
  await api.setLabel(vending.id, made.id)
  assert.equal((await api.label(made.id)).transactions, 1)
  await api.clearLabel(vending.id)
  assert.equal((await api.label(made.id)).transactions, 0)
})

test('ignored senders, a reset, and the income label', async () => {
  const api = new FakeApi()
  const [first, second] = await api.senders('to_confirm')
  await api.answerSender(first.id, { answer: 'ignore' })
  await api.answerSender(second.id, { answer: 'income', label: ' Pocket   money ' })
  assert.deepEqual((await api.senders('ignored')).map((s) => s.id), [first.id])
  const income = (await api.senders('confirmed')).find((s) => s.id === second.id)!
  assert.equal(income.income_label, 'Pocket money')
  await api.resetSender(first.id)
  await api.resetSender(second.id)
  const open = (await api.senders('to_confirm')).map((s) => s.id)
  assert.ok(open.includes(first.id) && open.includes(second.id))
  const one = (await api.transactions({ month: '2026-11', limit: 1 })).items[0]
  assert.deepEqual(await api.transaction(one.id), one)
})

test('previous month: whole for a past month', async () => {
  const api = new FakeApi()
  const october = await api.summary('2026-10')
  const november = await api.summary('2026-11')
  assert.equal(november.previous.month, '2026-10')
  assert.ok(november.previous.whole || november.previous.spent_paise <= october.spent_paise)
  assert.deepEqual((await api.summary('2026-12')).previous.spent_paise, november.spent_paise)
})

test('demo states', async () => {
  const api = new FakeApi()
  api.setState('error')
  await assert.rejects(api.summary('2026-11'), /not ready/)
  api.setState('stale')
  assert.equal((await api.summary('2026-11')).stale, true)
  api.setState('empty')
  assert.equal((await api.summary('2026-11')).spent_paise, 0)
})
