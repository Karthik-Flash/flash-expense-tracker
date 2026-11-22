// HTTP adapter for /api/v1 (docs/api.md). Every request carries the Supabase access token
// and Accept: application/json (a waking Render answers browser-like requests with an HTML
// page). 401 and 403 also tell the login layer (auth.ts).

import { ApiError, type Api, type SendAnswer, type SendRequest } from './client.ts'
import { HEADER } from './headers.ts'
import type { Snapshot, SnapshotAnswer } from './types.ts'

type Lost = (status: 401 | 403) => void

/** What a failed request says to the owner. The server's own words for 404, 409 and 422. */
export function errorText(status: number, detail: unknown): string {
  if (status === 0) return 'Could not reach the server. Check the connection and try again.'
  if (status === 401) return 'Your session ended. Sign in again.'
  if (status === 403) return 'This account has no access.'
  if (status === 503) return 'The server is not ready yet. Try again in a minute.'
  if (status >= 500) return 'The server had a problem. Try again.'
  if (typeof detail === 'string' && detail) {
    const text = detail[0].toUpperCase() + detail.slice(1)
    return text.endsWith('.') ? text : `${text}.`
  }
  return 'The server did not accept this.'
}

/** POST /signup (5C, D-128): no login, an invite code. '' when the account exists, else
 *  what to tell the person (the server's words are generic on purpose). */
export async function signUp(baseUrl: string, email: string, password: string, code: string): Promise<string> {
  let response: Response
  try {
    response = await fetch(baseUrl.replace(/\/+$/, '') + '/api/v1/signup', {
      method: 'POST',
      cache: 'no-store',
      signal: AbortSignal.timeout(90_000),
      headers: { [HEADER.accept]: 'application/json', [HEADER.contentType]: 'application/json' },
      body: JSON.stringify({ email, password, code }),
    })
  } catch {
    return errorText(0, null)
  }
  if (response.ok) return ''
  const detail = ((await response.json().catch(() => null)) as { detail?: unknown } | null)?.detail
  if (response.status === 422 && typeof detail !== 'string') return 'Check the email, and use a password of 8 to 72 characters.'
  return typeof detail === 'string' ? detail : errorText(response.status, null)
}

export class HttpApi implements Api {
  readonly demo = false
  private readonly base: string
  private readonly token: () => Promise<string | null>
  private readonly lost: Lost

  constructor(base: string, token: () => Promise<string | null>, lost: Lost) {
    this.base = base.replace(/\/+$/, '') + '/api/v1'
    this.token = token
    this.lost = lost
  }

  /** The snapshot's response, or an ApiError. */
  private async request(method: string, path: string, init: { headers?: Record<string, string>; signal?: AbortSignal; body?: string } = {}) {
    const unreachable = new ApiError(0, errorText(0, null))
    let token: string | null
    try {
      token = await this.token()
    } catch {
      throw unreachable // offline with an expired token: the library could not refresh it
    }
    if (!token) {
      this.lost(401)
      throw new ApiError(401, errorText(401, null))
    }
    let response: Response
    try {
      response = await fetch(this.base + path, {
        method,
        cache: 'no-store',
        signal: init.signal,
        headers: {
          [HEADER.authorization]: `Bearer ${token}`,
          [HEADER.accept]: 'application/json',
          ...init.headers,
        },
        body: init.body,
      })
    } catch (e) {
      if (init.signal?.aborted) throw e
      throw unreachable
    }
    if (response.ok || response.status === 304) return response
    if (response.status === 401 || response.status === 403) this.lost(response.status)
    const detail = await response.json().then((b: unknown) => (b as { detail?: unknown } | null)?.detail, () => null)
    throw new ApiError(response.status, errorText(response.status, detail))
  }

  async snapshot(etag: string | null, signal: AbortSignal): Promise<SnapshotAnswer> {
    const response = await this.request('GET', '/sync/snapshot', { signal, headers: etag ? { [HEADER.ifNoneMatch]: etag } : {} })
    if (response.status === 304) return { status: 304 }
    const text = await response.text()
    let snapshot: Snapshot
    try {
      snapshot = JSON.parse(text) as Snapshot
    } catch {
      throw new ApiError(502, errorText(502, null)) // not JSON: a waking server's page
    }
    return { status: 200, etag: response.headers.get('ETag') ?? '', snapshot, bytes: new TextEncoder().encode(text).length }
  }

  async registerDevice(deviceId: string, name: string): Promise<{ token: string }> {
    const body = JSON.stringify({ device_id: deviceId, name })
    const response = await this.request('POST', '/devices', { headers: { [HEADER.contentType]: 'application/json' }, body, signal: AbortSignal.timeout(90_000) })
    const answer = (await response.json().catch(() => null)) as { token?: unknown } | null
    if (typeof answer?.token !== 'string') throw new ApiError(502, errorText(502, null))
    return { token: answer.token }
  }

  async createInvite(): Promise<{ code: string }> {
    const response = await this.request('POST', '/invites', { signal: AbortSignal.timeout(90_000) })
    const answer = (await response.json().catch(() => null)) as { code?: unknown } | null
    if (typeof answer?.code !== 'string') throw new ApiError(502, errorText(502, null))
    return { code: answer.code }
  }

  /** Not through request(): a 409 here is an answer to show, not a lost session. */
  async deleteAccount(): Promise<SendAnswer> {
    const token = await this.token().catch(() => null)
    if (!token) return { status: 401, detail: null, message: errorText(401, null) }
    let response: Response
    try {
      response = await fetch(this.base + '/account/delete', {
        method: 'POST',
        cache: 'no-store',
        signal: AbortSignal.timeout(90_000),
        headers: { [HEADER.authorization]: `Bearer ${token}`, [HEADER.accept]: 'application/json', [HEADER.contentType]: 'application/json' },
        body: JSON.stringify({ confirm: 'DELETE' }),
      })
    } catch {
      throw new ApiError(0, errorText(0, null))
    }
    const detail = ((await response.json().catch(() => null)) as { detail?: unknown } | null)?.detail ?? null
    return { status: response.status, detail, message: response.ok ? '' : errorText(response.status, detail) }
  }

  /** One owner action from the outbox, with its Idempotency-Key. A 401 or 403 is answered,
   *  not acted on: the outbox keeps the action and asks for a sign-in (D-093). */
  async send(request: SendRequest, signal: AbortSignal): Promise<SendAnswer> {
    let token: string | null
    try {
      token = await this.token()
    } catch {
      throw new ApiError(0, errorText(0, null)) // offline: the token cannot be refreshed
    }
    if (!token) return { status: 401, detail: null, message: errorText(401, null) }
    let response: Response
    try {
      response = await fetch(this.base + request.path, {
        method: request.method,
        cache: 'no-store',
        signal,
        headers: {
          [HEADER.authorization]: `Bearer ${token}`,
          [HEADER.accept]: 'application/json',
          [HEADER.idempotencyKey]: request.op_id,
          ...(request.defer ? { [HEADER.deferRecompute]: '1' } : {}),
          ...(request.body === null || request.body === undefined ? {} : { [HEADER.contentType]: 'application/json' }),
        },
        body: request.body === null || request.body === undefined ? undefined : JSON.stringify(request.body),
      })
    } catch (e) {
      if (signal.aborted) throw e
      throw new ApiError(0, errorText(0, null))
    }
    const json: unknown = await response.json().catch(() => null)
    const detail = (json as { detail?: unknown } | null)?.detail ?? null
    return { status: response.status, detail, message: response.ok ? '' : errorText(response.status, detail) }
  }
}
