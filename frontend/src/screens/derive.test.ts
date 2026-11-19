import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { Snapshot, Txn } from '../api/types.ts'
import { isPersonTxn, labelName, matches, monthData, monthTxns, paymentsText, personKey } from './derive.ts'

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

test('label names: trimmed, 1 to 30 characters, no duplicates in any case', () => {
  assert.deepEqual(labelName('  Goa   trip ', []), { name: 'Goa trip', error: '' })
  assert.match(labelName('   ', []).error, /Type a name/)
  assert.equal(labelName('x'.repeat(30), []).error, '')
  assert.match(labelName('x'.repeat(31), []).error, /at most 30/)
  assert.equal(labelName('₹'.repeat(30), []).error, '')
  assert.match(labelName('goa TRIP', ['Goa trip']).error, /already exists/)
  assert.match(labelName('Goa trip', [' goa  trip ']).error, /already exists/)
  assert.equal(labelName('Goa trip 2', ['Goa trip']).error, '')
})

test('person rows: People spending and paybacks, keyed by person id', () => {
  const people = txn({ category: 'people', person_id: 'p_1' })
  assert.ok(isPersonTxn(people))
  assert.ok(isPersonTxn(txn({ direction: 'credit', role: 'payback', category: 'people' })))
  assert.ok(!isPersonTxn(txn({ category: 'gifts_donations' })))
  assert.ok(!isPersonTxn(txn({ category: 'people', role: 'duplicate' })))
  assert.ok(!isPersonTxn(txn({ direction: 'credit', role: 'income', category: 'other' })))
  assert.equal(personKey(people), 'p_1')
  assert.equal(personKey(txn({ display_name: null, category: 'people' })), 'name:Bank transfer')
})

test('a month of the snapshot: its figures and its rows, newest first', () => {
  const s = {
    months: [{ month: '2026-10' }, { month: '2026-11' }],
    transactions: [
      txn({ id: 3, time_utc: '2026-11-01T10:00:00Z' }),
      txn({ id: 2, time_utc: '2026-10-31T19:00:00Z' }), // 1 Nov 00:30 IST
      txn({ id: 1, time_utc: '2026-10-31T18:00:00Z' }), // 31 Oct 23:30 IST
    ],
  } as unknown as Snapshot
  assert.equal(monthData(s, '2026-11')?.month, '2026-11')
  assert.equal(monthData(s, '2026-09'), undefined)
  assert.deepEqual(monthTxns(s, '2026-11').map((t) => t.id), [3, 2])
  assert.deepEqual(monthTxns(s, '2026-10').map((t) => t.id), [1])
})

test('name search', () => {
  const t = txn({ display_name: 'Gate 2 Tea Stall' })
  assert.ok(matches(t, ''))
  assert.ok(matches(t, '  tea gate '))
  assert.ok(!matches(t, 'tea canteen'))
  assert.ok(matches(txn({ display_name: null, category: 'cash' }), 'cash'))
})

test('merchant cards say how many payments and when, as sender cards do', () => {
  assert.equal(paymentsText(1, '2026-11-12T06:00:00Z'), '1 payment · Thu 12 Nov')
  assert.equal(paymentsText(3, '2026-11-12T19:00:00Z'), '3 payments · last Fri 13 Nov') // 00:30 IST
  assert.equal(paymentsText(2), '2 payments') // a phone copy from before the date was sent
})
