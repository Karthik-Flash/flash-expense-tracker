// The adapter in use. A production build always uses the HTTP adapter; the demo adapter
// exists only in local dev with VITE_DEMO=1 (and is left out of the build).

import { accessToken, needSignIn, noAccess, refreshToken } from '../auth.ts'
import type { Api } from './client.ts'
import { FakeApi } from './fake.ts'
import { HttpApi } from './http.ts'

export const DEMO = import.meta.env.DEV && import.meta.env.VITE_DEMO === '1'

/** The API's address (the Android build bakes in the live one, D-125). */
export const API_URL: string = import.meta.env.VITE_API_URL ?? ''

export const demoApi: FakeApi | null = DEMO ? new FakeApi() : null

export const api: Api =
  demoApi ??
  new HttpApi(
    API_URL,
    accessToken,
    // A 401 keeps the data and the outbox on screen and asks for a sign-in (D-095), after one
    // token refresh and one more try (5B-2).
    (status) => (status === 401 ? needSignIn() : noAccess()),
    refreshToken,
  )
