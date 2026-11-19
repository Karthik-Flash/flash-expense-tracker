// HTTP adapter for /api/v1 (docs/api.md). Every request carries the Supabase access token
// and Accept: application/json (a waking Render answers browser-like requests with an HTML
// page). 401 and 403 also tell the login layer (auth.ts).

import { ApiError, type Api } from './client.ts'
import type { SenderAnswer, Snapshot, SnapshotAnswer, WriteResult } from './types.ts'

type Lost = (status: 401 | 403) => void

/** What an owner action says when it cannot reach the server. Nothing is queued (4B-1). */
export const OFFLINE = "You're offline. Try again when connected."

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

const offline = () => typeof navigator !== 'undefined' && navigator.onLine === false

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

  /** The response, or an ApiError. A failed write says OFFLINE. */
  private async request(method: string, path: string, init: { body?: unknown; headers?: Record<string, string>; signal?: AbortSignal } = {}) {
    const unreachable = new ApiError(0, method === 'GET' ? errorText(0, null) : OFFLINE)
    if (method !== 'GET' && offline()) throw unreachable
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
          Authorization: `Bearer ${token}`,
          Accept: 'application/json',
          ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...init.headers,
        },
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
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

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    return (await (await this.request(method, path, { body })).json()) as T
  }

  async snapshot(etag: string | null, signal: AbortSignal): Promise<SnapshotAnswer> {
    const response = await this.request('GET', '/sync/snapshot', { signal, headers: etag ? { 'If-None-Match': etag } : {} })
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

  answerSender(id: string, answer: SenderAnswer) {
    return this.call<WriteResult<{ id: string; credits: number }>>('PUT', `/senders/${encodeURIComponent(id)}`, answer)
  }

  resetSender(id: string) {
    return this.call<WriteResult<{ id: string; credits: number }>>('DELETE', `/senders/${encodeURIComponent(id)}`)
  }

  setCategory(txnId: number, category: string, scope: 'merchant' | 'transaction') {
    return this.call<WriteResult<{ id: number; category: string; scope: string }>>('PUT', `/transactions/${txnId}/category`, {
      category,
      scope,
    })
  }

  createLabel(name: string) {
    return this.call<{ id: number; name: string }>('POST', '/labels', { name })
  }

  setLabel(txnId: number, labelId: number) {
    return this.call<WriteResult<{ id: number; label_id: number }>>('PUT', `/transactions/${txnId}/label`, { label_id: labelId })
  }

  clearLabel(txnId: number) {
    return this.call<WriteResult<{ id: number; label_id: null }>>('DELETE', `/transactions/${txnId}/label`)
  }
}
