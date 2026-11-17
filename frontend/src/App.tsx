import { useCallback, useMemo, useState } from 'react'

import { api, DEMO, demoApi } from './api/index.ts'
import { DEMO_STATES, type DemoState } from './api/fake.ts'
import { signIn, signOut, useAuth } from './auth.ts'
import { AppContext, navigate, newSession, useApp, useLoad, useScrollMemory, useView, type AppState } from './state.tsx'
import { CategoryDetail, Home } from './screens/Home.tsx'
import { LabelDetail, Labels } from './screens/Labels.tsx'
import { Login } from './screens/Login.tsx'
import { Logos } from './screens/Logos.tsx'
import { TodoScreen } from './screens/Todo.tsx'
import { loadTodo } from './screens/todo-data.ts'
import { Transactions } from './screens/Transactions.tsx'
import { Button, Icon } from './ui.tsx'
import { HOME, type Tab, type View } from './view.ts'

const SIGNED_IN = 'flash-demo-signed-in'
const TABS: [Tab, string, string][] = [
  ['home', 'Home', 'house'],
  ['transactions', 'Transactions', 'receipt-text'],
  ['todo', 'To-do', 'list-checks'],
  ['labels', 'Labels', 'tag'],
]

function demoSignedIn(): boolean {
  try {
    return sessionStorage.getItem(SIGNED_IN) === '1'
  } catch {
    return false
  }
}

function setDemoSignedIn(on: boolean): void {
  try {
    if (on) sessionStorage.setItem(SIGNED_IN, '1')
    else sessionStorage.removeItem(SIGNED_IN)
  } catch {
    // Private mode: the demo login lasts for this page only.
  }
}

export default function App() {
  const view = useView()
  const auth = useAuth()
  const [demoIn, setDemoIn] = useState(demoSignedIn)
  const [version, setVersion] = useState(0)
  const changed = useCallback(() => setVersion((v) => v + 1), [])
  const leave = useCallback(() => {
    if (!DEMO) return void signOut()
    setDemoSignedIn(false)
    newSession()
    setDemoIn(false)
  }, [])
  const state: AppState = useMemo(() => ({ api, version, changed, signOut: leave }), [version, changed, leave])
  if (DEMO && view.tab === 'dev') return <Logos />
  const status = DEMO ? (demoIn ? 'in' : 'out') : auth.status
  if (status === 'starting') return null
  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-dvh flex-col">
        {DEMO && <DemoBanner />}
        {status === 'in' && <Shell view={view} />}
        {status === 'no-access' && <NoAccess />}
        {status === 'out' && (
          <Login
            note={auth.status === 'out' ? auth.note : ''}
            submit={async (email, password) => {
              if (!DEMO) return signIn(email, password)
              setDemoSignedIn(true)
              setDemoIn(true)
              return ''
            }}
          />
        )}
      </div>
    </AppContext.Provider>
  )
}

/** A valid login that the API does not know (403). */
function NoAccess() {
  return (
    <main className="mx-auto flex w-full max-w-[480px] flex-1 flex-col justify-center px-6 py-8" role="alert">
      <h1 className="text-xl font-semibold">This account has no access</h1>
      <p className="mt-2 text-sm text-muted">You signed in, but this account is not set up for Flash. Sign out and use the owner's account.</p>
      <div className="mt-6">
        <Button kind="primary" onClick={() => void signOut()}>Sign out</Button>
      </div>
    </main>
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

/** Local dev with VITE_DEMO=1 only: "Demo data" on every screen, and the demo state switch. */
function DemoBanner() {
  const { changed } = useApp()
  const [current, setCurrent] = useState<DemoState>(demoApi?.state ?? 'normal')
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
              demoApi?.setState(next)
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
