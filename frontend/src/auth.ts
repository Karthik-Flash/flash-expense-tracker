// Login with Supabase Auth: email and password only, no sign-up. The library keeps the
// session (localStorage) and refreshes the token; the API adapter asks it for the token.
// Nothing else in the app talks to Supabase.

import { createClient, isAuthRetryableFetchError, type SupabaseClient } from '@supabase/supabase-js'
import { useSyncExternalStore } from 'react'

import { clearData, pauseData } from './data/store.ts'

export type AuthState =
  | { status: 'starting' }
  | { status: 'out'; note: string }
  /** `user`: the login's id; the phone copy belongs to it (D-089). */
  | { status: 'in'; user: string }
  | { status: 'no-access' }

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? ''
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? ''
const NOT_SET_UP = 'Sign-in is not set up: VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY are missing.'

let client: SupabaseClient | null = null
let state: AuthState = { status: 'starting' }
const listeners = new Set<() => void>()

function set(next: AuthState): void {
  // Never show one account's data to the next: leaving 'in' stops the data in memory. What
  // is stored is deleted by sign-out, or by the next login when it is another one (D-089).
  if (next.status !== 'in') pauseData()
  state = next
  for (const listener of listeners) listener()
}

function auth() {
  if (!SUPABASE_URL || !SUPABASE_KEY) throw new Error(NOT_SET_UP)
  client ??= createClient(SUPABASE_URL, SUPABASE_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  })
  return client.auth
}

/** Once, before the first render: the stored session, then every change the library reports. */
export function startAuth(): void {
  try {
    auth().onAuthStateChange((_event, session) => {
      if (!session) set({ status: 'out', note: state.status === 'out' ? state.note : '' })
      else if (state.status !== 'in' && state.status !== 'no-access') set({ status: 'in', user: session.user.id })
    })
  } catch {
    set({ status: 'out', note: NOT_SET_UP })
  }
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

/** The access token for the API, refreshed by the library when it has expired. Throws when
 *  the refresh cannot reach Supabase (offline): that is not a lost login. */
export async function accessToken(): Promise<string | null> {
  const { data, error } = await auth().getSession()
  if (!data.session && error && isAuthRetryableFetchError(error)) throw error
  return data.session?.access_token ?? null
}

/** One refresh of the access token (the outbox after a 401). True when it worked. */
export async function refreshToken(): Promise<boolean> {
  try {
    const { data, error } = await auth().refreshSession()
    return !error && Boolean(data.session)
  } catch {
    return false
  }
}

/** '' when signed in, else what to tell the owner. */
export async function signIn(email: string, password: string): Promise<string> {
  try {
    const { data, error } = await auth().signInWithPassword({ email: email.trim(), password })
    if (!error) {
      set({ status: 'in', user: data.user.id })
      return ''
    }
    if (error.code === 'invalid_credentials') return 'Email or password is wrong.'
    if (error.name === 'AuthRetryableFetchError' || !error.status || error.status >= 500) {
      return 'Could not reach the sign-in service. Check the connection and try again.'
    }
    return `Could not sign in: ${error.message}`
  } catch (e) {
    return e instanceof Error ? e.message : 'Could not sign in.'
  }
}

/** The session ended (a 401): the login screen, keeping the phone copy and the outbox, so
 *  no waiting action is lost; the same login picks them up again (D-093). */
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
