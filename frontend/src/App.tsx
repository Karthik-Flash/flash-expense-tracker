import { useCallback, useMemo, useState } from 'react'

import { api, demoApi } from './api/index.ts'
import { DEMO_STATES, type DemoState } from './api/fake.ts'
import { currentMonth } from './lib/dates.ts'
import { AppContext, go, useApp, useLoad, useRoute, type AppState } from './state.tsx'
import { CategoryDetail, Home } from './screens/Home.tsx'
import { LabelDetail, Labels } from './screens/Labels.tsx'
import { Login } from './screens/Login.tsx'
import { TodoScreen } from './screens/Todo.tsx'
import { loadTodo } from './screens/todo-data.ts'
import { Transactions } from './screens/Transactions.tsx'

const SIGNED_IN = 'flash-demo-signed-in'
const TABS = [
  ['home', 'Home'],
  ['transactions', 'Transactions'],
  ['todo', 'To-do'],
  ['labels', 'Labels'],
] as const

function signedIn(): boolean {
  try {
    return sessionStorage.getItem(SIGNED_IN) === '1'
  } catch {
    return false
  }
}

export default function App() {
  const [ready, setReady] = useState(signedIn)
  const [month, setMonth] = useState(() => currentMonth())
  const [version, setVersion] = useState(0)
  const changed = useCallback(() => setVersion((v) => v + 1), [])
  const state: AppState = useMemo(
    () => ({ api, month, setMonth, version, changed, go }),
    [month, version, changed],
  )
  if (!ready) {
    return (
      <>
        {api.demo && <DemoBanner onState={changed} />}
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
      </>
    )
  }
  return (
    <AppContext.Provider value={state}>
      {api.demo && <DemoBanner onState={changed} />}
      <Shell />
    </AppContext.Provider>
  )
}

function Shell() {
  const route = useRoute()
  const [tab = 'home', ...rest] = route
  return (
    <div className="mx-auto min-h-dvh max-w-[480px] pb-24">
      <main>
        <Screen tab={tab} rest={rest} />
      </main>
      <Nav tab={tab} />
    </div>
  )
}

function Screen({ tab, rest }: { tab: string; rest: string[] }) {
  if (tab === 'home' && rest[0] === 'category' && rest[1]) return <CategoryDetail slug={rest[1]} name={rest[2]} />
  if (tab === 'transactions') return <Transactions />
  if (tab === 'todo') return <TodoScreen />
  if (tab === 'labels' && rest[0]) return <LabelDetail id={Number(rest[0])} />
  if (tab === 'labels') return <Labels />
  return <Home />
}

function Nav({ tab }: { tab: string }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]" aria-label="Main">
      <ul className="mx-auto grid max-w-[480px] grid-cols-4">
        {TABS.map(([key, name]) => (
          <li key={key}>
            <a
              href={`#/${key}`}
              aria-current={tab === key ? 'page' : undefined}
              className={`flex min-h-14 items-center justify-center gap-1 text-sm ${tab === key ? 'font-semibold text-accent' : 'text-muted'}`}
            >
              {name}
              {key === 'todo' && <TodoCount />}
            </a>
          </li>
        ))}
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
    <span className="min-w-5 rounded-full border border-line px-1.5 text-xs font-medium tabular-nums text-ink" aria-label={`${n} to do`}>
      {n}
    </span>
  )
}

/** "Demo data" on every screen, and the dev-only switch between demo states. */
function DemoBanner({ onState }: { onState: () => void }) {
  const [current, setCurrent] = useState<DemoState>(demoApi.state)
  return (
    <div className="sticky top-0 z-10 border-b border-line bg-banner">
      <div className="mx-auto flex min-h-10 max-w-[480px] items-center justify-between gap-2 px-4 text-xs">
        <span className="font-medium">Demo data. Not your real numbers.</span>
        <label className="flex items-center gap-1 text-muted">
          State
          <select
            value={current}
            onChange={(e) => {
              const next = e.target.value as DemoState
              demoApi.setState(next)
              setCurrent(next)
              onState()
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
