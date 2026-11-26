import assert from 'node:assert/strict'
import { test } from 'node:test'

import { noteOpen, provisionalTxn, takeCategoryOpen, type OpenItem } from './provisional.ts'

const item: OpenItem = { id: 901, time_utc: '2026-11-20T06:00:00Z', amount_paise: 3300, direction: 'debit', display_name: 'Test Kiosk', category: 'food_drinks', category_name: 'Food & Drinks', role: 'spend' }

test('5G-A: a notification opens its payment from the basics it carries, before any download', () => {
  assert.equal(provisionalTxn(901), undefined)
  noteOpen({ txnId: 901, act: 'category', item })
  const t = provisionalTxn(901)
  assert.ok(t)
  assert.deepEqual([t.amount_paise, t.category, t.display_name, t.role_basis, t.person_id, t.label], [3300, 'food_drinks', 'Test Kiosk', 'engine', null, null])
  assert.equal(takeCategoryOpen(901), true)
  assert.equal(takeCategoryOpen(901), false) // once
  assert.equal(provisionalTxn(null), undefined)
  // An APK from before sends no item; an item for another payment is ignored.
  noteOpen({ txnId: 902, act: 'sheet' })
  noteOpen({ txnId: 903, act: 'sheet', item })
  assert.equal(provisionalTxn(902), undefined)
  assert.equal(provisionalTxn(903), undefined)
})
