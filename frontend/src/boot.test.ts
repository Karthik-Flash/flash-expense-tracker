// Boot never waits on the network (D-095): a mocked Supabase auth client, fake-indexeddb,
// and an API that never answers. FAKE data only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { AuthRetryableFetchError } from '@supabase/supabase-js'
import { openDB } from 'idb'

import type { Api } from './api/client.ts'
import type { Snapshot } from './api/types.ts'
import { accessToken, authState, expire, OFFLINE_SIGN_IN, signIn, startAuth } from './auth.ts'
import { bootPath, markPainted, noteBootError, readBoot, startWatchdog } from './boot.ts'
import { ErrorBoundary } from './crash.ts'
import { putOp, readOutbox, saveLocal, wipeLocal, type Meta } from './data/local.ts'
import type { Op } from './data/outbox.ts'
import { clearData, dataState, settleData, startData } from './data/store.ts'

// localStorage as the browser has it: the Supabase session lives there.
const store = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
  },
})
const setOnline = (onLine: boolean) => Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { onLine } })

const URL_ = 'http://127.0.0.1:9' // unreachable on purpose; the mock never calls it anyway
const KEY = 'sb-127-auth-token'
const session = (user: string, expiresIn: number) => ({
  access_token: `token-${user}`,
  refresh_token: 'refresh',
  expires_at: Math.floor(Date.now() / 1000) + expiresIn,
  user: { id: user },
})
const seed = (user: string, expiresIn = 3600) => localStorage.setItem(KEY, JSON.stringify(session(user, expiresIn)))

type Listener = (event: string, s: unknown) => void

/** A Supabase auth client: getSession and sign-in as given; it never touches the network. */
function mockAuth(o: { getSession?: () => Promise<unknown>; signInAs?: string } = {}) {
  let listener: Listener = () => {}
  const calls = { getSession: 0, signIn: 0 }
  const client = {
    onAuthStateChange(f: Listener) {
      listener = f
      return { data: { subscription: { unsubscribe() {} } } }
    },
    getSession() {
      calls.getSession++
      return o.getSession ? o.getSession() : new Promise(() => {}) // the refresh hangs
    },
    refreshSession: async () => ({ data: { session: null }, error: new Error('no') }),
    async signInWithPassword() {
      calls.signIn++
      const user = o.signInAs ?? 'user-a'
      seed(user)
      return { data: { user: { id: user }, session: session(user, 3600) }, error: null }
    },
    signOut: async () => ({ error: null }),
  }
  startAuth({ client: client as never, url: URL_ })
  return { emit: (event: string, s: unknown) => listener(event, s), calls }
}

const snap = { schema_version: 1, owner_id: 'owner-a', months: [], transactions: [], todo: { senders: [], answered: [], merchants: [], unnamed: 0 }, labels: [], categories: [] } as unknown as Snapshot
const meta = (user: string): Meta => ({ etag: '"e"', fetched_at: Date.now() - 9 * 3600_000, owner_id: 'owner-a', user_id: user, schema_version: 1 })

/** An API that never answers: whatever shows came from the device. */
function silentApi() {
  const seen = { calls: 0 }
  const api = {
    demo: false,
    snapshot: (_etag: string | null, signal: AbortSignal) => {
      seen.calls++
      // Never answers; gives up when aborted, like fetch.
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    },
    send: () => new Promise(() => {}),
  } as unknown as Api
  return { api, seen }
}

const op = { seq: 1, op_id: 'op-1', state: 'pending', kind: 'Category', item: 'Test Shop' } as unknown as Op

async function phoneCopy(user: string) {
  await clearData()
  store.clear()
  setOnline(true)
  await saveLocal(snap, meta(user))
  await putOp(op)
}

test('watchdog: nothing drawn at 3 s fires once and notes it (fake timers)', () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  try {
    let fired = 0
    startWatchdog(() => fired++)
    mock.timers.tick(2999)
    assert.equal(fired, 0)
    mock.timers.tick(1)
    assert.equal(fired, 1)
    assert.match(readBoot().errors[0].message, /Nothing drawn 3 s after start/)
  } finally {
    mock.timers.reset()
  }
})

test('error boundary: a thrown error shows the plain screen and is kept on the device', () => {
  const boundary = new ErrorBoundary({ children: 'app' })
  assert.equal(boundary.render(), 'app')
  boundary.state = { ...boundary.state, ...ErrorBoundary.getDerivedStateFromError(new Error('boom')) }
  boundary.setState = () => {}
  boundary.componentDidCatch(new Error('boom'), { componentStack: '\n    at Home' })
  const html = renderToStaticMarkup(boundary.render() as ReactElement)
  assert.match(html, /role="alert"/)
  assert.match(html, /Something went wrong/)
  assert.match(html, />Reload</)
  assert.match(html, />Copy details</)
  assert.equal(readBoot().errors[0].message, 'Error: boom')
  assert.equal(bootPath(), 'error screen')
  assert.equal(readBoot().last?.path, 'error screen')
})

test('watchdog: once something is drawn it stays quiet', () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  try {
    let fired = 0
    markPainted('login') // already painted above: no change
    startWatchdog(() => fired++)
    mock.timers.tick(5000)
    assert.equal(fired, 0)
  } finally {
    mock.timers.reset()
  }
  for (let i = 0; i < 7; i++) noteBootError(`e${i}`)
  assert.equal(readBoot().errors.length, 5)
  assert.equal(readBoot().errors[0].message, 'e6')
})

test('no stored session: the login screen at once, without the network', async () => {
  await phoneCopy('user-a')
  const { calls } = mockAuth()
  assert.deepEqual(authState(), { status: 'out', note: '' })
  assert.equal(calls.getSession, 0)
  setOnline(false)
  assert.equal(await signIn('a@example.test', 'pw'), OFFLINE_SIGN_IN)
  assert.equal(calls.signIn, 0)
})

test('valid session: signed in and the phone copy shows at once', async () => {
  await phoneCopy('user-a')
  seed('user-a')
  const { emit } = mockAuth({ getSession: async () => ({ data: { session: session('user-a', 3600) }, error: null }) })
  assert.deepEqual(authState(), { status: 'in', user: 'user-a', signIn: false })
  const { api, seen } = silentApi()
  await startData(api, 'user-a')
  assert.equal(dataState().snapshot?.owner_id, 'owner-a')
  assert.equal(dataState().local, true)
  assert.equal(seen.calls, 1) // asked in the background, never answered
  emit('INITIAL_SESSION', session('user-a', 3600))
  assert.deepEqual(authState(), { status: 'in', user: 'user-a', signIn: false })
})

test('expired session, refresh hangs: the phone copy at once; the token gives up after 10 s', async () => {
  await phoneCopy('user-a')
  seed('user-a', -3600)
  const { calls } = mockAuth() // getSession never resolves
  assert.equal(authState().status, 'in')
  await startData(silentApi().api, 'user-a')
  assert.ok(dataState().snapshot)
  mock.timers.enable({ apis: ['setTimeout'] })
  try {
    const token = accessToken()
    mock.timers.tick(10_000)
    await assert.rejects(token, /timeout/)
  } finally {
    mock.timers.reset()
  }
  assert.equal(calls.getSession, 1)
  setOnline(false)
  await assert.rejects(accessToken(), /offline/) // offline: no wait at all
  assert.equal(calls.getSession, 1)
})

test('expired session, refresh fails on the network: stays signed in on the phone copy', async () => {
  await phoneCopy('user-a')
  seed('user-a', -3600)
  const error = new AuthRetryableFetchError('Failed to fetch', 0)
  const { emit } = mockAuth({ getSession: async () => ({ data: { session: null }, error }) })
  await startData(silentApi().api, 'user-a')
  emit('INITIAL_SESSION', null) // the library keeps the stored session on a network error
  assert.deepEqual(authState(), { status: 'in', user: 'user-a', signIn: false })
  assert.ok(dataState().snapshot)
  await assert.rejects(accessToken())
})

test('refresh token rejected: data and outbox stay, "Sign in to sync"', async () => {
  await phoneCopy('user-a')
  seed('user-a', -3600)
  const { emit } = mockAuth()
  await startData(silentApi().api, 'user-a')
  localStorage.removeItem(KEY) // what the library does with a refresh token the server refused
  emit('SIGNED_OUT', null)
  assert.deepEqual(authState(), { status: 'in', user: 'user-a', signIn: true })
  assert.ok(dataState().snapshot)
  assert.equal((await readOutbox()).length, 1)
  emit('TOKEN_REFRESHED', session('user-a', 3600)) // a later refresh that worked clears it
  assert.deepEqual(authState(), { status: 'in', user: 'user-a', signIn: false })
})

test('"Sign in to sync": the same login keeps the copy and the outbox; another wipes them', async () => {
  for (const [who, keeps] of [['user-a', true], ['user-b', false]] as const) {
    await phoneCopy('user-a')
    seed('user-a', -3600)
    const { emit } = mockAuth({ signInAs: who })
    await startData(silentApi().api, 'user-a')
    localStorage.removeItem(KEY)
    emit('SIGNED_OUT', null)
    await expire('Sign in again to sync your changes.') // the link: to the login screen
    assert.equal(authState().status, 'out')
    assert.equal(await signIn('a@example.test', 'pw'), '')
    assert.deepEqual(authState(), { status: 'in', user: who, signIn: false })
    await startData(silentApi().api, who) // what App does on 'in'
    assert.equal(Boolean(dataState().snapshot), keeps, who)
    assert.equal((await readOutbox()).length, keeps ? 1 : 0, who)
  }
})

test('watchdog: a stuck phone copy read stops blocking; the server is asked, nothing is wiped', async () => {
  await clearData()
  await wipeLocal()
  // An old tab holds version 1 open and never lets go: the app's open (version 2) waits.
  const old = await openDB('flash', 1, { upgrade: (d) => void d.createObjectStore('meta') })
  const { api, seen } = silentApi()
  const started = startData(api, 'user-a')
  await new Promise((r) => setTimeout(r, 50))
  assert.equal(seen.calls, 0)
  settleData()
  await started
  assert.equal(seen.calls, 1)
  assert.equal(dataState().snapshot, null)
  old.close()
  await clearData()
})
