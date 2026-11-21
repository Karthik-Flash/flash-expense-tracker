import { useEffect, useState } from 'react'

import type { Merchant, MonthData, PersonRow, Summary, Txn } from '../api/types.ts'
import { Wordmark } from '../brand.tsx'
import { shownName, useOutbox } from '../data/outbox.ts'
import { noteHomeDrawn, usePeople, useSnapshot } from '../data/store.ts'
import { currentMonth, monthLabel } from '../lib/dates.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { HOME } from '../view.ts'
import { navigate, useApp, useNav } from '../state.tsx'
import { Bar, CategoryTile, Empty, Figure, Freshness, Header, Icon, Loaded, Money, MonthSwitcher, Notice, RowButton, Section } from '../ui.tsx'
import { nameOf } from './common.ts'
import { identifiersText, isPersonTxn, monthData, monthTxns, personKey } from './derive.ts'
import { Ring } from './Ring.tsx'
import { TxnList } from './Transactions.tsx'

export function Home() {
  const { signOut } = useApp()
  const { month, replace, open } = useNav()
  const [load, retry] = useSnapshot()
  return (
    <>
      <header className="flex min-h-14 items-center justify-between gap-2 px-4 pt-2">
        <h1>
          <Wordmark height={22} />
        </h1>
        <div className="flex min-w-0 items-center gap-1">
          <button type="button" onClick={() => open({ sheet: 'speed' })} aria-label={`${__VERSION_LINE__}: speed and sync details`} className="min-h-11 min-w-0 text-right text-xs text-muted">
            {__VERSION_LINE__}
          </button>
          <button type="button" onClick={signOut} className="-mr-3 flex size-11 shrink-0 items-center justify-center rounded-lg text-muted" aria-label="Sign out">
            <Icon name="log-out" />
          </button>
        </div>
      </header>
      <MonthSwitcher month={month} setMonth={(m) => replace({ month: m })} latest={currentMonth()} />
      <Freshness />
      <Loaded load={load} retry={retry}>
        {(s) => {
          const m = monthData(s, month)
          return m ? <SummaryView m={m} txns={monthTxns(s, month)} /> : <Empty>Nothing recorded in {monthLabel(month)}.</Empty>
        }}
      </Loaded>
      {load.status === 'ready' && <Drawn />}
    </>
  )
}

/** Tells the launch timing that Home is on screen (D-090). */
function Drawn() {
  useEffect(noteHomeDrawn, [])
  return null
}

/** "Spent ₹1,240 less than this time last month". Past months compare whole months. */
function comparison(diff: number, before: Summary['previous']): string {
  const than = before.whole ? `in ${monthLabel(before.month)}` : 'this time last month'
  if (Math.abs(diff) < 50) return `Spent the same as ${than}`
  return `Spent ${rupees(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'} than ${than}`
}

/** A category against last month: the server's difference, "new" when it had none then. */
function change(diff: number, before: number): string {
  if (!before) return 'new'
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
          className={`min-h-11 min-w-14 rounded-md px-3 ${value === m ? 'bg-press font-medium text-ink' : 'text-muted'}`}
        >
          {m === 'list' ? 'List' : 'Chart'}
        </button>
      ))}
    </div>
  )
}

function SummaryView({ m, txns }: { m: MonthData; txns: Txn[] }) {
  const s: Summary = m.summary
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
        {/* Fits a 360 px screen at 200 % text: never past 12vw (4H). */}
        <p className="mt-1 text-[min(2.25rem,12vw)] font-semibold tracking-tight whitespace-nowrap tabular-nums">{rupees(s.net_paise)}</p>
        <p className="mt-2 text-sm text-muted tabular-nums">
          <span className="whitespace-nowrap">Spent {rupees(s.spent_paise)}</span> ·{' '}
          <span className="whitespace-nowrap">Paid back {rupees(s.paid_back_paise)}</span>
        </p>
        {compared && <p className="mt-1 text-sm text-muted">{comparison(m.changes.spent_paise, s.previous)}</p>}
      </div>
      {s.to_confirm.amount_paise > 0 && (
        <Section>
          <RowButton onClick={() => navigate({ ...HOME, tab: 'todo', month: view.month }, 'push')}>
            <span className="min-w-[min(6rem,35vw)] flex-1">
              To confirm: <Money paise={s.to_confirm.amount_paise} /> from {s.to_confirm.senders}{' '}
              {s.to_confirm.senders === 1 ? 'person' : 'people'}
            </span>
            <Icon name="chevron-right" className="text-muted" />
          </RowButton>
        </Section>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4">
        <h2 className="text-sm font-medium text-muted">Spent by category</h2>
        {parts.length > 0 && <ViewSwitch value={mode} onChange={setMode} />}
      </div>
      {parts.length === 0 && <Empty>No spending this month.</Empty>}
      {parts.length > 0 && mode === 'chart' && (
        <Ring chart={m.chart} spent={s.spent_paise} onOpen={(slug) => open({ path: ['category', slug] })} onOther={() => setMode('list')} />
      )}
      {parts.length > 0 && mode === 'list' && (
        <>
          {compared && <p className="px-4 pt-1 text-xs text-muted">Change against {s.previous.whole ? monthLabel(s.previous.month) : 'this time last month'}</p>}
          <Section>
            {parts.map((p) => (
              <RowButton key={p.slug} onClick={() => open({ path: ['category', p.slug] })}>
                <CategoryTile slug={p.slug} />
                <span className="min-w-[min(6rem,35vw)] flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-3">
                    <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{p.name}</span>
                    <Money paise={p.amount_paise} />
                    <span className="w-9 shrink-0 text-right text-sm text-muted tabular-nums">{percentOf(p.amount_paise, s.spent_paise)}</span>
                  </span>
                  <span className="mt-1.5 flex items-center gap-3">
                    <Bar slug={p.slug} share={s.spent_paise > 0 ? p.amount_paise / s.spent_paise : 0} />
                    {compared && (
                      <span className="shrink-0 text-xs whitespace-nowrap text-muted tabular-nums">{change(m.changes.categories[p.slug] ?? 0, base.get(p.slug) ?? 0)}</span>
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
  const { month, back } = useNav()
  const [load, retry] = useSnapshot()
  const s = load.status === 'ready' ? load.data : null
  const title = s?.categories.find((c) => c.slug === slug)?.name || 'Category'
  const people = slug === 'people'
  const m = s ? monthData(s, month) : undefined
  const person = people && name !== undefined ? m?.people.find((p) => p.key === name) : undefined
  const heading = name === undefined ? title : people ? (person?.name ?? 'Person') : name
  return (
    <>
      <Header title={heading} back={back} lead={<CategoryTile slug={slug} />} />
      <p className="px-4 text-sm text-muted">{name !== undefined ? `${title} · ` : ''}{monthLabel(month)}</p>
      <Loaded load={load} retry={retry}>
        {(snap) => {
          const txns = monthTxns(snap, month)
          if (people && name !== undefined) {
            return <PersonView name={heading} row={person} txns={txns.filter((t) => isPersonTxn(t) && personKey(t) === name)} />
          }
          if (people) return <Ledger rows={m?.people ?? []} />
          if (name !== undefined) return <TxnList txns={txns.filter((t) => t.category === slug && nameOf(t) === name)} />
          return <Merchants rows={m?.merchants[slug] ?? []} slug={slug} />
        }}
      </Loaded>
    </>
  )
}

function Merchants({ rows, slug }: { rows: Merchant[]; slug: string }) {
  const { open } = useNav()
  if (!rows.length) return <Empty>Nothing in this category this month.</Empty>
  return (
    <Section title="Paid to">
      {rows.map((g) => (
        <RowButton key={g.name} onClick={() => open({ path: ['category', slug, g.name] })}>
          <span className="min-w-[min(6rem,35vw)] flex-1">
            <span className="block truncate">{g.name}</span>
            <span className="text-xs text-muted">{g.count} {g.count === 1 ? 'payment' : 'payments'}</span>
          </span>
          <Money paise={g.total_paise} />
        </RowButton>
      ))}
    </Section>
  )
}

/** People: what went to each person and what came back. Money in is not part of Spent. */
function Ledger({ rows }: { rows: PersonRow[] }) {
  const { open } = useNav()
  const { find } = usePeople()
  const { ops } = useOutbox()
  if (!rows.length) return <Empty>No money to or from people this month.</Empty>
  return (
    <>
      <Section title="Sent and got back">
        {rows.map((p) => (
          // A row opens the person sheet: name, identifiers, Rename, Separate (4E).
          <RowButton key={p.key} onClick={() => open({ person: p.key })}>
            <span className="min-w-[min(6rem,35vw)] flex-1">
              <span className="flex flex-wrap items-baseline gap-x-3">
                <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{find(p.key) ? shownName(ops, find(p.key)!, p.name) : p.name}</span>
                <span className="shrink-0 text-xs text-muted">Net</span>
                <Money paise={p.net_paise} />
              </span>
              {identifiersText(find(p.key)) && <span className="block truncate text-xs text-muted">{identifiersText(find(p.key))}</span>}
              <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted tabular-nums">
                <span className="whitespace-nowrap">Sent {rupees(p.sent_paise)}</span>
                <span className="whitespace-nowrap">Got back {rupees(p.got_back_paise)}</span>
                {p.to_confirm_paise > 0 && <span className="whitespace-nowrap">To confirm {rupees(p.to_confirm_paise)}</span>}
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

function PersonView({ name, row, txns }: { name: string; row: PersonRow | undefined; txns: Txn[] }) {
  const p = row ?? { sent_paise: 0, got_back_paise: 0, to_confirm_paise: 0, net_paise: 0 }
  return (
    <>
      <div className="mx-4 mt-3 flex flex-wrap gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm tabular-nums">
        <Figure term="Sent" paise={p.sent_paise} />
        <Figure term="Got back" paise={p.got_back_paise} credit={p.got_back_paise > 0} />
        {p.to_confirm_paise > 0 && <Figure term="To confirm" paise={p.to_confirm_paise} credit />}
        <Figure term="Net" paise={p.net_paise} />
      </div>
      {(p.got_back_paise > 0 || p.to_confirm_paise > 0) && <p className="px-4 pt-2 text-xs text-muted">Money in from {name} is marked +. It is not part of Spent.</p>}
      <TxnList txns={txns} empty={`Nothing with ${name} this month.`} />
    </>
  )
}
