// The one interface the app uses: the HTTP adapter (http.ts) for /api/v1, or the demo
// adapter (fake.ts) in local dev with VITE_DEMO=1. Screens read the snapshot (data/store.ts);
// they write through the methods below.

import type { SenderAnswer, SnapshotAnswer, WriteResult } from './types.ts'

export interface Api {
  readonly demo: boolean
  /** The snapshot; 304 when `etag` is still current. */
  snapshot(etag: string | null, signal: AbortSignal): Promise<SnapshotAnswer>
  answerSender(id: string, answer: SenderAnswer): Promise<WriteResult<{ id: string; credits: number }>>
  /** Forget the answer: the sender is to confirm again. */
  resetSender(id: string): Promise<WriteResult<{ id: string; credits: number }>>
  setCategory(
    txnId: number,
    category: string,
    scope: 'merchant' | 'transaction',
  ): Promise<WriteResult<{ id: number; category: string; scope: string }>>
  /** 409 when the owner has that name in any case. */
  createLabel(name: string): Promise<{ id: number; name: string }>
  setLabel(txnId: number, labelId: number): Promise<WriteResult<{ id: number; label_id: number }>>
  clearLabel(txnId: number): Promise<WriteResult<{ id: number; label_id: null }>>
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
