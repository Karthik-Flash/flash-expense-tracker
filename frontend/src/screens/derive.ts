// Pure helpers the screens use on the snapshot (docs/ui-spec.md). They filter, sort and
// search; every money figure comes from the server (D-088).

import type { Category, MonthData, Person, Sender, Snapshot, Summary, Txn } from '../api/types.ts'
import { dayLabel, monthOf } from '../lib/dates.ts'
import { rupees } from '../lib/money.ts'
import { nameOf } from './common.ts'

export const LABEL_MAX = 30

const tidy = (text: string) => text.trim().replace(/\s+/g, ' ')

/** A name as it will be saved, and why it cannot be ('' when it can). The API has the same rules. */
export function labelName(raw: string, existing: string[]): { name: string; error: string } {
  const name = tidy(raw)
  let error = ''
  if (!name) error = 'Type a name.'
  else if ([...name].length > LABEL_MAX) error = `Use at most ${LABEL_MAX} characters.`
  else if (existing.some((e) => tidy(e).toLowerCase() === name.toLowerCase())) error = 'A label with this name already exists.'
  return { name, error }
}

/** Rows that count in Spent: spending, a counted card bill, a refund. */
export const countsInSpent = (t: Txn): boolean => t.role === 'spend' || t.role === 'card_bill_counted' || t.role === 'refund'

/** Money sent to a person (People spending) or got back from one (paybacks). */
export function isPersonTxn(t: Txn): boolean {
  return (t.category === 'people' && countsInSpent(t) && t.amount_paise !== 0) || (t.direction === 'credit' && t.role === 'payback')
}

/** The person of a row: the API's person id (one person under a name and a UPI ID once joined). */
export const personKey = (t: Txn): string => t.person_id ?? `name:${nameOf(t)}`

/** One IST month of the snapshot; undefined when nothing was recorded in it. */
export function monthData(s: Snapshot, month: string): MonthData | undefined {
  return s.months.find((m) => m.month === month)
}

/** The month's transactions, newest first. */
export function monthTxns(s: Snapshot, month: string): Txn[] {
  return s.transactions.filter((t) => monthOf(t.time_utc) === month)
}

/** "1 payment · Tue 12 Nov", "3 payments · last Tue 12 Nov" (as the sender cards say it). */
export function paymentsText(count: number, lastIso?: string): string {
  const n = `${count} ${count === 1 ? 'payment' : 'payments'}`
  if (!lastIso) return n
  return `${n} · ${count === 1 ? '' : 'last '}${dayLabel(lastIso)}`
}

/** The owner's most used categories, for one-tap chips on To-do merchant cards: by the number
 *  of rows the owner set (then of all spending rows), never by money. */
export function topCategories(txns: Txn[], cats: Category[], n = 4): Category[] {
  const score = new Map<string, number>()
  for (const t of txns) {
    if (!countsInSpent(t) || t.category === 'uncategorised') continue
    score.set(t.category, (score.get(t.category) ?? 0) + (t.category_basis === 'owner' ? 1000 : 1))
  }
  return cats
    .filter((c) => score.has(c.slug))
    .sort((a, b) => score.get(b.slug)! - score.get(a.slug)! || a.name.localeCompare(b.name))
    .slice(0, n)
}

/** The identifiers under a named person, as the bank wrote them: "Rohit V · *r203@okhdfcbank". */
export function identifiersText(p: Person | undefined): string {
  return p?.named ? p.identifiers.map((i) => i.name ?? '').filter(Boolean).join(' · ') : ''
}

/** Name search: every word must appear in the name, any case. */
export function matches(t: Txn, q: string): boolean {
  const name = nameOf(t).toLowerCase()
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((word) => name.includes(word))
}

// --- 5B-1 -----------------------------------------------------------------------------

/** "Invested ₹3,000 · Invested (to confirm) ₹500, in Spent": the server's figures (D-136). */
export function investedLine(s: Pick<Summary, 'invested_paise' | 'invested_to_confirm_paise' | 'investments_in_spent'>): string {
  const parts = []
  if (s.invested_paise) parts.push(`Invested ${rupees(s.invested_paise)}${s.investments_in_spent ? ', in Spent' : ''}`)
  if (s.invested_to_confirm_paise) parts.push(`Invested (to confirm) ${rupees(s.invested_to_confirm_paise)}, in Spent`)
  return parts.join(' · ')
}

/** The Investments filter: the category, or a payment tagged as an investment (confirmed or
 *  to confirm), so a suggested one shows too. Any other category filter matches its slug. */
export function inCategory(t: Txn, slug: string | null): boolean {
  if (!slug) return true
  return t.category === slug || (slug === 'investments' && Boolean(t.investment))
}

/** The row's tag (D-136): "Investment" or "Investment, to confirm". */
export function investmentTag(t: Pick<Txn, 'investment'>): string {
  if (t.investment === 'confirmed') return 'Investment'
  return t.investment === 'suggested' ? 'Investment, to confirm' : ''
}

/** The sender a credit belongs to (D-134): by person, else the sender of that one credit. */
export function senderOfCredit(t: Txn, todo: Snapshot['todo']): Sender | undefined {
  if (t.direction !== 'credit') return undefined
  const all = [...todo.senders, ...todo.answered]
  return all.find((s) => (t.person_id !== null && s.person_id === t.person_id) || (!s.person_id && s.txn_id === t.id))
}

/** The sheet of a credit from a person asks "Paid back?" (the To-do answer, D-134). */
export const asksPaidBack = (t: Txn, s: Sender | undefined): boolean =>
  Boolean(s) && t.direction === 'credit' && ['payback', 'uncertain', 'income', 'ignored'].includes(t.role)

/** On a payment: the paybacks linked to it, read only (D-134). "₹400 paid back by Ravi" for
 *  one you confirmed; "to confirm" for one the app guessed; "may be for this" for a candidate. */
export function paybackLines(debit: Txn, snap: Pick<Snapshot, 'paybacks' | 'transactions'>, name: (t: Txn) => string): string[] {
  const out = []
  for (const link of snap.paybacks ?? []) {
    if (link.debit !== debit.id) continue
    const back = snap.transactions.find((t) => t.id === link.credit)
    if (!back) continue
    const amount = rupees(back.amount_paise, true)
    if (link.status === 'candidate') out.push(`${amount} from ${name(back)} on ${dayLabel(back.time_utc)} may be for this`)
    else if (back.role_basis === 'owner') out.push(`${amount} paid back by ${name(back)}`)
    else out.push(`${amount} from ${name(back)}, to confirm`)
  }
  return out
}