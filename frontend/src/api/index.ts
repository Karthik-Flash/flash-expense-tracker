// The adapter in use. 3F-1: the demo adapter only. 3F-2 adds the HTTP adapter here.

import type { Api } from './client.ts'
import { FakeApi } from './fake.ts'

export const demoApi = new FakeApi()
export const api: Api = demoApi
