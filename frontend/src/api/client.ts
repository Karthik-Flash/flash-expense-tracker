// The one interface the app uses: the HTTP adapter (http.ts) for /api/v1, or the demo
// adapter (fake.ts) in local dev with VITE_DEMO=1. Screens read the snapshot (data/store.ts);
// every owner action goes through the outbox (data/outbox.ts), which calls send().

import type { AnalyticsAnswer, SnapshotAnswer } from './types.ts'

/** One owner action as the outbox sends it (D-091). */
export interface SendRequest {
  op_id: string
  method: 'PUT' | 'POST' | 'DELETE'
  path: string
  body: unknown
  /** More actions follow: the server may leave its recompute to the next read (D-094). */
  defer: boolean
}

/** The server's answer to a SendRequest: any status, never thrown. */
export interface SendAnswer {
  status: number
  /** The server's `detail`, as sent ("in_progress", "idempotency_key_reused", a message). */
  detail: unknown
  /** What to tell the owner when it failed. */
  message: string
}

export interface Api {
  readonly demo: boolean
  /** The snapshot; 304 when `etag` is still current. */
  snapshot(etag: string | null, signal: AbortSignal): Promise<SnapshotAnswer>
  /** Throws an ApiError only when the server cannot be reached (status 0) or on abort. */
  send(request: SendRequest, signal: AbortSignal): Promise<SendAnswer>
  /** POST /devices (5A, D-122): this phone, and its device token, shown only in this answer.
   *  Online only, never through the outbox: a stored replay would have to keep the token. */
  registerDevice(deviceId: string, name: string): Promise<{ token: string }>
  /** POST /invites (5C, the admin): a new code, shown only in this answer. Online only. */
  createInvite(): Promise<{ code: string }>
  /** POST /account/delete (5C, D-131): needs a sign-in from the last 10 minutes. The
   *  server's answer as it is: 200, or 409 fresh_login_required / admin_cannot_delete. */
  deleteAccount(): Promise<SendAnswer>
  /** GET /export (5F, D-146): the transactions of IST days `start` to `end` as a file the
   *  server built. Online only; nothing is written. */
  exportFile(start: string, end: string, format: 'csv' | 'xlsx'): Promise<Blob>
  /** GET /analytics (D-148): IST months `start` to `end`; 304 when `etag` is still current.
   *  Online only. */
  analytics(start: string, end: string, etag: string | null): Promise<AnalyticsAnswer>
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
