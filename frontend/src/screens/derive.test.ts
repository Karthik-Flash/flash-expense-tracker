import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { Txn } from '../api/types.ts'
import { comparable, labelName, ledger, matches, spentByCategory } from './derive.ts'

const txn = (over: Partial<Txn>): Txn => ({
  id: 1,
  time_utc: '2026-10-10T06:00:00Z',
  amount_paise: 10000,
  direction: 'debit',
  display_name: 'Someone',
  role: 'spend',
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

test('people ledger: sent, got back, biggest sent first', () => {
  const rows = ledger([
    txn({ display_name: 'Rohit V', category: 'people', amount_paise: 600000 }),
    txn({ display_name: 'Rohit V', direction: 'credit', role: 'payback', category: 'people', amount_paise: 125000 }),
    txn({ display_name: 'Meera S', category: 'people', amount_paise: 120000 }),
    txn({ display_name: 'Meera S', category: 'gifts_donations', amount_paise: 75000 }),
    txn({ display_name: 'ramesh.k@okaxis', direction: 'credit', role: 'payback', category: 'people', amount_paise: 1000000 }),
    txn({ display_name: 'Pay Co', direction: 'credit', role: 'income', category: 'other', amount_paise: 500000 }),
  ])
  assert.deepEqual(rows, [
    { name: 'Rohit V', sent: 600000, got: 125000 },
    { name: 'Meera S', sent: 120000, got: 0 },
    { name: 'ramesh.k@okaxis', sent: 0, got: 1000000 },
  ])
})

test('last month compares up to the same IST day', () => {
  const october = [
    txn({ time_utc: '2026-10-17T18:29:00Z', amount_paise: 100 }), // 17 Oct, 23:59 IST
    txn({ time_utc: '2026-10-17T18:30:00Z', amount_paise: 200 }), // 18 Oct, 00:00 IST
    txn({ time_utc: '2026-10-30T10:00:00Z', amount_paise: 400, direction: 'credit', role: 'refund' }),
  ]
  assert.deepEqual(comparable(october, '2026-11-17').map((t) => t.amount_paise), [100])
  assert.deepEqual([...spentByCategory(comparable(october, null))], [['food_drinks', -100]])
})

test('name search', () => {
  const t = txn({ display_name: 'Gate 2 Tea Stall' })
  assert.ok(matches(t, ''))
  assert.ok(matches(t, '  tea gate '))
  assert.ok(!matches(t, 'tea canteen'))
  assert.ok(matches(txn({ display_name: null, category: 'cash' }), 'cash'))
})
