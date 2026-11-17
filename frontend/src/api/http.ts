// HTTP adapter for /api/v1 (docs/api.md). Every request carries the Supabase access token;
// the screens never talk to Supabase. 401 and 403 also tell the login layer (auth.ts).

import { ApiError, type Api } from './client.ts'
import type {
  Category,
  LabelSummary,
  LabelView,
  Page,
  Sender,
  SenderAnswer,
  SenderStatus,
  Summary,
  Txn,
  TxnQuery,
  WriteResult,
} from './types.ts'

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

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await this.token()
    if (!token) {
      this.lost(401)
      throw new ApiError(401, errorText(401, null))
    }
    let response: Response
    try {
      response = await fetch(this.base + path, {
        method,
        headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      throw new ApiError(0, errorText(0, null))
    }
    if (response.ok) return (await response.json()) as T
    if (response.status === 401 || response.status === 403) this.lost(response.status)
    const detail = await response.json().then((b: unknown) => (b as { detail?: unknown } | null)?.detail, () => null)
    throw new ApiError(response.status, errorText(response.status, detail))
  }

  summary(month: string) {
    return this.call<Summary>('GET', `/summary?month=${month}`)
  }

  transactions(query: TxnQuery) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) if (value !== undefined) params.set(key, String(value))
    return this.call<Page<Txn>>('GET', `/transactions?${params}`)
  }

  transaction(id: number) {
    return this.call<Txn>('GET', `/transactions/${id}`)
  }

  categories() {
    return this.call<Category[]>('GET', '/categories')
  }

  labels() {
    return this.call<LabelSummary[]>('GET', '/labels')
  }

  label(id: number) {
    return this.call<LabelView>('GET', `/labels/${id}`)
  }

  senders(status: SenderStatus | 'all' = 'to_confirm') {
    return this.call<Sender[]>('GET', `/senders?status=${status}`)
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
