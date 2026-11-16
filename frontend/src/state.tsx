import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

import type { Api } from './api/client.ts'

export interface AppState {
  api: Api
  month: string
  setMonth: (month: string) => void
  /** Bumped after every write, so screens load again. */
  version: number
  changed: () => void
  go: (path: string) => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const state = useContext(AppContext)
  if (!state) throw new Error('useApp outside AppContext')
  return state
}

/** Hash route, split: "#/labels/1" -> ["labels", "1"]. The back button works. */
export function useRoute(): string[] {
  const read = () =>
    window.location.hash
      .replace(/^#\/?/, '')
      .split('/')
      .filter(Boolean)
      .map(decodeURIComponent)
  const [parts, setParts] = useState(read)
  useEffect(() => {
    const update = () => setParts(read())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return parts
}

export function go(path: string): void {
  window.location.hash = `/${path}`
}

export type Load<T> =
  | { status: 'loading'; slow: boolean }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

// A request still running after this long is shown as the server waking up.
const SLOW_MS = 1500

/**
 * Run a load, and again when a key changes or after a write (version). After a write the
 * old data stays on screen until the new data arrives; a new key shows loading. Keys are
 * plain values (month, ids, filters). retry() runs it again.
 */
export function useLoad<T>(load: () => Promise<T>, keys: (string | number)[]): [Load<T>, () => void] {
  const { version } = useApp()
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ key: string; id: string; value: Load<T> } | null>(null)
  const [slowFor, setSlowFor] = useState('')
  const latest = useRef(load)
  useEffect(() => {
    latest.current = load
  })
  const key = keys.join('|')
  const id = `${key}#${version}#${attempt}`
  useEffect(() => {
    let live = true
    const timer = window.setTimeout(() => live && setSlowFor(id), SLOW_MS)
    latest.current().then(
      (data) => live && setResult({ key, id, value: { status: 'ready', data } }),
      (error: unknown) =>
        live &&
        setResult({
          key,
          id,
          value: { status: 'error', message: error instanceof Error ? error.message : 'Something went wrong.' },
        }),
    )
    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [key, id])
  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  let value: Load<T> = { status: 'loading', slow: slowFor === id }
  if (result?.id === id) value = result.value
  else if (result?.key === key && result.value.status === 'ready') value = result.value
  return [value, retry]
}
