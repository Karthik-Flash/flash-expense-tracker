import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'

import { allTransactions, type Api } from './api/client.ts'
import type { Txn } from './api/types.ts'
import { currentMonth } from './lib/dates.ts'
import { parentOf, parseHash, stack, toHash, type View } from './view.ts'

export interface AppState {
  api: Api
  /** Bumped after every write, so screens load again. */
  version: number
  changed: () => void
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

// Loading. Answers are kept for the session, so moving around the app shows loaded data
// at once. A write bumps `version`: the old data stays on screen until the new arrives.

export type Load<T> =
  | { status: 'loading'; slow: boolean }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

// Only the session's first request can meet a sleeping server: "Starting up" after this long.
const SLOW_MS = 3000
const cache = new Map<string, { version: number; data: unknown }>()
let answered = false

/** Forget every answer, as at the start of a session (the demo state switch). */
export function newSession(): void {
  cache.clear()
  answered = false
}

/** Keys name the data: the same keys must always mean the same load. */
export function useLoad<T>(load: () => Promise<T>, keys: (string | number)[]): [Load<T>, () => void] {
  const { version } = useApp()
  const key = keys.join('|')
  const [attempt, setAttempt] = useState(0)
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null)
  const [slowFor, setSlowFor] = useState('')
  const [, rerender] = useReducer((n: number) => n + 1, 0)
  const latest = useRef(load)
  useEffect(() => {
    latest.current = load
  })
  const hit = cache.get(key)
  const fresh = hit?.version === version
  const id = `${key}#${version}#${attempt}`
  useEffect(() => {
    if (fresh) return
    let live = true
    const timer = answered ? 0 : window.setTimeout(() => live && setSlowFor(id), SLOW_MS)
    latest.current().then(
      (data) => {
        answered = true
        if ((cache.get(key)?.version ?? -1) <= version) cache.set(key, { version, data })
        if (live) rerender()
      },
      (error: unknown) => {
        answered = true
        if (live) setFailed({ id, message: error instanceof Error ? error.message : 'Something went wrong.' })
      },
    )
    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [key, id, version, fresh])
  const retry = () => setAttempt((n) => n + 1)
  let value: Load<T> = { status: 'loading', slow: slowFor === id && !answered }
  if (failed?.id === id) value = { status: 'error', message: failed.message }
  else if (hit) value = { status: 'ready', data: hit.data as T }
  return [value, retry]
}

/** Several loads as one: an error first, then loading, else every answer. */
export function joinLoads<T extends unknown[]>(...loads: { [K in keyof T]: Load<T[K]> }): Load<T> {
  const all = loads as Load<unknown>[]
  const error = all.find((l) => l.status === 'error')
  if (error) return error
  const waiting = all.filter((l) => l.status === 'loading')
  if (waiting.length) return { status: 'loading', slow: waiting.some((l) => l.slow) }
  return { status: 'ready', data: all.map((l) => (l as { data: unknown }).data) as T }
}

/** Every transaction of a month, shared by Home, category detail and Transactions. */
export function useMonthTxns(month: string): [Load<Txn[]>, () => void] {
  const { api } = useApp()
  return useLoad(() => allTransactions(api, { month }), ['txns', month])
}
