import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { Txn } from '../api/types.ts'
import { labelName, ledger, matches } from './derive.ts'

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

test('people ledger: one row per person id, confirmed got back, biggest sent first', () => {
  const credit = { direction: 'credit', role: 'payback', category: 'people' } as const
  const rows = ledger([
    txn({ display_name: 'Rohit V', person_id: 'p_1', category: 'people', amount_paise: 600000 }),
    txn({ ...credit, display_name: 'rohit.v@okaxis', person_id: 'p_1', amount_paise: 125000, role_basis: 'owner' }),
    txn({ ...credit, display_name: 'Rohit V', person_id: 'p_1', amount_paise: 5000 }),
    txn({ display_name: 'Meera S', person_id: 's_2', category: 'people', amount_paise: 120000 }),
    txn({ display_name: 'Meera S', person_id: 's_2', category: 'gifts_donations', amount_paise: 75000 }),
    txn({ ...credit, display_name: 'ramesh.k@okaxis', person_id: 's_3', amount_paise: 1000000 }),
    txn({ display_name: 'Pay Co', direction: 'credit', role: 'income', category: 'other', amount_paise: 500000 }),
  ])
  assert.deepEqual(rows, [
    { key: 'p_1', name: 'Rohit V', sent: 600000, got: 125000, toConfirm: 5000 },
    { key: 's_2', name: 'Meera S', sent: 120000, got: 0, toConfirm: 0 },
    { key: 's_3', name: 'ramesh.k@okaxis', sent: 0, got: 0, toConfirm: 1000000 },
  ])
})

test('name search', () => {
  const t = txn({ display_name: 'Gate 2 Tea Stall' })
  assert.ok(matches(t, ''))
  assert.ok(matches(t, '  tea gate '))
  assert.ok(!matches(t, 'tea canteen'))
  assert.ok(matches(txn({ display_name: null, category: 'cash' }), 'cash'))
})
