// Response shapes of the data API (docs/api.md). Money is integer paise; times are UTC ISO.

export type Role =
  | 'spend'
  | 'card_bill_counted'
  | 'refund'
  | 'payback'
  | 'income'
  | 'self_transfer'
  | 'card_bill_excluded'
  | 'fd_move'
  | 'duplicate'
  | 'ignored'
  | 'uncertain'

export type Basis = 'engine' | 'owner'

export interface CategoryAmount {
  slug: string
  name: string
  amount_paise: number
}

export interface Summary {
  month: string
  spent_paise: number
  paid_back_paise: number
  to_confirm: { amount_paise: number; senders: number }
  net_paise: number
  income_paise: number
  categories: CategoryAmount[]
  counts: { uncategorised_spend: number; senders_to_confirm: number; not_counted_yet: number }
  stale: boolean
  last_recompute_utc: string | null
  /** The month before: up to the same IST day for the current month (whole: false), else whole. */
  previous: { month: string; whole: boolean; spent_paise: number; categories: CategoryAmount[] }
}

export interface Txn {
  id: number
  time_utc: string
  amount_paise: number
  direction: 'debit' | 'credit'
  display_name: string | null
  /** Who the money went to or came from (p_ party, s_ sender); null with no counterparty text. */
  person_id: string | null
  role: Role
  /** owner: the owner decided the role. A payback with basis engine is to confirm. */
  role_basis: Basis
  category: string
  category_name: string
  category_basis: Basis
  label: { id: number; name: string } | null
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface Category {
  slug: string
  name: string
}

export interface LabelSummary {
  id: number
  name: string
  transactions: number
  spent_paise: number
  paid_back_paise: number
  to_confirm_paise: number
  net_paise: number
}

export interface LabelView extends LabelSummary {
  categories: CategoryAmount[]
}

export interface Sender {
  id: string
  display_name: string | null
  total_paise: number
  count: number
  role: 'payback' | 'uncertain' | 'income' | 'ignored'
  basis: Basis
  status: SenderStatus
  last_time_utc: string
  /** The label of a confirmed income sender. */
  income_label: string | null
}

export type SenderStatus = 'to_confirm' | 'confirmed' | 'ignored'

export interface WriteResult<R> {
  result: R
  recompute: { status: string; run: number | null }
}

export type SenderAnswer =
  | { answer: 'friend' }
  | { answer: 'income'; label: string }
  | { answer: 'ignore' }

export interface TxnQuery {
  month?: string
  category?: string
  label?: number
  cursor?: string
  limit?: number
}
