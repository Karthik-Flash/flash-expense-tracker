// Demo adapter: a student's October and November 2026, all names and amounts FAKE.
// It answers with the exact shapes of docs/api.md and applies writes in memory, so every
// screen can be tried. A dev switch picks a state: normal, waking, empty, error, stale.

import { ApiError, type Api, type SendAnswer, type SendRequest } from './client.ts'
import {
  SCHEMA_VERSION,
  type Basis,
  type Category,
  type CategoryAmount,
  type ChartSlice,
  type LabelView,
  type Merchant,
  type MonthData,
  type Person,
  type PersonRole,
  type PersonRow,
  type Role,
  type Sender,
  type SenderAnswer,
  type SenderStatus,
  type Snapshot,
  type SnapshotAnswer,
  type Summary,
  type Txn,
} from './types.ts'
import { nameOf } from '../screens/common.ts'
import { isPersonTxn, personKey } from '../screens/derive.ts'
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
  /** Read by the generic parser (another bank, D-101). */
  generic?: boolean
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
  credit([2026, 11, 17, 9, 40], 300, '*k77@okhdfcbank', 'payback', 'engine') // a masked UPI ID
  add([2026, 11, 7, 17, 0], 750, 'Meera S', 'gifts_donations', { label: 2, basis: 'owner' })
  // A second bank with no parser of its own yet: read automatically, to check (D-101).
  const other = { generic: true }
  add([2026, 11, 12, 13, 20], 340, 'Campus Bookshop', 'uncategorised', other)
  add([2026, 11, 15, 10, 5], 2000, null, 'cash', other)
  add([2026, 11, 14, 19, 30], 500, 'Priya N', 'other', { ...other, direction: 'credit', role: 'uncertain' })

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
  private answers = new Map<string, SendAnswer>()
  // People (4E): the owner's names by person key, and which identifier belongs to whom.
  private names = new Map<string, string>()
  private joins = new Map<string, string>()
  private parties = 0
  // Checks (4F-A): rows the owner said "Looks right" about.
  private checked = new Set<number>()

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

  /** An identifier's own key (as the server's sender id of its text). */
  private base(row: Row): string | null {
    return row.name ? senderId(row.name, row.id) : null
  }

  /** The person of a row: a party (p_) once named or joined, else its identifier. */
  private personOf(row: Row): string | null {
    const b = this.base(row)
    return b && (this.joins.get(b) ?? b)
  }

  private txn(row: Row): Txn {
    const { role, basis: roleBasis } = this.role(row)
    const { category, basis } = this.category(row)
    return {
      id: row.id,
      time_utc: row.time,
      amount_paise: row.amount,
      direction: row.direction,
      display_name: row.name && (this.names.get(this.personOf(row)!) ?? row.name),
      identifier: row.name && this.names.has(this.personOf(row)!) ? row.name : null,
      person_id: this.personOf(row),
      role,
      role_basis: roleBasis,
      category,
      category_name: NAME[category],
      category_basis: basis,
      label: row.label ? { id: row.label, name: this.labelNames.get(row.label) ?? '' } : null,
      generic: Boolean(row.generic),
      check: Boolean(row.generic) && !this.checked.has(row.id) && role !== 'ignored' && role !== 'duplicate',
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
      const id = this.personOf(row) ?? senderId(null, row.id)
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
          display_name: mine[0].name && (this.names.get(id) ?? mine[0].name),
          total_paise: mine.reduce((sum, r) => sum + r.amount, 0),
          count: mine.length,
          role,
          basis: roles.every((r) => r.basis === 'owner') ? ('owner' as const) : ('engine' as const),
          status,
          last_time_utc: mine[mine.length - 1].time,
          income_label: role === 'income' ? (this.incomeLabel.get(id) ?? null) : null,
          person_id: mine[0].name ? id : null,
          txn_id: mine[mine.length - 1].id,
        }
      })
      .sort((a, b) => b.total_paise - a.total_paise || a.id.localeCompare(b.id))
  }

  private summary(month: string): Summary {
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

  /** The demo's stand-in for GET /sync/snapshot, with the server's rules (app/api/snapshot.py). */
  snapshot(etag: string | null, signal: AbortSignal): Promise<SnapshotAnswer> {
    void signal
    return this.respond((): SnapshotAnswer => {
      const transactions = this.visible()
        .map((row) => this.txn(row))
        .sort((a, b) => b.time_utc.localeCompare(a.time_utc) || b.id - a.id)
      const months = [...new Set(transactions.map((t) => monthOf(t.time_utc)))].sort().map((month): MonthData => {
        const summary = this.summary(month)
        const mine = transactions.filter((t) => monthOf(t.time_utc) === month)
        const before = new Map(summary.previous.categories.map((c) => [c.slug, c.amount_paise]))
        return {
          month,
          summary,
          changes: {
            spent_paise: summary.spent_paise - summary.previous.spent_paise,
            categories: Object.fromEntries(summary.categories.map((c) => [c.slug, c.amount_paise - (before.get(c.slug) ?? 0)])),
          },
          chart: chart(summary.categories),
          merchants: merchants(mine),
          people: people(mine),
        }
      })
      const senders = this.sendersOf(this.visible())
      const labels = [...this.labelNames.entries()].map(([id, name]) => this.labelView(id, name)).sort((a, b) => a.name.localeCompare(b.name))
      const document: Omit<Snapshot, 'generated_at'> = {
        schema_version: SCHEMA_VERSION,
        owner_id: 'demo',
        engine_versions: { demo: '1' },
        months,
        transactions,
        todo: { senders: senders.filter((s) => s.status === 'to_confirm'), answered: senders.filter((s) => s.status !== 'to_confirm'), ...todo(transactions) },
        labels,
        categories: CATEGORIES,
        people: this.peopleOf(transactions),
      }
      const text = JSON.stringify(document)
      const tag = `"${senderId(text, 0)}"`
      if (etag === tag) return { status: 304 }
      return { status: 200, etag: tag, snapshot: { ...document, generated_at: new Date().toISOString() }, bytes: text.length }
    })
  }

  /** The demo's stand-in for the six owner writes, with the server's Idempotency-Key rule:
   *  the same op_id gets the same answer and changes nothing (app/api/ops.py). */
  send(request: SendRequest, signal: AbortSignal): Promise<SendAnswer> {
    void signal
    return this.respond((): SendAnswer => {
      const done = this.answers.get(request.op_id)
      if (done) return done
      let answer: SendAnswer
      try {
        this.apply(request)
        answer = { status: request.method === 'POST' ? 201 : 200, detail: null, message: '' }
      } catch (e) {
        if (!(e instanceof ApiError)) throw e
        answer = { status: e.status, detail: e.message, message: e.message }
      }
      this.answers.set(request.op_id, answer)
      return answer
    })
  }

  /** As app/api/v1.py people_directory: who can be named or joined. */
  private peopleOf(txns: Txn[]): Person[] {
    const roles = new Map(this.sendersOf(this.visible()).map((s) => [s.id, roleOf(s)]))
    const out = new Map<string, Person>()
    const counts = new Set<string>()
    for (const t of txns) {
      const row = this.rows.find((x) => x.id === t.id)!
      const key = this.personOf(row)
      if (!key) continue
      const p = out.get(key) ?? { key, name: t.display_name, named: this.names.has(key), txn_id: t.id, role: roles.get(key) ?? null, identifiers: [] }
      if (!p.identifiers.some((i) => i.name === row.name)) p.identifiers.push({ name: row.name, txn_id: t.id, from_file: false })
      if (roles.has(key) || t.category === 'people' || t.role === 'payback' || key.startsWith('p_')) counts.add(key)
      out.set(key, p)
    }
    return [...out.values()].filter((p) => counts.has(p.key)).sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
  }

  /** A party key for this row's person, made when it is still a lone identifier. */
  private partyOf(row: Row): string {
    const key = this.personOf(row)
    if (!key) throw new ApiError(422, 'The transaction has no merchant text.')
    if (key.startsWith('p_')) return key
    const party = `p_${++this.parties}`
    this.joins.set(key, party)
    return party
  }

  private person(txnId: number, method: string, what: string, b: Record<string, unknown>): void {
    const row = this.rows.find((r) => r.id === txnId)
    if (!row) throw new ApiError(404, 'No such transaction.')
    if (what === 'name' && method === 'PUT') {
      const name = String(b.name ?? '').trim().replace(/\s+/g, ' ')
      if (!name || [...name].length > 30) throw new ApiError(422, 'A name has 1 to 30 characters.')
      this.names.set(this.partyOf(row), name)
    } else if (what === 'name') {
      if (!this.names.delete(this.personOf(row) ?? '')) throw new ApiError(404, 'This person has no name to clear.')
    } else if (method === 'PUT') {
      const into = this.rows.find((r) => r.id === Number(b.into))
      if (!into) throw new ApiError(404, 'No such transaction.')
      const from = this.personOf(row)
      if (!from) throw new ApiError(422, 'The transaction has no merchant text.')
      if (from === this.personOf(into)) throw new ApiError(409, 'These are already the same person.')
      const roles = new Map(this.sendersOf(this.rows).map((s) => [s.id, roleOf(s)]))
      const [mine, theirs] = [roles.get(from), roles.get(this.personOf(into)!)]
      const role = b.role as PersonRole | undefined
      if (mine && theirs && mine !== theirs && !role) throw new ApiError(409, 'The two have different answers: choose the one the person keeps.')
      const target = this.partyOf(into)
      for (const [identifier, owner] of [...this.joins]) if (owner === from) this.joins.set(identifier, target)
      if (!from.startsWith('p_')) this.joins.set(from, target)
      if (!this.names.has(target) && this.names.has(from)) this.names.set(target, this.names.get(from)!)
      if (!this.names.has(target) && into.name) this.names.set(target, into.name.slice(0, 30)) // "Same as Rohit V"
      const chosen = role ?? theirs ?? mine
      if (chosen && chosen !== theirs) {
        for (const r of this.rows.filter((x) => x.direction === 'credit' && this.personOf(x) === target)) {
          if (chosen === 'none') this.roleAnswer.delete(r.id)
          else this.roleAnswer.set(r.id, chosen === 'friend' ? 'payback' : chosen === 'income' ? 'income' : 'ignored')
        }
      }
    } else {
      const b0 = this.base(row)
      const owner = b0 && this.joins.get(b0)
      if (!b0 || !owner) throw new ApiError(404, 'This identifier is not part of a person.')
      if ([...this.joins.values()].filter((o) => o === owner).length < 2) throw new ApiError(409, "This is the person's only identifier.")
      this.joins.delete(b0)
    }
  }

  private apply({ method, path, body }: SendRequest): void {
    const b = (body ?? {}) as Record<string, string | number | undefined>
    const person = /^\/people\/(\d+)\/(name|join)$/.exec(path)
    if (person) return this.person(Number(person[1]), method, person[2], b)
    const check = /^\/transactions\/(\d+)\/(check|ignore)$/.exec(path)
    if (check) return this.check(Number(check[1]), check[2], method)
    const sender = /^\/senders\/([^/]+)$/.exec(path)
    const txn = /^\/transactions\/(\d+)\/(category|label)$/.exec(path)
    if (sender && method === 'PUT') return this.answerSender(decodeURIComponent(sender[1]), b as unknown as SenderAnswer)
    if (sender && method === 'DELETE') return this.resetSender(decodeURIComponent(sender[1]))
    if (path === '/labels' && method === 'POST') return void this.createLabel(String(b.name))
    if (txn?.[2] === 'category' && method === 'PUT') return this.setCategory(Number(txn[1]), String(b.category), b.scope as 'merchant' | 'transaction')
    if (txn?.[2] === 'label' && method === 'PUT') {
      const id = b.new_label !== undefined ? this.createLabel(String(b.new_label)) : Number(b.label_id)
      return this.setLabel(Number(txn[1]), id)
    }
    if (txn?.[2] === 'label' && method === 'DELETE') return this.clearLabel(Number(txn[1]))
    throw new ApiError(404, 'Not found.')
  }

  /** As owner_actions.looks_right, not_a_payment and count_again (D-101, D-103). */
  private check(txnId: number, what: string, method: string): void {
    const row = this.rows.find((r) => r.id === txnId)
    if (!row) throw new ApiError(404, 'No such transaction.')
    if (what === 'check') {
      if (!row.generic) throw new ApiError(422, 'Only a payment read automatically needs a check.')
      this.checked.add(txnId)
    } else if (method === 'PUT') {
      this.roleAnswer.set(txnId, 'ignored')
    } else if (this.roleAnswer.has(txnId)) {
      if (this.roleAnswer.get(txnId) !== 'ignored') throw new ApiError(409, 'This payment is not marked as not a payment.')
      this.roleAnswer.delete(txnId)
    }
  }

  private answerSender(id: string, answer: SenderAnswer): void {
    const sender = this.sendersOf(this.rows).find((s) => s.id === id)
    if (!sender) throw new ApiError(404, 'No such sender.')
    const role: Role = answer.answer === 'friend' ? 'payback' : answer.answer === 'income' ? 'income' : 'ignored'
    const mine = this.rows.filter((r) => r.direction === 'credit' && (this.personOf(r) ?? senderId(null, r.id)) === id)
    for (const row of mine) this.roleAnswer.set(row.id, role)
    if (answer.answer === 'income') this.incomeLabel.set(id, answer.label.trim().replace(/\s+/g, ' '))
  }

  private resetSender(id: string): void {
    const mine = this.rows.filter((r) => r.direction === 'credit' && (this.personOf(r) ?? senderId(null, r.id)) === id)
    if (!mine.length) throw new ApiError(404, 'No such sender.')
    for (const row of mine) this.roleAnswer.delete(row.id)
    this.incomeLabel.delete(id)
  }

  private setCategory(txnId: number, category: string, scope: 'merchant' | 'transaction'): void {
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
  }

  private createLabel(name: string): number {
    const clean = name.trim().replace(/\s+/g, ' ')
    if (!clean || [...clean].length > 30) throw new ApiError(422, 'A label name has 1 to 30 characters.')
    for (const existing of this.labelNames.values()) {
      if (existing.toLowerCase() === clean.toLowerCase()) throw new ApiError(409, 'A label with this name already exists.')
    }
    const id = Math.max(0, ...this.labelNames.keys()) + 1
    this.labelNames.set(id, clean)
    return id
  }

  private setLabel(txnId: number, labelId: number): void {
    const row = this.rows.find((r) => r.id === txnId)
    if (!row) throw new ApiError(404, 'No such transaction.')
    if (!this.labelNames.has(labelId)) throw new ApiError(404, 'No such label.')
    row.label = labelId
  }

  private clearLabel(txnId: number): void {
    const row = this.rows.find((r) => r.id === txnId)
    if (!row) throw new ApiError(404, 'No such transaction.')
    row.label = null
  }
}

/** As owner_actions.person_role. */
function roleOf(s: Sender): PersonRole {
  if (s.status === 'ignored') return 'ignore'
  if (s.status === 'to_confirm') return 'none'
  return s.role === 'income' ? 'income' : 'friend'
}

// The server's figures, for the demo only (app/api/snapshot.py does this for real data). The
// screens never add up money; this file stands in for the server.

const effect = (t: Txn) => (t.role === 'spend' || t.role === 'card_bill_counted' ? t.amount_paise : t.role === 'refund' ? -t.amount_paise : 0)

function merchants(txns: Txn[]): Record<string, Merchant[]> {
  const groups = new Map<string, Map<string, Merchant>>()
  for (const t of txns) {
    const names = groups.get(t.category) ?? new Map<string, Merchant>()
    const g = names.get(nameOf(t)) ?? { name: nameOf(t), total_paise: 0, count: 0 }
    names.set(g.name, { ...g, total_paise: g.total_paise + effect(t), count: g.count + 1 })
    groups.set(t.category, names)
  }
  return Object.fromEntries(
    [...groups].map(([slug, names]) => [slug, [...names.values()].sort((a, b) => b.total_paise - a.total_paise || a.name.localeCompare(b.name))]),
  )
}

function people(txns: Txn[]): PersonRow[] {
  const rows = new Map<string, PersonRow>()
  for (const t of txns.filter(isPersonTxn)) {
    const key = personKey(t)
    const p = rows.get(key) ?? { key, name: nameOf(t), sent_paise: 0, got_back_paise: 0, to_confirm_paise: 0, net_paise: 0 }
    if (t.role !== 'payback') p.sent_paise += effect(t)
    else if (t.role_basis === 'owner') p.got_back_paise += t.amount_paise
    else p.to_confirm_paise += t.amount_paise
    p.net_paise = p.sent_paise - p.got_back_paise
    rows.set(key, p)
  }
  return [...rows.values()].sort((a, b) => b.sent_paise - a.sent_paise || b.got_back_paise - a.got_back_paise || a.name.localeCompare(b.name))
}

function chart(parts: CategoryAmount[]): MonthData['chart'] {
  const positive = parts.filter((p) => p.amount_paise > 0).sort((a, b) => b.amount_paise - a.amount_paise)
  const shown = positive.length > 7 ? positive.slice(0, 6) : positive
  const slices: ChartSlice[] = shown.map((p) => ({ slug: p.slug, name: p.name, amount_paise: p.amount_paise }))
  const rest = positive.slice(shown.length)
  const sum = (list: CategoryAmount[]) => list.reduce((total, p) => total + p.amount_paise, 0)
  if (rest.length) slices.push({ slug: null, name: `Other (${rest.length})`, amount_paise: sum(rest) })
  return { total_paise: sum(positive), slices }
}

function todo(txns: Txn[]): Pick<Snapshot['todo'], 'merchants' | 'unnamed'> {
  const groups = new Map<string, Snapshot['todo']['merchants'][number]>()
  let unnamed = 0
  for (const t of txns) {
    if (t.category !== 'uncategorised' || (t.role !== 'spend' && t.role !== 'card_bill_counted')) continue
    if (!t.display_name) {
      unnamed++
      continue
    }
    const g = groups.get(t.display_name) ?? { name: t.display_name, total_paise: 0, count: 0, txn_id: t.id, last_time_utc: t.time_utc }
    groups.set(t.display_name, { ...g, total_paise: g.total_paise + t.amount_paise, count: g.count + 1 })
  }
  return { merchants: [...groups.values()].sort((a, b) => b.total_paise - a.total_paise), unnamed }
}
