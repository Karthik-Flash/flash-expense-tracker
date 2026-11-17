// The one interface every screen uses: the HTTP adapter (http.ts) for /api/v1, or the
// demo adapter (fake.ts) in local dev with VITE_DEMO=1.

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

export interface Api {
  readonly demo: boolean
  summary(month: string): Promise<Summary>
  transactions(query: TxnQuery): Promise<Page<Txn>>
  transaction(id: number): Promise<Txn>
  categories(): Promise<Category[]>
  labels(): Promise<LabelSummary[]>
  label(id: number): Promise<LabelView>
  senders(status?: SenderStatus | 'all'): Promise<Sender[]>
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

/** Every page of a transaction query. */
export async function allTransactions(api: Api, query: Omit<TxnQuery, 'cursor'>): Promise<Txn[]> {
  const items: Txn[] = []
  let cursor: string | undefined
  do {
    const page = await api.transactions({ ...query, cursor, limit: 200 })
    items.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return items
}

/** Signed effect on Spent: a refund lowers it. Used to total a group of rows. */
export function spentEffect(t: Txn): number {
  if (t.role === 'spend' || t.role === 'card_bill_counted') return t.amount_paise
  if (t.role === 'refund') return -t.amount_paise
  return 0
}
