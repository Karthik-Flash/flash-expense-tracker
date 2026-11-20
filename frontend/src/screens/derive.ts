// Pure helpers the screens use on the snapshot (docs/ui-spec.md). They filter, sort and
// search; every money figure comes from the server (D-088).

import type { Category, MonthData, Person, Snapshot, Txn } from '../api/types.ts'
import { dayLabel, monthOf } from '../lib/dates.ts'
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
