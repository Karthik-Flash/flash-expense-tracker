// Pure helpers the screens derive from transactions. 3F-3 may move some to the API
// (docs/ui-spec.md, "API gaps").

import { spentEffect } from '../api/client.ts'
import type { Txn } from '../api/types.ts'
import { dayKey } from '../lib/dates.ts'
import { nameOf } from './common.ts'

export const LABEL_MAX = 30

const tidy = (text: string) => text.trim().replace(/\s+/g, ' ')

/** A name as it will be saved, and why it cannot be ('' when it can). */
export function labelName(raw: string, existing: string[]): { name: string; error: string } {
  const name = tidy(raw)
  let error = ''
  if (!name) error = 'Type a name.'
  else if ([...name].length > LABEL_MAX) error = `Use at most ${LABEL_MAX} characters.`
  else if (existing.some((e) => tidy(e).toLowerCase() === name.toLowerCase())) error = 'A label with this name already exists.'
  return { name, error }
}

/** Spent by category (refunds lower it). */
export function spentByCategory(txns: Txn[]): Map<string, number> {
  const out = new Map<string, number>()
  for (const t of txns) {
    const effect = spentEffect(t)
    if (effect) out.set(t.category, (out.get(t.category) ?? 0) + effect)
  }
  return out
}

/** Last month's rows to compare with: all of them, or up to the same IST day when `today` ("2026-11-17") is in the month on screen. */
export function comparable(lastMonth: Txn[], today: string | null): Txn[] {
  if (!today) return lastMonth
  const day = today.slice(8)
  return lastMonth.filter((t) => dayKey(t.time_utc).slice(8) <= day)
}

/** Money sent to a person (People spending) or got back from one (paybacks, confirmed or not). */
export function isPersonTxn(t: Txn): boolean {
  return (t.category === 'people' && spentEffect(t) !== 0) || (t.direction === 'credit' && t.role === 'payback')
}

export interface Person {
  name: string
  sent: number
  got: number
}

/** One row per person, biggest Sent first. Net is sent - got. */
export function ledger(txns: Txn[]): Person[] {
  const people = new Map<string, Person>()
  for (const t of txns.filter(isPersonTxn)) {
    const name = nameOf(t)
    const p = people.get(name) ?? { name, sent: 0, got: 0 }
    if (t.role === 'payback') p.got += t.amount_paise
    else p.sent += spentEffect(t)
    people.set(name, p)
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

/** Name search: every word must appear in the name, any case. */
export function matches(t: Txn, q: string): boolean {
  const name = nameOf(t).toLowerCase()
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((word) => name.includes(word))
}
