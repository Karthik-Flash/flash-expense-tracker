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
  /** Under a person's name (D-096): the identifier this row came from, as the bank wrote it
   *  (a name or a UPI ID); null when it is the name shown. Absent before 4E. */
  identifier?: string | null
  /** Who the money went to or came from (p_ party, s_ sender); null with no counterparty text. */
  person_id: string | null
  role: Role
  /** owner: the owner decided the role. A payback with basis engine is to confirm. */
  role_basis: Basis
  category: string
  category_name: string
  category_basis: Basis
  label: { id: number; name: string } | null
  /** Read by the generic parser, for a bank with no parser of its own yet (D-101). */
  generic?: boolean
  /** A generic row the owner has not checked yet: "Looks right" or "Not a payment". */
  check?: boolean
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
  /** The person (as Txn.person_id) and a transaction to name or join them by (4E). */
  person_id?: string | null
  txn_id?: number
}

/** A person's answer: Friend, Family (income), Ignore, or none yet (to confirm). */
export type PersonRole = 'friend' | 'income' | 'ignore' | 'none'

/** Someone the owner can name or join (D-096): one party, or one identifier on its own. */
export interface Person {
  key: string
  name: string | null
  /** The owner gave the name. */
  named: boolean
  /** A transaction of this person, to act on. */
  txn_id: number
  /** null: no money came from them. */
  role: PersonRole | null
  /** Newest first: the names or UPI IDs the bank used, each with one of its transactions. */
  identifiers: { name: string | null; txn_id: number; from_file: boolean }[]
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

// The snapshot (GET /api/v1/sync/snapshot, D-088): every figure the app shows, worked out by
// the server. The app filters, sorts and searches it; it never adds up money.

export const SCHEMA_VERSION = 1

export interface Merchant {
  name: string
  total_paise: number
  count: number
}

/** A possible transfer between two of the owner's accounts, same amount, no shared reference
 *  (D-115). Yes: both legs are a transfer (in no total); No: the pair is dropped. */
export interface Transfer {
  debit: number
  credit: number
  amount_paise: number
  from_bank: string
  to_bank: string
  debit_time_utc: string
  credit_time_utc: string
}

/** One row of the People ledger. Net = Sent - Got back; To confirm never lowers it. */
export interface PersonRow {
  key: string
  name: string
  sent_paise: number
  got_back_paise: number
  to_confirm_paise: number
  net_paise: number
}

/** A ring slice; slug null is "Other", the categories after the biggest ones. */
export interface ChartSlice {
  slug: string | null
  name: string
  amount_paise: number
}

export interface MonthData {
  month: string
  summary: Summary
  /** Against summary.previous: Spent, and each category of this month. */
  changes: { spent_paise: number; categories: Record<string, number> }
  chart: { total_paise: number; slices: ChartSlice[] }
  /** Per category: "Paid to", biggest first. */
  merchants: Record<string, Merchant[]>
  people: PersonRow[]
}

export interface Snapshot {
  schema_version: number
  generated_at: string
  owner_id: string
  engine_versions: Record<string, string>
  /** Every IST month with transactions, oldest first. */
  months: MonthData[]
  /** Newest first. */
  transactions: Txn[]
  todo: {
    senders: Sender[]
    answered: Sender[]
    /** `last_time_utc`: the newest payment (absent in a phone copy from before 4B-2). */
    merchants: (Merchant & { txn_id: number; last_time_utc?: string })[]
    unnamed: number
    /** Moved between your accounts? (D-115). Absent in a phone copy from before 4A. */
    transfers?: Transfer[]
  }
  labels: LabelView[]
  categories: Category[]
  /** Everyone to name or join (4E); absent in a phone copy from before. */
  people?: Person[]
}

export type SnapshotAnswer = { status: 200; etag: string; snapshot: Snapshot; bytes: number } | { status: 304 }
