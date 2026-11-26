// The Android back button (5G-B, D-154). Pure parts, tested in Node: which open sheets can be
// closed, and what Back does next. App.tsx wires it to the phone (native/sms.ts).
//
// Rules: Back closes the topmost open sheet or dialog first; then it steps out of a detail or
// a sheet in the URL (parentOf); then any tab other than Home goes to Home; on Home with
// nothing open it leaves the app (Android's own back, with its predictive animation).

import { HOME, parentOf, type View } from './view.ts'

const stack: (() => void)[] = []
const listeners = new Set<() => void>()
const changed = () => listeners.forEach((f) => f())

/** An open sheet: Back calls `close`. Returns the function that forgets it (on unmount). */
export function pushBack(close: () => void): () => void {
  stack.push(close)
  changed()
  return () => {
    const i = stack.lastIndexOf(close)
    if (i >= 0) stack.splice(i, 1)
    changed()
  }
}

export const openSheets = () => stack.length
export function subscribeBack(f: () => void): () => void {
  listeners.add(f)
  return () => void listeners.delete(f)
}

export type BackAction = { kind: 'close' } | { kind: 'parent' } | { kind: 'home'; view: View } | { kind: 'leave' }

/** What Back does now. `sheets`: how many sheets are open outside the URL's own layers. */
export function backAction(view: View, sheets: number): BackAction {
  if (sheets > 0) return { kind: 'close' }
  if (parentOf(view)) return { kind: 'parent' }
  if (view.tab !== 'home') return { kind: 'home', view: { ...HOME } }
  return { kind: 'leave' }
}

/** Close the topmost sheet; false when none is open. */
export function closeTop(): boolean {
  const top = stack.at(-1)
  if (!top) return false
  top()
  return true
}
