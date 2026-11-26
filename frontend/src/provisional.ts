// 5G-A (D-153): what a notification tap knows about its payment, kept until the snapshot
// holds the full row. Pure, so it is tested in Node (opener.ts does the navigation).

import type { Txn } from './api/types.ts'

/** What a notification knows about its payment (Wire.openItem on the phone). */
export interface OpenItem {
  id: number
  time_utc: string
  amount_paise: number
  direction: 'debit' | 'credit'
  display_name: string | null
  category: string
  category_name: string
  role: Txn['role']
}

let atCategory: number | null = null
const provisional = new Map<number, Txn>()

/** A Txn from a notification's item: enough for the sheet and the category list. */
export function txnOfItem(item: OpenItem): Txn {
  return {
    id: item.id,
    time_utc: item.time_utc,
    amount_paise: item.amount_paise,
    direction: item.direction,
    display_name: item.display_name,
    person_id: null,
    role: item.role,
    role_basis: 'engine',
    category: item.category,
    category_name: item.category_name,
    category_basis: 'engine',
    label: null,
  }
}

/** Remember a tap: its item (when it is for this payment) and whether it asked for categories. */
export function noteOpen(at: { txnId: number; act: 'sheet' | 'category'; item?: OpenItem | null }): void {
  atCategory = at.act === 'category' ? at.txnId : null
  if (at.item && at.item.id === at.txnId && typeof at.item.time_utc === 'string') provisional.set(at.txnId, txnOfItem(at.item))
}

/** The payment a notification opened, until the snapshot holds it. */
export function provisionalTxn(id: number | null): Txn | undefined {
  return id === null ? undefined : provisional.get(id)
}

/** The sheet of `txnId` opens at its category list, once. */
export function takeCategoryOpen(txnId: number): boolean {
  const yes = atCategory === txnId
  atCategory = null
  return yes
}
