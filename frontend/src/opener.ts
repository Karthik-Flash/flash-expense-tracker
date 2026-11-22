// A payment notification was tapped (5B-2, D-142): open that payment's sheet in Transactions,
// or its category list for "Change category". Native code only opens the app; every change
// goes through the outbox as usual.

import { navigate } from './state.tsx'
import { HOME } from './view.ts'

let atCategory: number | null = null

export function openFromNotification(at: { txnId: number; act: 'sheet' | 'category' }): void {
  atCategory = at.act === 'category' ? at.txnId : null
  navigate({ ...HOME, tab: 'transactions', txn: at.txnId }, 'push')
}

/** The sheet of `txnId` opens at its category list, once. */
export function takeCategoryOpen(txnId: number): boolean {
  const yes = atCategory === txnId
  atCategory = null
  return yes
}
