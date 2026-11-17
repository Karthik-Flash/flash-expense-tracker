// The adapter in use. A production build always uses the HTTP adapter; the demo adapter
// exists only in local dev with VITE_DEMO=1 (and is left out of the build).

import { accessToken, noAccess, signOut } from '../auth.ts'
import type { Api } from './client.ts'
import { FakeApi } from './fake.ts'
import { errorText, HttpApi } from './http.ts'

export const DEMO = import.meta.env.DEV && import.meta.env.VITE_DEMO === '1'

export const demoApi: FakeApi | null = DEMO ? new FakeApi() : null

export const api: Api =
  demoApi ??
  new HttpApi(import.meta.env.VITE_API_URL ?? '', accessToken, (status) =>
    status === 401 ? void signOut(errorText(401, null)) : noAccess(),
  )
