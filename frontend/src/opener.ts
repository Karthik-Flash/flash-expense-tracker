// A payment notification was tapped (5B-2, D-142): open that payment's sheet in Transactions,
// or its category list for "Change category". Native code only opens the app; every change
// goes through the outbox as usual.
//
// 5G-A (D-153): a notification is about a payment the phone has just uploaded, so the phone's
// copy of the snapshot does not hold it yet. The notification carries the payment's basics;
// the sheet opens from them at once (provisional.ts) and the full row replaces them when the
// background refresh brings it. Opening waits for the first paint.

import { noteOpen, type OpenItem } from './provisional.ts'
import { navigate } from './state.tsx'
import { HOME } from './view.ts'

const afterPaint = (go: () => void) => requestAnimationFrame(() => requestAnimationFrame(go))

export function openFromNotification(at: { txnId: number; act: 'sheet' | 'category'; item?: OpenItem | null }): void {
  noteOpen(at)
  afterPaint(() => navigate({ ...HOME, tab: 'transactions', txn: at.txnId }, 'push'))
}

// The speed check (scripts/perf-check.mjs) builds with VITE_TEST_HOOKS=1 to stand in for the
// phone's notification tap; every other build leaves this out.
if (import.meta.env.VITE_TEST_HOOKS === '1') (globalThis as { __flashOpen?: typeof openFromNotification }).__flashOpen = openFromNotification
