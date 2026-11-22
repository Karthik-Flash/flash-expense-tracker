// 5B-1: To-do newest first, "Updated hh:mm", pull-to-refresh, investments, paybacks and the
// settings action. Pure helpers; FAKE data.

import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { Sender, Snapshot, Txn } from './api/types.ts'
import { actions, newestFirst, settingsMark, shownSettings, todoView, type Op } from './data/outbox.ts'
import { freshnessLine } from './data/store.ts'
import { PULL_TRIGGER_PX, canStart, pullDistance, pullState } from './pull.ts'
import { asksPaidBack, inCategory, investedLine, investmentTag, paybackLines, senderOfCredit } from './screens/derive.ts'

const txn = (over: Partial<Txn>): Txn => ({
  id: 1,
  time_utc: '2026-10-10T06:00:00Z',
  amount_paise: 10000,
  direction: 'debit',
  display_name: 'Someone',
  person_id: null,
  role: 'spend',
  role_basis: 'engine',
  category: 'food_drinks',
  category_name: 'Food & Drinks',
  category_basis: 'engine',
  label: null,
  ...over,
})

const sender = (over: Partial<Sender>): Sender => ({
  id: 's_1',
  display_name: 'Test Friend',
  total_paise: 5000,
  count: 1,
  role: 'payback',
  basis: 'engine',
  status: 'to_confirm',
  last_time_utc: '2026-10-10T06:00:00Z',
  income_label: null,
  person_id: 'p_1',
  txn_id: 2,
  ...over,
})

const todo = (over: Partial<Snapshot['todo']> = {}): Snapshot['todo'] => ({
  senders: [],
  answered: [],
  merchants: [],
  unnamed: 0,
  transfers: [],
  suggestions: [],
  ...over,
})

test('every To-do list is newest first, ties by the higher id, also from an old phone copy', () => {
  const t = todoView(
    todo({
      senders: [
        sender({ id: 's_a', last_time_utc: '2026-10-01T06:00:00Z', txn_id: 5 }),
        sender({ id: 's_b', last_time_utc: '2026-10-09T06:00:00Z', txn_id: 3 }),
        sender({ id: 's_c', last_time_utc: '2026-10-09T06:00:00Z', txn_id: 7 }),
      ],
      merchants: [
        { name: 'Old', total_paise: 9000, count: 1, txn_id: 1, last_time_utc: '2026-09-01T06:00:00Z' },
        { name: 'New', total_paise: 10, count: 1, txn_id: 2, last_time_utc: '2026-10-01T06:00:00.123456Z' },
        { name: 'Unknown', total_paise: 10, count: 1, txn_id: 9 }, // before 4B-2: no time, last
      ],
      transfers: [
        { debit: 1, credit: 2, amount_paise: 1, from_bank: 'HDFC', to_bank: 'SBI', debit_time_utc: '2026-09-01T06:00:00Z', credit_time_utc: '2026-09-01T06:10:00Z' },
        { debit: 3, credit: 4, amount_paise: 1, from_bank: 'HDFC', to_bank: 'SBI', debit_time_utc: '2026-10-01T06:00:00Z', credit_time_utc: '2026-10-01T06:10:00Z' },
      ],
      suggestions: [
        { kind: 'investment', key: 'a', txn_id: 1, name: 'A', count: 1, last_time_utc: '2026-09-01T06:00:00Z' },
        { kind: 'investment', key: 'b', txn_id: 2, name: 'B', count: 3, last_time_utc: '2026-10-01T06:00:00Z' },
      ],
    }),
    [],
  )
  assert.deepEqual(t.senders.map((s) => s.id), ['s_c', 's_b', 's_a'])
  assert.deepEqual(t.merchants.map((m) => m.name), ['New', 'Old', 'Unknown'])
  assert.deepEqual(t.transfers.map((x) => x.debit), [3, 1])
  assert.deepEqual(t.suggestions.map((x) => x.key), ['b', 'a'])
  assert.deepEqual(newestFirst([], () => undefined, () => 0), [])
})

test('"Updated 14:05" today, with the day before; offline still says how old', () => {
  const now = Date.parse('2026-11-19T09:00:00Z') // 14:30 IST
  assert.equal(freshnessLine({ fetchedAt: Date.parse('2026-11-19T08:35:00Z'), refreshing: false, failed: false }, now), 'Updated 14:05')
  assert.equal(freshnessLine({ fetchedAt: Date.parse('2026-11-17T08:35:00Z'), refreshing: false, failed: false }, now), 'Updated Tue 17 Nov, 14:05')
  assert.equal(freshnessLine({ fetchedAt: now - 5 * 60_000, refreshing: false, failed: true }, now), 'Offline · showing data from 5 min ago')
  assert.equal(freshnessLine({ fetchedAt: now, refreshing: true, failed: false }, now), 'Updating…')
})

test('pull-to-refresh: from the top only, half speed, a trigger, a limit', () => {
  assert.equal(pullDistance(-30), 0)
  assert.equal(pullDistance(60), 30)
  assert.equal(pullDistance(1000), 80)
  assert.equal(pullState(0), 'idle')
  assert.equal(pullState(PULL_TRIGGER_PX * 2 - 2), 'pulling')
  assert.equal(pullState(PULL_TRIGGER_PX * 2), 'ready')
  assert.equal(canStart(0, false), true)
  assert.equal(canStart(12, false), false) // scrolled down: the page scrolls
  assert.equal(canStart(0, true), false) // a sheet or a field
})

test('investments: the tag, the filter and the Home line', () => {
  const confirmed = txn({ id: 1, role: 'investment', category: 'investments', investment: 'confirmed' })
  const suggested = txn({ id: 2, category: 'uncategorised', investment: 'suggested' })
  const plain = txn({ id: 3 })
  assert.deepEqual([confirmed, suggested, plain].map(investmentTag), ['Investment', 'Investment, to confirm', ''])
  assert.deepEqual([confirmed, suggested, plain].filter((t) => inCategory(t, 'investments')).map((t) => t.id), [1, 2])
  assert.deepEqual([confirmed, suggested, plain].filter((t) => inCategory(t, 'food_drinks')).map((t) => t.id), [3])
  assert.equal(inCategory(plain, null), true)
  assert.equal(investedLine({ invested_paise: 300000, invested_to_confirm_paise: 50000, investments_in_spent: false }), 'Invested ₹3,000 · Invested (to confirm) ₹500, in Spent')
  assert.equal(investedLine({ invested_paise: 300000, investments_in_spent: true }), 'Invested ₹3,000, in Spent')
  assert.equal(investedLine({}), '') // an older phone copy: nothing to say
})

test('a credit from a person asks Paid back with its sender; a debit lists its paybacks', () => {
  const back = txn({ id: 2, direction: 'credit', role: 'payback', person_id: 'p_1', amount_paise: 40000, display_name: 'Test Friend' })
  const pay = txn({ id: 1, person_id: 'p_1', amount_paise: 90000 })
  const s = sender({})
  assert.equal(senderOfCredit(back, todo({ senders: [s] })), s)
  assert.equal(senderOfCredit(back, todo({ answered: [s] })), s) // answered: can be changed
  assert.equal(senderOfCredit(pay, todo({ senders: [s] })), undefined)
  const lone = txn({ id: 7, direction: 'credit', role: 'uncertain' }) // no text: its own sender
  assert.equal(senderOfCredit(lone, todo({ senders: [sender({ person_id: null, txn_id: 7 })] }))?.txn_id, 7)
  assert.equal(asksPaidBack(back, s), true)
  assert.equal(asksPaidBack(txn({ direction: 'credit', role: 'refund' }), s), false)
  const name = (t: Txn) => t.display_name ?? ''
  const snap = (status: 'linked' | 'candidate', basis: 'engine' | 'owner') => ({
    transactions: [pay, { ...back, role_basis: basis }],
    paybacks: [{ debit: 1, credit: 2, status }],
  })
  assert.deepEqual(paybackLines(pay, snap('linked', 'owner'), name), ['₹400 paid back by Test Friend'])
  assert.deepEqual(paybackLines(pay, snap('linked', 'engine'), name), ['₹400 from Test Friend, to confirm'])
  assert.deepEqual(paybackLines(pay, snap('candidate', 'owner'), name), ['₹400 from Test Friend on Sat 10 Oct may be for this'])
  assert.deepEqual(paybackLines(pay, { transactions: [pay] }, name), []) // an older phone copy
})

test('the setting goes through the outbox and shows at once', () => {
  const op = actions.setSettings({ count_investments_in_spent: true })
  assert.deepEqual([op.method, op.path, op.body], ['PUT', '/profile/settings', { count_investments_in_spent: true }])
  const waiting = { ...op, seq: 1, op_id: 'x', state: 'pending' } as unknown as Op
  assert.equal(settingsMark([waiting]), waiting)
  assert.deepEqual(shownSettings([waiting], { count_investments_in_spent: false }), { count_investments_in_spent: true })
  assert.deepEqual(shownSettings([{ ...waiting, state: 'failed' } as Op], undefined), { count_investments_in_spent: false })
  assert.deepEqual(shownSettings([], { count_investments_in_spent: true }), { count_investments_in_spent: true })
})
