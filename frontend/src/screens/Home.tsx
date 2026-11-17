import type { Summary, Txn } from '../api/types.ts'
import { currentMonth, monthLabel, shiftMonth, today } from '../lib/dates.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { HOME } from '../view.ts'
import { joinLoads, navigate, useApp, useLoad, useMonthTxns, useNav } from '../state.tsx'
import { Bar, Empty, Figure, Header, Icon, Loaded, Money, MonthSwitcher, Notice, RowButton, Section } from '../ui.tsx'
import { categoryIcon, nameOf } from './common.ts'
import { byName, comparable, isPersonTxn, ledger, spentByCategory } from './derive.ts'
import { TxnList } from './Transactions.tsx'

export function Home() {
  const { api } = useApp()
  const { month, replace } = useNav()
  const [summary, retrySummary] = useLoad(() => api.summary(month), ['summary', month])
  const [txns, retryTxns] = useMonthTxns(month)
  const [before, retryBefore] = useMonthTxns(shiftMonth(month, -1))
  return (
    <>
      <div className="pt-2">
        <MonthSwitcher month={month} setMonth={(m) => replace({ month: m })} latest={currentMonth()} />
      </div>
      <Loaded
        load={joinLoads(summary, txns, before)}
        retry={() => {
          retrySummary()
          retryTxns()
          retryBefore()
        }}
      >
        {([s, mine, last]) => <SummaryView s={s} txns={mine} lastMonth={last} />}
      </Loaded>
    </>
  )
}

/** "Spent ₹1,240 less than this time last month". Past months compare whole months. */
function comparison(diff: number, month: string, toDate: boolean): string {
  const than = toDate ? 'this time last month' : `in ${monthLabel(shiftMonth(month, -1))}`
  if (Math.abs(diff) < 50) return `Spent the same as ${than}`
  return `Spent ${rupees(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'} than ${than}`
}

function change(now: number, before: number): string {
  if (!before) return 'new'
  const diff = now - before
  if (Math.abs(diff) < 50) return 'same'
  return `${rupees(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'}`
}

function SummaryView({ s, txns, lastMonth }: { s: Summary; txns: Txn[]; lastMonth: Txn[] }) {
  const { view, open } = useNav()
  const empty = s.spent_paise === 0 && s.categories.length === 0 && s.to_confirm.amount_paise === 0
  if (empty) return <Empty>Nothing recorded in {monthLabel(s.month)}.</Empty>
  const toDate = s.month === currentMonth()
  const base = spentByCategory(comparable(lastMonth, toDate ? today() : null))
  const baseTotal = [...base.values()].reduce((sum, n) => sum + n, 0)
  const parts = [...s.categories].sort((a, b) => b.amount_paise - a.amount_paise)
  return (
    <>
      {s.stale && <Notice>Totals are being updated.</Notice>}
      <div className="px-4 pt-5 text-center">
        <p className="text-sm text-muted">Net</p>
        <p className="mt-1 text-4xl font-semibold tracking-tight whitespace-nowrap tabular-nums">{rupees(s.net_paise)}</p>
        <p className="mt-2 text-sm text-muted tabular-nums">
          <span className="whitespace-nowrap">Spent {rupees(s.spent_paise)}</span> ·{' '}
          <span className="whitespace-nowrap">Paid back {rupees(s.paid_back_paise)}</span>
        </p>
        {lastMonth.length > 0 && <p className="mt-1 text-sm text-muted">{comparison(s.spent_paise - baseTotal, s.month, toDate)}</p>}
      </div>
      {s.to_confirm.amount_paise > 0 && (
        <Section>
          <RowButton onClick={() => navigate({ ...HOME, tab: 'todo', month: view.month }, 'push')}>
            <span className="min-w-0 flex-1">
              To confirm: <Money paise={s.to_confirm.amount_paise} /> from {s.to_confirm.senders}{' '}
              {s.to_confirm.senders === 1 ? 'person' : 'people'}
            </span>
            <Icon name="chevron-right" className="text-muted" />
          </RowButton>
        </Section>
      )}
      <Section title="Spent by category" aside={lastMonth.length > 0 && <span className="shrink-0 text-xs text-muted">vs last month</span>}>
        {parts.length === 0 && <Empty>No spending this month.</Empty>}
        {parts.map((p) => (
          <RowButton key={p.slug} onClick={() => open({ path: ['category', p.slug] })}>
            <Icon name={categoryIcon(p.slug)} className="text-muted" />
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <Money paise={p.amount_paise} />
                <span className="w-9 shrink-0 text-right text-sm text-muted tabular-nums">{percentOf(p.amount_paise, s.spent_paise)}</span>
              </span>
              <span className="mt-1.5 flex items-center gap-3">
                <Bar share={s.spent_paise > 0 ? p.amount_paise / s.spent_paise : 0} />
                {lastMonth.length > 0 && (
                  <span className="shrink-0 text-xs whitespace-nowrap text-muted tabular-nums">{change(p.amount_paise, base.get(p.slug) ?? 0)}</span>
                )}
              </span>
            </span>
          </RowButton>
        ))}
      </Section>
      {txns.length > 0 && <TxnList txns={txns.slice(0, 5)} title="Recent" />}
      {s.counts.not_counted_yet > 0 && (
        <p className="px-4 pt-4 pb-2 text-center text-xs text-muted">
          {s.counts.not_counted_yet} {s.counts.not_counted_yet === 1 ? 'message' : 'messages'} not counted yet
        </p>
      )}
    </>
  )
}

/** One category of the month: merchants, or for People a ledger; `name` opens one of them. */
export function CategoryDetail({ slug, name }: { slug: string; name?: string }) {
  const { api } = useApp()
  const { month, back } = useNav()
  const [load, retry] = useMonthTxns(month)
  const [cats] = useLoad(() => api.categories(), ['categories'])
  const title = (cats.status === 'ready' && cats.data.find((c) => c.slug === slug)?.name) || 'Category'
  const people = slug === 'people'
  return (
    <>
      <Header title={name ?? title} back={back} />
      <p className="px-4 text-sm text-muted">{name !== undefined ? `${title} · ` : ''}{monthLabel(month)}</p>
      <Loaded load={load} retry={retry}>
        {(txns) => {
          if (people && name !== undefined) return <PersonView name={name} txns={txns.filter((t) => isPersonTxn(t) && nameOf(t) === name)} />
          if (people) return <Ledger txns={txns} />
          const mine = txns.filter((t) => t.category === slug)
          if (name !== undefined) return <TxnList txns={mine.filter((t) => nameOf(t) === name)} />
          return <Merchants txns={mine} slug={slug} />
        }}
      </Loaded>
    </>
  )
}

function Merchants({ txns, slug }: { txns: Txn[]; slug: string }) {
  const { open } = useNav()
  const rows = byName(txns)
  if (!rows.length) return <Empty>Nothing in this category this month.</Empty>
  return (
    <Section title="Paid to">
      {rows.map((g) => (
        <RowButton key={g.name} onClick={() => open({ path: ['category', slug, g.name] })}>
          <span className="min-w-0 flex-1">
            <span className="block truncate">{g.name}</span>
            <span className="text-xs text-muted">{g.count} {g.count === 1 ? 'payment' : 'payments'}</span>
          </span>
          <Money paise={g.total} />
        </RowButton>
      ))}
    </Section>
  )
}

/** People: what went to each person and what came back. Money in is not part of Spent. */
function Ledger({ txns }: { txns: Txn[] }) {
  const { open } = useNav()
  const rows = ledger(txns)
  if (!rows.length) return <Empty>No money to or from people this month.</Empty>
  return (
    <>
      <Section title="Sent and got back">
        {rows.map((p) => (
          <RowButton key={p.name} onClick={() => open({ path: ['category', 'people', p.name] })}>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="shrink-0 text-xs text-muted">Net</span>
                <Money paise={p.sent - p.got} />
              </span>
              <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted tabular-nums">
                <span className="whitespace-nowrap">Sent {rupees(p.sent)}</span>
                <span className="whitespace-nowrap">Got back {rupees(p.got)}</span>
              </span>
            </span>
          </RowButton>
        ))}
      </Section>
      <p className="px-4 pt-3 text-xs text-muted">Got back is money in from them. It is not part of Spent; it counts as Paid back once confirmed.</p>
    </>
  )
}

function PersonView({ name, txns }: { name: string; txns: Txn[] }) {
  const p = ledger(txns)[0] ?? { name, sent: 0, got: 0 }
  return (
    <>
      <div className="mx-4 mt-3 flex flex-wrap gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm tabular-nums">
        <Figure term="Sent" paise={p.sent} />
        <Figure term="Got back" paise={p.got} credit={p.got > 0} />
        <Figure term="Net" paise={p.sent - p.got} />
      </div>
      {p.got > 0 && <p className="px-4 pt-2 text-xs text-muted">Money in from {name} is marked +. It is not part of Spent.</p>}
      <TxnList txns={txns} empty={`Nothing with ${name} this month.`} />
    </>
  )
}
