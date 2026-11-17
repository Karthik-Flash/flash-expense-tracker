import { useCallback, useMemo, useState } from 'react'

import { api, demoApi } from './api/index.ts'
import { DEMO_STATES, type DemoState } from './api/fake.ts'
import { AppContext, navigate, newSession, useApp, useLoad, useScrollMemory, useView, type AppState } from './state.tsx'
import { CategoryDetail, Home } from './screens/Home.tsx'
import { LabelDetail, Labels } from './screens/Labels.tsx'
import { Login } from './screens/Login.tsx'
import { Logos } from './screens/Logos.tsx'
import { TodoScreen } from './screens/Todo.tsx'
import { loadTodo } from './screens/todo-data.ts'
import { Transactions } from './screens/Transactions.tsx'
import { Icon } from './ui.tsx'
import { HOME, type Tab, type View } from './view.ts'

const SIGNED_IN = 'flash-demo-signed-in'
const TABS: [Tab, string, string][] = [
  ['home', 'Home', 'house'],
  ['transactions', 'Transactions', 'receipt-text'],
  ['todo', 'To-do', 'list-checks'],
  ['labels', 'Labels', 'tag'],
]

function signedIn(): boolean {
  try {
    return sessionStorage.getItem(SIGNED_IN) === '1'
  } catch {
    return false
  }
}

export default function App() {
  const view = useView()
  const [ready, setReady] = useState(signedIn)
  const [version, setVersion] = useState(0)
  const changed = useCallback(() => setVersion((v) => v + 1), [])
  const state: AppState = useMemo(() => ({ api, version, changed }), [version, changed])
  if (view.tab === 'dev' && (import.meta.env.DEV || api.demo)) return <Logos />
  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-dvh flex-col">
        {api.demo && <DemoBanner />}
        {ready ? (
          <Shell view={view} />
        ) : (
          <Login
            demo={api.demo}
            onDone={() => {
              try {
                sessionStorage.setItem(SIGNED_IN, '1')
              } catch {
                // Private mode: stay signed in for this page only.
              }
              setReady(true)
            }}
          />
        )}
      </div>
    </AppContext.Provider>
  )
}

function Shell({ view }: { view: View }) {
  useScrollMemory(view)
  return (
    <div className="mx-auto w-full max-w-[480px] flex-1 pb-[calc(5rem+env(safe-area-inset-bottom))]">
      <main>
        <Screen view={view} />
      </main>
      <Nav view={view} />
    </div>
  )
}

function Screen({ view }: { view: View }) {
  const [a, b, c] = view.path
  if (view.tab === 'home' && a === 'category' && b) return <CategoryDetail slug={b} name={c} />
  if (view.tab === 'transactions') return <Transactions />
  if (view.tab === 'todo') return <TodoScreen />
  if (view.tab === 'labels' && a) return <LabelDetail id={Number(a)} />
  if (view.tab === 'labels') return <Labels />
  return <Home />
}

function Nav({ view }: { view: View }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]" aria-label="Main">
      <ul className="mx-auto grid max-w-[480px] grid-cols-4">
        {TABS.map(([tab, name, icon]) => {
          const target: View = { ...HOME, tab, month: view.month }
          const active = view.tab === tab
          return (
            <li key={tab} className="min-w-0">
              <a
                href={`#/${tab}`}
                onClick={(e) => {
                  e.preventDefault()
                  navigate(target, 'push')
                }}
                aria-current={active ? 'page' : undefined}
                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 py-1.5 ${active ? 'text-accent' : 'text-muted'}`}
              >
                <span className="relative">
                  <Icon name={icon} />
                  {tab === 'todo' && <TodoCount />}
                </span>
                <span className={`max-w-full truncate text-xs ${active ? 'font-semibold' : ''}`}>{name}</span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function TodoCount() {
  const { api: client } = useApp()
  const [load] = useLoad(() => loadTodo(client), ['todo'])
  if (load.status !== 'ready') return null
  const n = load.data.senders.length + load.data.merchants.length
  if (!n) return null
  return (
    <span
      className="absolute -top-1.5 left-3.5 min-w-4.5 rounded-full border border-line bg-surface px-1 text-center text-[0.6875rem] leading-4 font-medium text-ink tabular-nums"
      aria-label={`${n} to do`}
    >
      {n}
    </span>
  )
}

/** "Demo data" on every screen, in the flow so it never covers content, and the demo state switch. */
function DemoBanner() {
  const { changed } = useApp()
  const [current, setCurrent] = useState<DemoState>(demoApi.state)
  return (
    <div className="border-b border-line bg-banner">
      <div className="mx-auto flex max-w-[480px] flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-1 text-xs">
        <span className="font-medium">Demo data. Not your real numbers.</span>
        <label className="flex items-center gap-1 text-muted">
          State
          <select
            value={current}
            onChange={(e) => {
              const next = e.target.value as DemoState
              demoApi.setState(next)
              setCurrent(next)
              newSession()
              changed()
            }}
            className="min-h-9 rounded border border-line bg-surface px-1 text-xs text-ink"
          >
            {DEMO_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
    </div>
  )
}
