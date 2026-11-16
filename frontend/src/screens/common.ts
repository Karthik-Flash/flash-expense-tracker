import type { Txn } from '../api/types.ts'

/** A name for every row, also when the bank gave none. */
export function nameOf(t: Txn): string {
  if (t.display_name) return t.display_name
  if (t.category === 'cash') return 'Cash withdrawal'
  return t.direction === 'credit' ? 'Bank transfer in' : 'Bank transfer'
}

export function roleText(t: Txn): string {
  switch (t.role) {
    case 'spend':
      return 'Counted in Spent'
    case 'card_bill_counted':
      return 'Card bill, counted in Spent'
    case 'refund':
      return 'Refund, lowers Spent'
    case 'payback':
      return 'From a person: counts as paid back once confirmed'
    case 'income':
      return 'Income'
    case 'uncertain':
      return 'To confirm'
    case 'self_transfer':
      return 'Between your own accounts, not counted'
    case 'card_bill_excluded':
      return 'Card bill, not counted'
    case 'fd_move':
      return 'Fixed deposit, not counted'
    case 'duplicate':
      return 'A second message for one payment, not counted'
    case 'ignored':
      return 'Ignored'
  }
}

/** Rows that count in Spent show the category; others say what they are. */
export function subtitle(t: Txn): string {
  if (t.role === 'spend' || t.role === 'card_bill_counted') return t.category_name
  if (t.role === 'refund') return `Refund · ${t.category_name}`
  if (t.role === 'payback') return 'From a person'
  if (t.role === 'income') return 'Income'
  if (t.role === 'uncertain') return 'To confirm'
  return 'Not counted'
}

export const isCredit = (t: Txn) => t.direction === 'credit'
