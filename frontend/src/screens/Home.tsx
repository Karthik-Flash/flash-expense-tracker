import { useState } from 'react'

import type { Summary, Txn } from '../api/types.ts'
import { Wordmark } from '../brand.tsx'
import { currentMonth, monthLabel } from '../lib/dates.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { HOME } from '../view.ts'
import { joinLoads, navigate, useApp, useLoad, useMonthTxns, useNav } from '../state.tsx'
import { Bar, CategoryTile, Empty, Figure, Header, Icon, Loaded, Money, MonthSwitcher, Notice, RowButton, Section } from '../ui.tsx'
import { nameOf } from './common.ts'
import { byName, isPersonTxn, ledger, personKey } from './derive.ts'
import { Ring } from './Ring.tsx'
import { TxnList } from './Transactions.tsx'

export function Home() {
  const { api, signOut } = useApp()
  const { month, replace } = useNav()
  const [summary, retrySummary] = useLoad(() => api.summary(month), ['summary', month])
  const [txns, retryTxns] = useMonthTxns(month)
  return (
    <>
      <header className="flex min-h-14 items-center justify-between gap-2 px-4 pt-2">
        <h1>
          <Wordmark height={22} />
        </h1>
        <button type="button" onClick={signOut} className="-mr-3 flex size-11 shrink-0 items-center justify-center rounded-lg text-muted" aria-label="Sign out">
          <Icon name="log-out" />
        </button>
      </header>
      <MonthSwitcher month={month} setMonth={(m) => replace({ month: m })} latest={currentMonth()} />
      <Loaded
        load={joinLoads(summary, txns)}
        retry={() => {
          retrySummary()
          retryTxns()
        }}
      >
        {([s, mine]) => <SummaryView s={s} txns={mine} />}
      </Loaded>
    </>
  )
}

/** "Spent ₹1,240 less than this time last month". Past months compare whole months. */
function comparison(diff: number, before: Summary['previous']): string {
  const than = before.whole ? `in ${monthLabel(before.month)}` : 'this time last month'
  if (Math.abs(diff) < 50) return `Spent the same as ${than}`
  return `Spent ${rupees(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'} than ${than}`
}

function change(now: number, before: number): string {
  if (!before) return 'new'
  const diff = now - before
  if (Math.abs(diff) < 50) return 'same'
  return `${rupees(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'}`
}

type Mode = 'list' | 'chart'
const MODE_KEY = 'flash-category-view'

function savedMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === 'chart' ? 'chart' : 'list'
  } catch {
    return 'list'
  }
}

/** List | Chart. List is the default; the choice is remembered on this device. */
function ViewSwitch({ value, onChange }: { value: Mode; onChange: (m: Mode) => void }) {
  return (
    <div role="group" aria-label="Show categories as" className="flex shrink-0 rounded-lg border border-line bg-surface p-0.5 text-sm">
      {(['list', 'chart'] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={value === m}
          onClick={() => onChange(m)}
          className={`min-h-9 min-w-14 rounded-md px-3 ${value === m ? 'bg-press font-medium text-ink' : 'text-muted'}`}
        >
          {m === 'list' ? 'List' : 'Chart'}
        </button>
      ))}
    </div>
  )
}

function SummaryView({ s, txns }: { s: Summary; txns: Txn[] }) {
  const { view, open } = useNav()
  const [mode, pick] = useState<Mode>(savedMode)
  const setMode = (m: Mode) => {
    pick(m)
    try {
      localStorage.setItem(MODE_KEY, m)
    } catch {
      // Private mode: the choice lasts for this page.
    }
  }
  const empty = s.spent_paise === 0 && s.categories.length === 0 && s.to_confirm.amount_paise === 0
  if (empty) return <Empty>Nothing recorded in {monthLabel(s.month)}.</Empty>
  const base = new Map(s.previous.categories.map((c) => [c.slug, c.amount_paise]))
  const compared = s.previous.categories.length > 0
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
        {compared && <p className="mt-1 text-sm text-muted">{comparison(s.spent_paise - s.previous.spent_paise, s.previous)}</p>}
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
      <div className="mt-4 flex items-center justify-between gap-3 px-4">
        <h2 className="truncate text-sm font-medium text-muted">Spent by category</h2>
        {parts.length > 0 && <ViewSwitch value={mode} onChange={setMode} />}
      </div>
      {parts.length === 0 && <Empty>No spending this month.</Empty>}
      {parts.length > 0 && mode === 'chart' && (
        <Ring parts={parts} spent={s.spent_paise} onOpen={(slug) => open({ path: ['category', slug] })} onOther={() => setMode('list')} />
      )}
      {parts.length > 0 && mode === 'list' && (
        <>
          {compared && <p className="px-4 pt-1 text-xs text-muted">Change against {s.previous.whole ? monthLabel(s.previous.month) : 'this time last month'}</p>}
          <Section>
            {parts.map((p) => (
              <RowButton key={p.slug} onClick={() => open({ path: ['category', p.slug] })}>
                <CategoryTile slug={p.slug} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-3">
                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                    <Money paise={p.amount_paise} />
                    <span className="w-9 shrink-0 text-right text-sm text-muted tabular-nums">{percentOf(p.amount_paise, s.spent_paise)}</span>
                  </span>
                  <span className="mt-1.5 flex items-center gap-3">
                    <Bar slug={p.slug} share={s.spent_paise > 0 ? p.amount_paise / s.spent_paise : 0} />
                    {compared && (
                      <span className="shrink-0 text-xs whitespace-nowrap text-muted tabular-nums">{change(p.amount_paise, base.get(p.slug) ?? 0)}</span>
                    )}
                  </span>
                </span>
              </RowButton>
            ))}
          </Section>
        </>
      )}
      {txns.length > 0 && <TxnList txns={txns.slice(0, 5)} title="Recent" />}
      {s.counts.not_counted_yet > 0 && (
        <p className="px-4 pt-4 pb-2 text-center text-xs text-muted">
          {s.counts.not_counted_yet} {s.counts.not_counted_yet === 1 ? 'message' : 'messages'} not counted yet
        </p>
      )}
    </>
  )
}

/**
 * One category of the month: merchants, or for People a ledger. `name` opens one of them:
 * a merchant name, or for People a person key (derive.ts personKey).
 */
export function CategoryDetail({ slug, name }: { slug: string; name?: string }) {
  const { api } = useApp()
  const { month, back } = useNav()
  const [load, retry] = useMonthTxns(month)
  const [cats] = useLoad(() => api.categories(), ['categories'])
  const title = (cats.status === 'ready' && cats.data.find((c) => c.slug === slug)?.name) || 'Category'
  const people = slug === 'people'
  const person = people && name !== undefined && load.status === 'ready' ? load.data.find((t) => personKey(t) === name) : undefined
  const heading = name === undefined ? title : people ? (person ? nameOf(person) : 'Person') : name
  return (
    <>
      <Header title={heading} back={back} lead={<CategoryTile slug={slug} />} />
      <p className="px-4 text-sm text-muted">{name !== undefined ? `${title} · ` : ''}{monthLabel(month)}</p>
      <Loaded load={load} retry={retry}>
        {(txns) => {
          if (people && name !== undefined) return <PersonView name={heading} txns={txns.filter((t) => isPersonTxn(t) && personKey(t) === name)} />
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
          <RowButton key={p.key} onClick={() => open({ path: ['category', 'people', p.key] })}>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="shrink-0 text-xs text-muted">Net</span>
                <Money paise={p.sent - p.got} />
              </span>
              <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted tabular-nums">
                <span className="whitespace-nowrap">Sent {rupees(p.sent)}</span>
                <span className="whitespace-nowrap">Got back {rupees(p.got)}</span>
                {p.toConfirm > 0 && <span className="whitespace-nowrap">To confirm {rupees(p.toConfirm)}</span>}
              </span>
            </span>
          </RowButton>
        ))}
      </Section>
      <p className="px-4 pt-3 text-xs text-muted">
        Got back is money in from them that you confirmed: it counts as Paid back. Money in is never part of Spent.
      </p>
    </>
  )
}

function PersonView({ name, txns }: { name: string; txns: Txn[] }) {
  const p = ledger(txns)[0] ?? { sent: 0, got: 0, toConfirm: 0 }
  return (
    <>
      <div className="mx-4 mt-3 flex flex-wrap gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm tabular-nums">
        <Figure term="Sent" paise={p.sent} />
        <Figure term="Got back" paise={p.got} credit={p.got > 0} />
        {p.toConfirm > 0 && <Figure term="To confirm" paise={p.toConfirm} credit />}
        <Figure term="Net" paise={p.sent - p.got} />
      </div>
      {p.got + p.toConfirm > 0 && <p className="px-4 pt-2 text-xs text-muted">Money in from {name} is marked +. It is not part of Spent.</p>}
      <TxnList txns={txns} empty={`Nothing with ${name} this month.`} />
    </>
  )
}
