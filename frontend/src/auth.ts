// Login with Supabase Auth: email and password only, no sign-up. The library keeps the
// session (localStorage) and refreshes the token; the API adapter asks it for the token.
// Nothing else in the app talks to Supabase.
//
// Boot never waits on the network (D-095): who is signed in comes from the session stored
// on the device, even when its access token has expired. The library refreshes the token
// in the background; offline, that can take half a minute or more.

import { createClient, isAuthRetryableFetchError, type SupabaseClient } from '@supabase/supabase-js'
import { useSyncExternalStore } from 'react'

import { clearData, pauseData } from './data/store.ts'

export type AuthState =
  | { status: 'starting' }
  | { status: 'out'; note: string }
  /** `user`: the login's id; the phone copy belongs to it (D-089). `signIn`: the session was
   *  rejected; the data and the outbox stay, the app asks for a sign-in to sync (D-095). */
  | { status: 'in'; user: string; signIn: boolean }
  | { status: 'no-access' }

type Auth = SupabaseClient['auth']

const ENV = import.meta.env ?? {}
const NOT_SET_UP = 'Sign-in is not set up: VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY are missing.'
export const OFFLINE_SIGN_IN = "You're offline. Connect to sign in."
const UNREACHABLE = 'Could not reach the sign-in service. Check the connection and try again.'
const TOKEN_WAIT_MS = 10_000
const SIGN_IN_WAIT_MS = 20_000

let url: string = ENV.VITE_SUPABASE_URL ?? ''
let client: Auth | null = null
let state: AuthState = { status: 'starting' }
const listeners = new Set<() => void>()

function set(next: AuthState): void {
  // Never show one account's data to the next: leaving 'in' stops the data in memory. What
  // is stored is deleted by sign-out, or by the next login when it is another one (D-089).
  if (next.status !== 'in') pauseData()
  state = next
  for (const listener of listeners) listener()
}

function auth(): Auth {
  if (client) return client
  const key = ENV.VITE_SUPABASE_PUBLISHABLE_KEY ?? ''
  if (!url || !key) throw new Error(NOT_SET_UP)
  client = createClient(url, key, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  }).auth
  return client
}

const offline = () => typeof navigator !== 'undefined' && navigator.onLine === false

function within<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const late = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error('timeout')), ms)
  })
  return Promise.race([work, late]).finally(() => clearTimeout(timer))
}

/** The user id of the session stored on this device (supabase-js's default key), or null.
 *  Read straight from storage: no network, no wait. */
export function storedUser(): string | null {
  try {
    const raw = localStorage.getItem(`sb-${new URL(url).hostname.split('.')[0]}-auth-token`)
    const id = raw ? (JSON.parse(raw) as { user?: { id?: unknown } }).user?.id : null
    return typeof id === 'string' && id ? id : null
  } catch {
    return null
  }
}

/** Once, before the first render. `test` replaces the Supabase client (node tests). */
export function startAuth(test?: { client: Auth; url: string }): void {
  if (test) ({ client, url } = test)
  let a: Auth
  try {
    a = auth()
  } catch {
    set({ status: 'out', note: NOT_SET_UP })
    return
  }
  const user = storedUser()
  set(user ? { status: 'in', user, signIn: false } : { status: 'out', note: '' })
  a.onAuthStateChange((_event, session) => {
    if (session) {
      if (state.status === 'in' && state.user === session.user.id) {
        if (state.signIn) set({ ...state, signIn: false })
      } else if (state.status !== 'no-access') {
        set({ status: 'in', user: session.user.id, signIn: false })
      }
      return
    }
    if (state.status === 'in') {
      // A refresh that failed on the network keeps the stored session: carry on offline.
      // One the server rejected removes it: keep the data and the outbox, ask to sign in.
      if (!storedUser()) needSignIn()
    } else if (state.status === 'no-access') {
      set({ status: 'out', note: '' })
    }
  })
}

export function authState(): AuthState {
  return state
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange)
      return () => listeners.delete(onChange)
    },
    () => state,
  )
}

/** The session is gone or the API refused its token (401): stay on the data and the
 *  outbox, show "Sign in to sync" (D-095). */
export function needSignIn(): void {
  if (state.status === 'in' && !state.signIn) set({ ...state, signIn: true })
}

/** The access token for the API, refreshed by the library when it has expired. Throws when
 *  offline or when the refresh cannot reach Supabase in 10 s: that is not a lost login. */
export async function accessToken(): Promise<string | null> {
  if (offline()) throw new Error('offline')
  const { data, error } = await within(auth().getSession(), TOKEN_WAIT_MS)
  if (!data.session && error && isAuthRetryableFetchError(error)) throw error
  return data.session?.access_token ?? null
}

/** One refresh of the access token (the outbox after a 401). True when it worked. */
export async function refreshToken(): Promise<boolean> {
  try {
    const { data, error } = await within(auth().refreshSession(), TOKEN_WAIT_MS)
    return !error && Boolean(data.session)
  } catch {
    return false
  }
}

/** '' when signed in, else what to tell the owner. */
export async function signIn(email: string, password: string): Promise<string> {
  if (offline()) return OFFLINE_SIGN_IN
  try {
    const { data, error } = await within(auth().signInWithPassword({ email: email.trim(), password }), SIGN_IN_WAIT_MS)
    if (!error) {
      set({ status: 'in', user: data.user.id, signIn: false })
      return ''
    }
    if (error.code === 'invalid_credentials') return 'Email or password is wrong.'
    if (error.name === 'AuthRetryableFetchError' || !error.status || error.status >= 500) return UNREACHABLE
    return `Could not sign in: ${error.message}`
  } catch (e) {
    return e instanceof Error && e.message === 'timeout' ? UNREACHABLE : e instanceof Error ? e.message : 'Could not sign in.'
  }
}

/** To the login screen, keeping the phone copy and the outbox, so no waiting action is
 *  lost; the same login picks them up again, another login wipes them (D-093, D-095). */
export async function expire(note = ''): Promise<void> {
  if (state.status === 'out') return
  set({ status: 'out', note })
  try {
    await auth().signOut({ scope: 'local' })
  } catch {
    // The local session is gone either way.
  }
}

/** Sign out on this device: the phone copy and the outbox are deleted first. `note` is shown
 *  on the login screen. The app asks first when actions have not synced (D-093). */
export async function signOut(note = ''): Promise<void> {
  if (state.status === 'out') return
  await clearData()
  set({ status: 'out', note })
  try {
    await auth().signOut({ scope: 'local' })
  } catch {
    // The local session is gone either way.
  }
}

/** A valid login that the API does not know (403). */
export function noAccess(): void {
  if (state.status !== 'no-access') set({ status: 'no-access' })
}

/** The watchdog (D-095): still starting after 3 s means draw from the device. */
export function settleAuth(): void {
  if (state.status !== 'starting') return
  const user = url ? storedUser() : null
  set(user ? { status: 'in', user, signIn: false } : { status: 'out', note: '' })
}
