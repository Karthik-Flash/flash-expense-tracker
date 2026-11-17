// Demo adapter: a student's October and November 2026, all names and amounts FAKE.
// It answers with the exact shapes of docs/api.md and applies writes in memory, so every
// screen can be tried. A dev switch picks a state: normal, waking, empty, error, stale.

import { ApiError, type Api } from './client.ts'
import type {
  Basis,
  Category,
  CategoryAmount,
  LabelSummary,
  LabelView,
  Role,
  Sender,
  SenderStatus,
  Summary,
  Txn,
  TxnQuery,
} from './types.ts'
import { currentMonth, dayKey, istToIso, monthOf, shiftMonth, today } from '../lib/dates.ts'

export type DemoState = 'normal' | 'waking' | 'empty' | 'error' | 'stale'
export const DEMO_STATES: DemoState[] = ['normal', 'waking', 'empty', 'error', 'stale']

export const CATEGORIES: Category[] = [
  ['food_drinks', 'Food & Drinks'],
  ['groceries', 'Groceries'],
  ['travel', 'Travel'],
  ['shopping', 'Shopping'],
  ['bills_recharges', 'Bills & Recharges'],
  ['subscriptions', 'Subscriptions'],
  ['health', 'Health'],
  ['personal_care', 'Personal Care'],
  ['entertainment', 'Entertainment'],
  ['education', 'Education'],
  ['rent_hostel', 'Rent & Hostel'],
  ['emi_loans', 'EMI & Loans'],
  ['investments', 'Investments'],
  ['gifts_donations', 'Gifts & Donations'],
  ['people', 'People'],
  ['cash', 'Cash'],
  ['card_bill', 'Card bill'],
  ['fees_charges', 'Fees & Charges'],
  ['other', 'Other'],
  ['uncategorised', 'Uncategorised'],
].map(([slug, name]) => ({ slug, name }))
const NAME = Object.fromEntries(CATEGORIES.map((c) => [c.slug, c.name]))
const SPENDING: Role[] = ['spend', 'card_bill_counted', 'refund']
const NOT_SPENDING: Partial<Record<Role, string>> = {
  payback: 'people',
  income: 'other',
  uncertain: 'other',
  ignored: 'other',
  duplicate: 'other',
}

interface Row {
  id: number
  time: string
  amount: number // paise
  direction: 'debit' | 'credit'
  name: string | null
  role: Role // the engine's role
  basis: Basis
  engineCategory: string
  label: number | null
}

/** Small deterministic generator: the same demo every time. */
function generator(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) % 2147483648
    return s / 2147483648
  }
}

function build(): Row[] {
  const rows: Omit<Row, 'id'>[] = []
  const rnd = generator(42)
  const pick = (low: number, high: number) => Math.round(low + rnd() * (high - low))
  const add = (
    when: [number, number, number, number, number],
    rupees: number,
    name: string | null,
    category: string,
    extra: Partial<Row> = {},
  ) =>
    rows.push({
      time: istToIso(...when),
      amount: Math.round(rupees * 100),
      direction: 'debit',
      name,
      role: 'spend',
      basis: 'engine',
      engineCategory: category,
      label: null,
      ...extra,
    })
  const credit = (when: [number, number, number, number, number], rupees: number, name: string | null, role: Role, basis: Basis) =>
    add(when, rupees, name, NOT_SPENDING[role] ?? 'other', { direction: 'credit', role, basis })

  for (const [month, lastDay] of [[10, 31], [11, 17]] as const) {
    const y = 2026
    for (let day = 1; day <= lastDay; day++) {
      add([y, month, day, 8, pick(5, 50)], pick(12, 25), 'Gate 2 Tea Stall', 'food_drinks')
      if (rnd() < 0.6) add([y, month, day, 17, pick(0, 55)], pick(10, 20), 'Gate 2 Tea Stall', 'food_drinks')
      if (rnd() < 0.8) add([y, month, day, 13, pick(0, 40)], pick(70, 115), 'Campus Canteen', 'food_drinks')
      if (day % 3 === 0) add([y, month, day, 22, pick(0, 50)], pick(60, 95), 'Night Canteen', 'food_drinks')
      if (day % 4 === 1) add([y, month, day, 20, pick(5, 55)], pick(220, 420), 'Swiggy', 'food_drinks')
      if (day % 6 === 2) add([y, month, day, 11, pick(0, 59)], pick(25, 45), 'Vendmart Block B', 'uncategorised')
      if (day % 7 === 3) add([y, month, day, 16, pick(0, 59)], pick(30, 60), 'Campus Xerox', 'uncategorised')
      if (day % 9 === 4) add([y, month, day, 19, pick(0, 59)], pick(180, 520), 'Blinkit', 'groceries')
      if (day % 5 === 0) add([y, month, day, 9, pick(0, 59)], pick(45, 90), 'Rapido', 'travel')
    }
    add([y, month, 1, 10, 15], 4500, 'Sunrise Hostel', 'rent_hostel')
    add([y, month, 2, 21, 40], 6000, 'Rohit V', 'people')
    add([y, month, 3, 9, 12], 299, 'Jio', 'bills_recharges')
    add([y, month, 5, 0, 30], 59, 'Spotify', 'subscriptions')
    add([y, month, 5, 0, 31], 59, 'Spotify', 'other', { role: 'duplicate' })
    add([y, month, 8, 18, 20], 1200, 'Meera S', 'people')
    add([y, month, 10, 12, 0], 2000, null, 'cash')
    add([y, month, 11, 15, 25], 350, 'Kiran D', 'people')
    add([y, month, 14, 18, 45], pick(120, 340), 'Sri Sai Stores', 'uncategorised')
    add([y, month, 6, 19, 5], pick(120, 340), 'Sri Sai Stores', 'uncategorised')
    credit([y, month, 1, 9, 0], 10000, 'ramesh.k@okaxis', 'payback', 'engine')
    credit([y, month, 9, 20, 10], 450, 'Meera S', 'payback', 'owner')
    credit([y, month, 15, 21, 0], 800, 'Arjun K', 'payback', 'engine')
  }
  add([2026, 10, 20, 15, 0], 1450, 'Lakshmi Enterprises', 'uncategorised')
  add([2026, 10, 25, 18, 30], 260, 'Uber', 'travel')
  credit([2026, 10, 27, 11, 0], 200, 'Kiran D', 'payback', 'engine')
  credit([2026, 10, 16, 14, 0], 1500, null, 'uncertain', 'engine')
  // November: a trip to Goa, labelled.
  const trip = { label: 1 }
  add([2026, 11, 12, 22, 15], 1850, 'IRCTC', 'travel', trip)
  add([2026, 11, 13, 9, 30], 2500, 'Arjun K', 'people', trip)
  add([2026, 11, 13, 14, 10], 1200, 'Palm Grove Stay', 'travel', { ...trip, basis: 'owner' })
  add([2026, 11, 13, 20, 45], 640, 'Baga Shack', 'food_drinks', { ...trip, basis: 'owner' })
  add([2026, 11, 14, 13, 5], 380, 'Baga Shack', 'food_drinks', { ...trip, basis: 'owner' })
  add([2026, 11, 15, 11, 20], 420, 'Goa Scooty Rentals', 'uncategorised', trip)
  add([2026, 11, 16, 19, 40], 120, 'Swiggy', 'food_drinks', { direction: 'credit', role: 'refund' })
  credit([2026, 11, 16, 22, 5], 1250, 'Rohit V', 'payback', 'engine')
  add([2026, 11, 7, 17, 0], 750, 'Meera S', 'gifts_donations', { label: 2, basis: 'owner' })

  return rows
    .sort((a, b) => a.time.localeCompare(b.time))
    .map((row, index) => ({ ...row, id: 1001 + index }))
}

function senderId(name: string | null, id: number): string {
  const seed = name ? `key|${name}` : `txn|${id}`
  let h = 2166136261
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0
  return `s_${h.toString(16).padStart(8, '0')}${String(seed.length).padStart(4, '0')}`
}

export class FakeApi implements Api {
  readonly demo = true
  state: DemoState = 'normal'
  private rows = build()
  private labelNames = new Map<number, string>([
    [1, 'Goa trip'],
    [2, "Meera's birthday"],
  ])
  private merchantDefault = new Map<string, string>()
  private oneOff = new Map<number, string>()
  private roleAnswer = new Map<number, Role>()
  private incomeLabel = new Map<string, string>()
  private wokeAt = 0

  setState(state: DemoState): void {
    this.state = state
    this.wokeAt = 0
  }

  private async respond<T>(make: () => T): Promise<T> {
    if (this.state === 'waking' && !this.wokeAt) {
      await new Promise((resolve) => setTimeout(resolve, 9000))
      this.wokeAt = Date.now()
    } else {
      await new Promise((resolve) => setTimeout(resolve, 180))
    }
    if (this.state === 'error') throw new ApiError(503, 'The server is not ready yet. Try again in a minute.')
    return make()
  }

  private visible(): Row[] {
    return this.state === 'empty' ? [] : this.rows
  }

  private role(row: Row): { role: Role; basis: Basis } {
    const answer = this.roleAnswer.get(row.id)
    return answer ? { role: answer, basis: 'owner' } : { role: row.role, basis: row.basis }
  }

  private category(row: Row): { category: string; basis: Basis } {
    const { role } = this.role(row)
    if (!SPENDING.includes(role)) return { category: NOT_SPENDING[role] ?? 'other', basis: 'engine' }
    const own = this.oneOff.get(row.id) ?? (row.name ? this.merchantDefault.get(row.name) : undefined)
    return own ? { category: own, basis: 'owner' } : { category: row.engineCategory, basis: row.basis }
  }

  private txn(row: Row): Txn {
    const { role, basis: roleBasis } = this.role(row)
    const { category, basis } = this.category(row)
    return {
      id: row.id,
      time_utc: row.time,
      amount_paise: row.amount,
      direction: row.direction,
      display_name: row.name,
      person_id: row.name ? senderId(row.name, row.id) : null,
      role,
      role_basis: roleBasis,
      category,
      category_name: NAME[category],
      category_basis: basis,
      label: row.label ? { id: row.label, name: this.labelNames.get(row.label) ?? '' } : null,
    }
  }

  private totals(rows: Row[]) {
    let spent = 0
    let paidBack = 0
    let toConfirm = 0
    let income = 0
    const parts = new Map<string, number>()
    for (const row of rows) {
      const { role, basis } = this.role(row)
      if (SPENDING.includes(role)) {
        const signed = role === 'refund' ? -row.amount : row.amount
        spent += signed
        const { category } = this.category(row)
        parts.set(category, (parts.get(category) ?? 0) + signed)
      } else if (role === 'payback') {
        if (basis === 'owner') paidBack += row.amount
        else toConfirm += row.amount
      } else if (role === 'income') income += row.amount
    }
    const categories: CategoryAmount[] = CATEGORIES.filter((c) => parts.get(c.slug)).map((c) => ({
      slug: c.slug,
      name: c.name,
      amount_paise: parts.get(c.slug) ?? 0,
    }))
    return { spent, paidBack, toConfirm, income, categories }
  }

  private sendersOf(rows: Row[]): Sender[] {
    const groups = new Map<string, Row[]>()
    for (const row of rows) {
      const { role } = this.role(row)
      if (row.direction !== 'credit' || !['payback', 'uncertain', 'income', 'ignored'].includes(role)) continue
      const id = senderId(row.name, row.id)
      groups.set(id, [...(groups.get(id) ?? []), row])
    }
    return [...groups.entries()]
      .map(([id, mine]) => {
        const roles = mine.map((r) => this.role(r))
        const kept = roles.filter((r) => r.role !== 'ignored')
        const open = roles.some((r) => r.role === 'uncertain' || (r.role === 'payback' && r.basis !== 'owner'))
        const status: SenderStatus = open ? 'to_confirm' : kept.length ? 'confirmed' : 'ignored'
        const role = (kept.at(-1)?.role ?? 'ignored') as Sender['role']
        return {
          id,
          display_name: mine[0].name,
          total_paise: mine.reduce((sum, r) => sum + r.amount, 0),
          count: mine.length,
          role,
          basis: roles.every((r) => r.basis === 'owner') ? ('owner' as const) : ('engine' as const),
          status,
          last_time_utc: mine[mine.length - 1].time,
          income_label: role === 'income' ? (this.incomeLabel.get(id) ?? null) : null,
        }
      })
      .sort((a, b) => b.total_paise - a.total_paise || a.id.localeCompare(b.id))
  }

  summary(month: string): Promise<Summary> {
    return this.respond(() => {
      const rows = this.visible().filter((r) => monthOf(r.time) === month)
      const t = this.totals(rows)
      const open = this.sendersOf(rows).filter((s) => s.status === 'to_confirm')
      return {
        month,
        spent_paise: t.spent,
        paid_back_paise: t.paidBack,
        to_confirm: { amount_paise: t.toConfirm, senders: open.length },
        net_paise: t.spent - t.paidBack,
        income_paise: t.income,
        categories: t.categories,
        counts: {
          uncategorised_spend: rows.filter(
            (r) => SPENDING.includes(this.role(r).role) && this.category(r).category === 'uncategorised',
          ).length,
          senders_to_confirm: open.length,
          not_counted_yet: rows.length ? (month === '2026-11' ? 3 : 5) : 0,
        },
        stale: this.state === 'stale',
        last_recompute_utc: rows.length ? '2026-11-17T03:00:00Z' : null,
        previous: this.previous(month),
      }
    })
  }

  /** As the API: up to the same IST day when the month is the current one, else whole. */
  private previous(month: string): Summary['previous'] {
    const before = shiftMonth(month, -1)
    const whole = month !== currentMonth()
    const day = today().slice(8)
    const rows = this.visible().filter((r) => monthOf(r.time) === before && (whole || dayKey(r.time).slice(8) <= day))
    const t = this.totals(rows)
    return { month: before, whole, spent_paise: t.spent, categories: t.categories }
  }

  transaction(id: number) {
    return this.respond(() => {
      const row = this.visible().find((r) => r.id === id)
      if (!row) throw new ApiError(404, 'No such transaction.')
      return this.txn(row)
    })
  }

  transactions(query: TxnQuery) {
    return this.respond(() => {
      const limit = query.limit ?? 50
      let items = this.visible()
        .map((row) => this.txn(row))
        .filter(
          (t) =>
            (!query.month || monthOf(t.time_utc) === query.month) &&
            (!query.category || t.category === query.category) &&
            (query.label === undefined || t.label?.id === query.label),
        )
        .sort((a, b) => b.time_utc.localeCompare(a.time_utc) || b.id - a.id)
      if (query.cursor) {
        const [ms, id] = query.cursor.split('_').map(Number)
        items = items.filter((t) => {
          const at = Date.parse(t.time_utc)
          return at < ms || (at === ms && t.id < id)
        })
      }
      const page = items.slice(0, limit)
      const last = page[page.length - 1]
      return {
        items: page,
        next_cursor: items.length > limit && last ? `${Date.parse(last.time_utc)}_${last.id}` : null,
      }
    })
  }

  categories() {
    return this.respond(() => CATEGORIES)
  }

  private labelView(id: number, name: string): LabelView {
    const rows = this.visible().filter((r) => r.label === id)
    const t = this.totals(rows)
    return {
      id,
      name,
      transactions: rows.length,
      spent_paise: t.spent,
      paid_back_paise: t.paidBack,
      to_confirm_paise: t.toConfirm,
      net_paise: t.spent - t.paidBack,
      categories: t.categories,
    }
  }

  labels() {
    return this.respond(() =>
      [...this.labelNames.entries()]
        .map(([id, name]): LabelSummary => {
          const { categories, ...totals } = this.labelView(id, name)
          void categories
          return totals
        })
        .sort((a, b) => a.name.localeCompare(b.name)),
    )
  }

  label(id: number): Promise<LabelView> {
    return this.respond(() => {
      const name = this.labelNames.get(id)
      if (!name) throw new ApiError(404, 'No such label.')
      return this.labelView(id, name)
    })
  }

  senders(status: SenderStatus | 'all' = 'to_confirm') {
    return this.respond(() =>
      this.sendersOf(this.visible()).filter((s) => status === 'all' || s.status === status),
    )
  }

  answerSender(id: string, answer: Parameters<Api['answerSender']>[1]) {
    return this.respond(() => {
      const sender = this.sendersOf(this.rows).find((s) => s.id === id)
      if (!sender) throw new ApiError(404, 'No such sender.')
      const role: Role = answer.answer === 'friend' ? 'payback' : answer.answer === 'income' ? 'income' : 'ignored'
      const mine = this.rows.filter((r) => r.direction === 'credit' && senderId(r.name, r.id) === id)
      for (const row of mine) this.roleAnswer.set(row.id, role)
      if (answer.answer === 'income') this.incomeLabel.set(id, answer.label.trim().replace(/\s+/g, ' '))
      return { result: { id, credits: mine.length }, recompute: { status: 'done', run: 1 } }
    })
  }

  resetSender(id: string) {
    return this.respond(() => {
      const mine = this.rows.filter((r) => r.direction === 'credit' && senderId(r.name, r.id) === id)
      if (!mine.length) throw new ApiError(404, 'No such sender.')
      for (const row of mine) this.roleAnswer.delete(row.id)
      this.incomeLabel.delete(id)
      return { result: { id, credits: mine.length }, recompute: { status: 'done', run: 1 } }
    })
  }

  setCategory(txnId: number, category: string, scope: 'merchant' | 'transaction') {
    return this.respond(() => {
      const row = this.rows.find((r) => r.id === txnId)
      if (!row) throw new ApiError(404, 'No such transaction.')
      if (!NAME[category]) throw new ApiError(422, 'Not a category of the list.')
      if (scope === 'merchant') {
        if (!row.name) throw new ApiError(422, 'The transaction has no merchant text.')
        this.merchantDefault.set(row.name, category)
        this.oneOff.delete(txnId)
      } else {
        this.oneOff.set(txnId, category)
      }
      return { result: { id: txnId, category, scope }, recompute: { status: 'done', run: 1 } }
    })
  }

  createLabel(name: string) {
    return this.respond(() => {
      const clean = name.trim().replace(/\s+/g, ' ')
      if (!clean || [...clean].length > 30) throw new ApiError(422, 'A label name has 1 to 30 characters.')
      for (const existing of this.labelNames.values()) {
        if (existing.toLowerCase() === clean.toLowerCase()) throw new ApiError(409, 'A label with this name already exists.')
      }
      const id = Math.max(0, ...this.labelNames.keys()) + 1
      this.labelNames.set(id, clean)
      return { id, name: clean }
    })
  }

  setLabel(txnId: number, labelId: number) {
    return this.respond(() => {
      const row = this.rows.find((r) => r.id === txnId)
      if (!row) throw new ApiError(404, 'No such transaction.')
      if (!this.labelNames.has(labelId)) throw new ApiError(404, 'No such label.')
      row.label = labelId
      return { result: { id: txnId, label_id: labelId }, recompute: { status: 'unchanged', run: null } }
    })
  }

  clearLabel(txnId: number) {
    return this.respond(() => {
      const row = this.rows.find((r) => r.id === txnId)
      if (!row) throw new ApiError(404, 'No such transaction.')
      row.label = null
      return { result: { id: txnId, label_id: null }, recompute: { status: 'unchanged', run: null } }
    })
  }
}
