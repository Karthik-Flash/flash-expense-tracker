import { useCallback, useEffect, useMemo, useState } from 'react'

import { welcomeDue } from './account.ts'
import { api, API_URL, DEMO, demoApi } from './api/index.ts'
import { signUp } from './api/http.ts'
import { DEMO_STATES, type DemoState } from './api/fake.ts'
import { markPainted, type BootPath } from './boot.ts'
import { beforeSignOut, expire, refreshToken, signIn, signOut, useAuth } from './auth.ts'
import { checksView, startOutbox, syncState, todoView, unsynced, useOutbox } from './data/outbox.ts'
import { clearData, refresh, startData, useData, useSnapshot } from './data/store.ts'
import { AppContext, navigate, useNav, useScrollMemory, useView, type AppState } from './state.tsx'
import { connectPhone, isNativeApp, signOutPhone, startSms } from './native/sms.ts'
import { DeleteSheet, MembersSheet, PrivacySheet, SettingsSheet, WelcomeSheet } from './screens/Account.tsx'
import { BankSmsSheet } from './screens/BankSms.tsx'
import { CategoryDetail, Home } from './screens/Home.tsx'
import { LabelDetail, Labels } from './screens/Labels.tsx'
import { Login } from './screens/Login.tsx'
import { ProfileSheet } from './screens/Profile.tsx'
import { SpeedSheet } from './screens/Speed.tsx'
import { UnsavedSheet } from './screens/Sync.tsx'
import { PersonSheet } from './screens/People.tsx'
import { Logos } from './screens/Logos.tsx'
import { TodoScreen } from './screens/Todo.tsx'
import { Insights } from './screens/Insights.tsx'
import { Transactions } from './screens/Transactions.tsx'
import { openFromNotification } from './opener.ts'
import { Button, Icon, PullToRefresh, Sheet } from './ui.tsx'
import { UpdateBar } from './update.ts'
import { HOME, type Tab, type View } from './view.ts'

const SIGNED_IN = 'flash-demo-signed-in'
// Sign-out revokes this phone's device token while the login still works (5A, D-122).
beforeSignOut(() => signOutPhone(api))
const TABS: [Tab, string, string][] = [
  ['home', 'Home', 'house'],
  ['transactions', 'Transactions', 'receipt-text'],
  ['insights', 'Insights', 'trending-up'],
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
  const { back } = useNav()
  const auth = useAuth()
  const [demoIn, setDemoIn] = useState(demoSignedIn)
  const [asking, setAsking] = useState(0)
  const leaveNow = useCallback(() => {
    setAsking(0)
    if (!DEMO) return void signOut()
    setDemoSignedIn(false)
    void clearData()
    setDemoIn(false)
  }, [])
  // Changes not yet on the server would be lost: ask first (D-093).
  const leave = useCallback(() => {
    const n = unsynced(syncState().ops)
    if (n) setAsking(n)
    else leaveNow()
  }, [leaveNow])
  const state: AppState = useMemo(() => ({ api, signOut: leave }), [leave])
  const status = DEMO ? (demoIn ? 'in' : 'out') : auth.status
  const user = DEMO ? 'demo' : auth.status === 'in' ? auth.user : null
  // After the first paint: the phone copy of this login, then the server (D-089), then the
  // outbox (D-091). Nothing here holds up the first screen (D-095).
  useEffect(() => {
    if (status === 'in' && user) void startData(api, user)
        .then(() => startOutbox(api, refreshToken))
        // The Android app: an upload refreshes the snapshot; the same login reconnects the
        // phone by itself after a sign-out (D-143); a notification opens its payment (D-142).
        .then(() => startSms(refresh, user, () => connectPhone(api, API_URL, user), openFromNotification))
  }, [status, user])
  if (DEMO && view.tab === 'dev') return <Logos />
  // Not reached: startAuth decides from the device before the first render (D-095).
  if (status === 'starting') return <p className="px-4 py-10 text-center text-sm text-muted">Loading</p>
  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-dvh flex-col">
        {DEMO && <DemoBanner />}
        {status === 'in' && <Shell view={view} />}
        {status === 'no-access' && <NoAccess />}
        {(status === 'out' || status === 'no-access') && <Painted path="login" />}
        {status === 'out' && (
          <Login
            note={auth.status === 'out' ? auth.note : ''}
            submit={async (email, password) => {
              if (!DEMO) return signIn(email, password)
              setDemoSignedIn(true)
              setDemoIn(true)
              return ''
            }}
            join={async (email, password, code) => {
              if (DEMO) {
                setDemoSignedIn(true)
                setDemoIn(true)
                return ''
              }
              // 5C (D-128): the account first, then the usual sign-in.
              return (await signUp(API_URL, email, password, code)) || signIn(email, password)
            }}
          />
        )}
        {/* The Android app updates by a new APK: no service worker there (D-125). */}
        {!isNativeApp() && <UpdateBar aboveNav={status === 'in'} />}
        {status !== 'in' && view.sheet === 'privacy' && <PrivacySheet onClose={back} />}
        {asking > 0 && <SignOutSheet count={asking} stay={() => setAsking(0)} leave={leaveNow} />}
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

/** Sign-out with changes still in the outbox: staying is the default. */
function SignOutSheet({ count, stay, leave }: { count: number; stay: () => void; leave: () => void }) {
  return (
    <Sheet title="Sign out?" onClose={stay}>
      <div className="px-4 py-4">
        <p className="text-sm">
          {count} {count === 1 ? "change hasn't" : "changes haven't"} synced yet. If you sign out now they will be lost.
        </p>
        <div className="mt-4 grid gap-2">
          <Button kind="primary" onClick={stay}>Stay signed in</Button>
          <Button onClick={leave}>Sign out anyway</Button>
        </div>
      </div>
    </Sheet>
  )
}

/** Records how this launch reached its first screen (boot.ts), once it is on screen. */
function Painted({ path }: { path: BootPath }) {
  useEffect(() => markPainted(path), [path])
  return null
}

function Shell({ view }: { view: View }) {
  useScrollMemory(view)
  const { back } = useNav()
  const [load] = useSnapshot()
  const { local } = useData()
  const auth = useAuth()
  const user = auth.status === 'in' ? auth.user : null
  // The first run (5C, D-132): an account with no data, once per login on this device.
  const due = !DEMO && load.status === 'ready' && welcomeDue(load.data, user)
  useEffect(() => {
    if (due && !view.sheet) navigate({ ...view, sheet: 'welcome' }, 'open')
  }, [due, view])
  const path: BootPath | null = load.status === 'ready' ? (local ? 'local copy' : 'online') : load.status === 'error' ? 'error screen' : null
  return (
    <div className="mx-auto w-full max-w-[480px] flex-1 pb-[calc(5rem+env(safe-area-inset-bottom))]">
      {/* 5B-2: the session ended and could not be renewed. Never stale data without saying so. */}
      {auth.status === 'in' && auth.signIn && (
        <div className="mx-4 mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm" role="alert">
          <span className="min-w-0 flex-1">Your session ended, so new payments are not loading. Your changes wait on this phone.</span>
          <Button kind="primary" onClick={() => void expire('Sign in again to see new payments.')}>Sign in again</Button>
        </div>
      )}
      <main>
        <Screen view={view} />
      </main>
      <Nav view={view} />
      <PullToRefresh />
      {path && <Painted path={path} />}
      {view.sheet === 'speed' && <SpeedSheet onClose={back} />}
      {view.sheet === 'profile' && <ProfileSheet onClose={back} />}
      {view.sheet === 'unsaved' && <UnsavedSheet onClose={back} />}
      {view.sheet === 'sms' && <BankSmsSheet onClose={back} />}
      {view.sheet === 'settings' && <SettingsSheet onClose={back} />}
      {view.sheet === 'members' && <MembersSheet onClose={back} />}
      {view.sheet === 'delete' && <DeleteSheet onClose={back} />}
      {view.sheet === 'privacy' && <PrivacySheet onClose={back} />}
      {view.sheet === 'welcome' && <WelcomeSheet onClose={back} />}
      {view.person && !view.sheet && <PersonSheet key={`${view.person}:${view.act}`} personKey={view.person} act={view.act} onClose={back} />}
    </div>
  )
}

function Screen({ view }: { view: View }) {
  const [a, b, c] = view.path
  if (view.tab === 'home' && a === 'category' && b) return <CategoryDetail slug={b} name={c} />
  if (view.tab === 'transactions') return <Transactions />
  if (view.tab === 'todo') return <TodoScreen />
  if (view.tab === 'insights') return <Insights />
  if (view.tab === 'labels' && a) return <LabelDetail id={Number(a)} />
  if (view.tab === 'labels') return <Labels />
  return <Home />
}

function Nav({ view }: { view: View }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]" aria-label="Main">
      <ul className="mx-auto grid max-w-[480px] grid-cols-5">
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
                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 ${active ? 'text-accent' : 'text-muted'}`}
              >
                <span className="relative">
                  <Icon name={icon} />
                  {tab === 'todo' && <TodoCount />}
                </span>
                {/* Tab names stay on one line at large text sizes: at most 12 px, less on a narrow
                    screen (4H); five tabs since 5F, so "Transactions" fits a 360 px screen. */}
                <span className={`max-w-full truncate text-[min(0.75rem,2.8vw)] tracking-tight${active ? 'font-semibold' : ''}`}>{name}</span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function TodoCount() {
  const [load] = useSnapshot()
  const { ops } = useOutbox()
  if (load.status !== 'ready') return null
  const t = todoView(load.data.todo, ops) // answers waiting to sync are not counted
  const n = t.senders.length + t.merchants.length + t.transfers.length + t.suggestions.length + checksView(load.data.transactions, ops).length
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
  const [current, setCurrent] = useState<DemoState>(demoApi?.state ?? 'normal')
  return (
    <div data-demo className="border-b border-line bg-banner">
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
              // A new session: "waking" shows "Starting up" again.
              void clearData()
                .then(() => startData(api, 'demo'))
                .then(() => startOutbox(api))
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
