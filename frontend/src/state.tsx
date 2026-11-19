import { createContext, useContext, useLayoutEffect, useMemo, useSyncExternalStore } from 'react'

import type { Api } from './api/client.ts'
import { currentMonth } from './lib/dates.ts'
import { parentOf, parseHash, stack, toHash, type View } from './view.ts'

export interface AppState {
  /** The adapter. Reads come from the snapshot (data/store.ts), writes from the outbox. */
  api: Api
  signOut: () => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const state = useContext(AppContext)
  if (!state) throw new Error('useApp outside AppContext')
  return state
}

// Navigation. The view lives only in the URL hash (view.ts). Opening a layer (detail or
// sheet) pushes a history entry marked `child`, so Back (in the app, the browser or
// Android) closes it. Filters, search and the month replace the entry instead.

type Move = 'open' | 'push' | 'replace'
const NAVIGATE = 'flash:navigate'
/** Scroll position of each list, by its hash without an open sheet. */
const scrolls = new Map<string, number>()
let lastMove: Move | 'pop' = 'replace'

const baseOf = (view: View) => toHash({ ...view, txn: null })

/** Once, before the first render: give a cold deep link the history under it. */
export function startNavigation(): void {
  history.scrollRestoration = 'manual'
  const view = parseHash(location.hash)
  if (history.state !== null) {
    history.replaceState(history.state, '', toHash(view))
    return
  }
  const steps = stack(view)
  history.replaceState({ child: false }, '', toHash(steps[0]))
  for (const step of steps.slice(1)) history.pushState({ child: true }, '', toHash(step))
}

export function navigate(view: View, move: Move): void {
  const hash = toHash(view)
  if (hash === location.hash) return
  if (move === 'replace') {
    history.replaceState(history.state, '', hash)
  } else {
    scrolls.set(baseOf(parseHash(location.hash)), window.scrollY)
    history.pushState({ child: move === 'open' }, '', hash)
  }
  lastMove = move
  window.dispatchEvent(new Event(NAVIGATE))
}

function subscribe(onChange: () => void) {
  const onPop = () => {
    lastMove = 'pop'
    onChange()
  }
  window.addEventListener('popstate', onPop)
  window.addEventListener(NAVIGATE, onChange)
  return () => {
    window.removeEventListener('popstate', onPop)
    window.removeEventListener(NAVIGATE, onChange)
  }
}

export function useView(): View {
  const hash = useSyncExternalStore(subscribe, () => location.hash)
  return useMemo(() => parseHash(hash), [hash])
}

export function useNav() {
  const view = useView()
  return {
    view,
    month: view.month ?? currentMonth(),
    /** A new layer: a detail or a sheet. */
    open: (patch: Partial<View>) => navigate({ ...view, ...patch }, 'open'),
    /** Same layer, new month, filter or search. */
    replace: (patch: Partial<View>) => navigate({ ...view, ...patch }, 'replace'),
    /** Close the topmost layer. */
    back: () => {
      const parent = parentOf(view)
      if (!parent) return
      if ((history.state as { child?: boolean } | null)?.child) history.back()
      else navigate(parent, 'replace')
    },
  }
}

/** A new screen starts at the top; Back returns to where the list was. A sheet leaves it alone. */
export function useScrollMemory(view: View): void {
  const base = baseOf(view)
  useLayoutEffect(() => {
    if (lastMove === 'pop') window.scrollTo(0, scrolls.get(base) ?? 0)
    else if (lastMove !== 'replace') window.scrollTo(0, 0)
  }, [base])
}
