import { allTransactions, spentEffect } from '../api/client.ts'
import type { Summary, Txn } from '../api/types.ts'
import { currentMonth, monthLabel } from '../lib/dates.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { useApp, useLoad } from '../state.tsx'
import { Bar, Empty, Header, Loaded, Money, MonthSwitcher, Notice, RowButton, Section } from '../ui.tsx'
import { nameOf } from './common.ts'
import { TxnList } from './Transactions.tsx'

export function Home() {
  const { api, month, setMonth, go } = useApp()
  const [load, retry] = useLoad(() => api.summary(month), [month])
  return (
    <>
      <div className="pt-2">
        <MonthSwitcher month={month} setMonth={setMonth} latest={currentMonth()} />
      </div>
      <Loaded load={load} retry={retry}>
        {(s) => <SummaryView s={s} go={go} />}
      </Loaded>
    </>
  )
}

function SummaryView({ s, go }: { s: Summary; go: (path: string) => void }) {
  const empty = s.spent_paise === 0 && s.categories.length === 0 && s.to_confirm.amount_paise === 0
  if (empty) return <Empty>Nothing recorded in {monthLabel(s.month)}.</Empty>
  const parts = [...s.categories].sort((a, b) => b.amount_paise - a.amount_paise)
  const top = Math.max(1, ...parts.map((p) => p.amount_paise))
  return (
    <>
      {s.stale && <Notice>Totals are being updated.</Notice>}
      <div className="px-4 pt-6 text-center">
        <p className="text-sm text-muted">Net</p>
        <p className="mt-1 text-4xl font-semibold tracking-tight tabular-nums">{rupees(s.net_paise)}</p>
        <p className="mt-2 text-sm text-muted tabular-nums">
          Spent {rupees(s.spent_paise)} · Paid back {rupees(s.paid_back_paise)}
        </p>
      </div>
      {s.to_confirm.amount_paise > 0 && (
        <Section>
          <RowButton onClick={() => go('todo')}>
            <span className="flex-1">
              To confirm: <Money paise={s.to_confirm.amount_paise} /> from {s.to_confirm.senders}{' '}
              {s.to_confirm.senders === 1 ? 'person' : 'people'}
            </span>
            <span aria-hidden="true" className="text-muted">›</span>
          </RowButton>
        </Section>
      )}
      <Section title="Spent by category">
        {parts.length === 0 && <Empty>No spending this month.</Empty>}
        {parts.map((p) => (
          <RowButton key={p.slug} onClick={() => go(`home/category/${p.slug}`)}>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline justify-between gap-3">
                <span className="truncate">{p.name}</span>
                <span className="shrink-0 tabular-nums">
                  {rupees(p.amount_paise)}
                  <span className="ml-2 inline-block w-10 text-right text-sm text-muted">{percentOf(p.amount_paise, s.spent_paise)}</span>
                </span>
              </span>
              <Bar share={p.amount_paise / top} />
            </span>
          </RowButton>
        ))}
      </Section>
      {s.counts.not_counted_yet > 0 && (
        <p className="px-4 pt-4 pb-2 text-center text-xs text-muted">
          {s.counts.not_counted_yet} {s.counts.not_counted_yet === 1 ? 'message' : 'messages'} not counted yet
        </p>
      )}
    </>
  )
}

/** Recipients or merchants of one category, biggest first; tap one for its transactions. */
export function CategoryDetail({ slug, name }: { slug: string; name?: string }) {
  const { api, month, go } = useApp()
  const [load, retry] = useLoad(() => allTransactions(api, { month, category: slug }), [month, slug])
  const title = load.status === 'ready' && load.data[0] ? load.data[0].category_name : 'Category'
  if (name !== undefined) {
    return (
      <>
        <Header title={name} back={() => go(`home/category/${slug}`)} />
        <p className="px-4 text-sm text-muted">{title} · {monthLabel(month)}</p>
        <Loaded load={load} retry={retry}>
          {(txns) => <TxnList txns={txns.filter((t) => nameOf(t) === name)} />}
        </Loaded>
      </>
    )
  }
  return (
    <>
      <Header title={title} back={() => go('home')} />
      <p className="px-4 text-sm text-muted">{monthLabel(month)}</p>
      <Loaded load={load} retry={retry}>
        {(txns) => <Groups txns={txns} slug={slug} go={go} />}
      </Loaded>
    </>
  )
}

function Groups({ txns, slug, go }: { txns: Txn[]; slug: string; go: (path: string) => void }) {
  const groups = new Map<string, { total: number; count: number }>()
  for (const t of txns) {
    const g = groups.get(nameOf(t)) ?? { total: 0, count: 0 }
    groups.set(nameOf(t), { total: g.total + spentEffect(t), count: g.count + 1 })
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].total - a[1].total)
  if (!rows.length) return <Empty>Nothing in this category this month.</Empty>
  return (
    <Section title={slug === 'people' ? 'Sent to' : 'Paid to'}>
      {rows.map(([who, g]) => (
        <RowButton key={who} onClick={() => go(`home/category/${slug}/${encodeURIComponent(who)}`)}>
          <span className="min-w-0 flex-1">
            <span className="block truncate">{who}</span>
            <span className="text-xs text-muted">{g.count} {g.count === 1 ? 'payment' : 'payments'}</span>
          </span>
          <Money paise={g.total} />
        </RowButton>
      ))}
    </Section>
  )
}
