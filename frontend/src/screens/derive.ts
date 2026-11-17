// Pure helpers the screens derive from transactions (docs/ui-spec.md).

import { spentEffect } from '../api/client.ts'
import type { CategoryAmount, Txn } from '../api/types.ts'
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

/** Money sent to a person (People spending) or got back from one (paybacks). */
export function isPersonTxn(t: Txn): boolean {
  return (t.category === 'people' && spentEffect(t) !== 0) || (t.direction === 'credit' && t.role === 'payback')
}

/** The person of a row: the API's person id (one person under a name and a UPI ID once joined). */
export const personKey = (t: Txn): string => t.person_id ?? `name:${nameOf(t)}`

export interface Person {
  key: string
  name: string
  sent: number
  /** Confirmed paybacks: they lower Net. */
  got: number
  /** Paybacks the engine guessed: shown, never subtracted. */
  toConfirm: number
}

/** One row per person, biggest Sent first. Net is sent - got. */
export function ledger(txns: Txn[]): Person[] {
  const people = new Map<string, Person>()
  for (const t of txns.filter(isPersonTxn)) {
    const key = personKey(t)
    const p = people.get(key) ?? { key, name: nameOf(t), sent: 0, got: 0, toConfirm: 0 }
    if (t.role !== 'payback') p.sent += spentEffect(t)
    else if (t.role_basis === 'owner') p.got += t.amount_paise
    else p.toConfirm += t.amount_paise
    people.set(key, p)
  }
  return [...people.values()].sort((a, b) => b.sent - a.sent || b.got - a.got || a.name.localeCompare(b.name))
}

/** Spending grouped by name, biggest first. */
export function byName(txns: Txn[]): { name: string; total: number; count: number }[] {
  const groups = new Map<string, { name: string; total: number; count: number }>()
  for (const t of txns) {
    const g = groups.get(nameOf(t)) ?? { name: nameOf(t), total: 0, count: 0 }
    g.total += spentEffect(t)
    g.count += 1
    groups.set(g.name, g)
  }
  return [...groups.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name))
}

export interface Slice {
  /** null: "Other", the categories after the biggest ones. */
  slug: string | null
  name: string
  amount: number
  /** Of the positive categories' sum: the slices fill the ring exactly. */
  share: number
}

/** The ring's slices: the `max` biggest categories, the rest as one "Other". A category that
 *  refunds lowered to zero or below has no slice. */
export function ringSlices(parts: CategoryAmount[], max = 6): Slice[] {
  const positive = parts.filter((p) => p.amount_paise > 0).sort((a, b) => b.amount_paise - a.amount_paise)
  const total = positive.reduce((sum, p) => sum + p.amount_paise, 0)
  if (!total) return []
  const shown = positive.length > max + 1 ? positive.slice(0, max) : positive
  const slices: Slice[] = shown.map((p) => ({ slug: p.slug, name: p.name, amount: p.amount_paise, share: p.amount_paise / total }))
  const rest = positive.slice(shown.length)
  if (rest.length) {
    const amount = rest.reduce((sum, p) => sum + p.amount_paise, 0)
    slices.push({ slug: null, name: `Other (${rest.length})`, amount, share: amount / total })
  }
  return slices
}

/** Name search: every word must appear in the name, any case. */
export function matches(t: Txn, q: string): boolean {
  const name = nameOf(t).toLowerCase()
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((word) => name.includes(word))
}
