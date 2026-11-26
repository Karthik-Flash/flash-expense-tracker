// Analytics (premium B, D-148): the Insights charts. Every number comes from GET /analytics;
// this file only lays it out. Hand-drawn SVG, no chart package. A bar opens that month's
// Transactions; a category, a merchant or a person opens their payments.

import { useEffect, useState } from 'react'

import type { Analytics as Data } from '../api/types.ts'
import { ApiError } from '../api/client.ts'
import { onReset, type Load } from '../data/store.ts'
import { SPANS, spanOf, type Span } from '../exportRange.ts'
import { currentMonth, dayLabel, monthLabel } from '../lib/dates.ts'
import { groupIndian, rupees } from '../lib/money.ts'
import { seePayments, seeTransactions, useApp } from '../state.tsx'
import { CategoryTile, Empty, Loaded, Money, RowButton, Section } from '../ui.tsx'
import { catColor } from './common.ts'

const SLOW_MS = 3000
/** The last answer per range, with its ETag: shown at once, then checked (a 304 keeps it). */
const cache = new Map<string, { etag: string; data: Data }>()
// 5G-F: another login on this device must never see these figures (sign-out, D-158).
onReset(() => cache.clear())

const percent = (bp: number) => (bp > 0 && bp < 100 ? '<1%' : `${Math.round(bp / 100)}%`)
const short = (month: string) => monthLabel(month).slice(0, 3)

function useAnalytics(start: string, end: string): [Load<Data>, () => void] {
  const { api } = useApp()
  const key = `${start}|${end}`
  const [loads, setLoads] = useState<Record<string, Load<Data>>>({})
  const [ask, setAsk] = useState(0)
  const held = cache.get(key)
  const load: Load<Data> = loads[key] ?? (held ? { status: 'ready', data: held.data } : { status: 'loading', slow: false })
  useEffect(() => {
    let live = true
    const old = cache.get(key)
    const put = (l: Load<Data>) => live && setLoads((all) => ({ ...all, [key]: l }))
    const slow = setTimeout(() => !old && put({ status: 'loading', slow: true }), SLOW_MS)
    api
      .analytics(start, end, old?.etag ?? null)
      .then((answer) => {
        if (answer.status === 200) cache.set(key, { etag: answer.etag, data: answer.analytics })
        const data = answer.status === 200 ? answer.analytics : old?.data
        if (data) put({ status: 'ready', data })
      })
      .catch((e: unknown) => {
        if (old) return // an old answer stays on screen when offline
        const message = e instanceof ApiError && e.status === 0 ? 'You are offline. Analytics needs the server; try again when online.' : e instanceof Error ? e.message : 'Try again.'
        put({ status: 'error', message })
      })
      .finally(() => clearTimeout(slow))
    return () => {
      live = false
      clearTimeout(slow)
    }
  }, [api, key, start, end, ask])
  const retry = () => {
    setLoads((all) => ({ ...all, [key]: { status: 'loading', slow: false } }))
    setAsk((n) => n + 1)
  }
  return [load, retry]
}

export function AnalyticsSection() {
  const [span, setSpan] = useState<Span>('6')
  const now = currentMonth()
  const [custom, setCustom] = useState<[string, string]>([now, now])
  const [start, end] = spanOf(span, custom)
  const [load, retry] = useAnalytics(start, end)
  const field = 'min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 text-sm text-ink'
  return (
    <>
      <div className="mt-2 space-y-2 px-4">
        <label className="block text-xs text-muted">
          Period
          <select className={`${field} mt-1 w-full`} value={span} onChange={(e) => setSpan(e.target.value as Span)}>
            {SPANS.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>
        {span === 'custom' && (
          <div className="flex flex-wrap gap-2">
            <label className="flex min-w-36 flex-1 flex-col text-xs text-muted">
              From
              <input type="month" className={field} value={custom[0]} max={now} onChange={(e) => e.target.value && setCustom([e.target.value, custom[1]])} />
            </label>
            <label className="flex min-w-36 flex-1 flex-col text-xs text-muted">
              To
              <input type="month" className={field} value={custom[1]} max={now} onChange={(e) => e.target.value && setCustom([custom[0], e.target.value])} />
            </label>
          </div>
        )}
      </div>
      <Loaded load={load} retry={retry}>
        {(a) => (a.stats.payments === 0 ? <Empty>No payments from {monthLabel(start)} to {monthLabel(end)}.</Empty> : <Charts a={a} />)}
      </Loaded>
    </>
  )
}

function Charts({ a }: { a: Data }) {
  const last = a.end
  return (
    <>
      <MonthBars a={a} />
      <Categories a={a} />
      {a.moves && (a.moves.up.length > 0 || a.moves.down.length > 0) && (
        <Section title={`${monthLabel(a.moves.to)} against ${monthLabel(a.moves.from)}`}>
          {[...a.moves.up, ...a.moves.down].map((m) => (
            <RowButton key={m.slug} onClick={() => seeTransactions({ month: a.moves!.to, category: m.slug })} label={`${m.name}: ${rupees(m.from_paise)} to ${rupees(m.to_paise)}`}>
              <CategoryTile slug={m.slug} />
              <span className="min-w-0 flex-1 wrap-break-word">{m.name}</span>
              <span className="shrink-0 text-sm text-muted tabular-nums">{m.change_paise > 0 ? 'up' : 'down'} {rupees(Math.abs(m.change_paise))}</span>
            </RowButton>
          ))}
        </Section>
      )}
      {a.merchants.length > 0 && (
        <Section title="Top places">
          {a.merchants.map((m) => (
            <RowButton key={m.name} onClick={() => seeTransactions({ month: last, q: m.name })}>
              <Named name={m.name} detail={`${m.count} ${m.count === 1 ? 'payment' : 'payments'} · ${percent(m.share_bp)} of Spent`} />
              <Money paise={m.total_paise} />
            </RowButton>
          ))}
        </Section>
      )}
      {a.people.length > 0 && (
        <Section title="Top people">
          {a.people.map((p) => (
            <RowButton key={p.key} onClick={() => (p.key.startsWith('name:') ? seeTransactions({ month: last, q: p.name }) : seePayments(p.key))}>
              <Named name={p.name} detail={`${p.count} ${p.count === 1 ? 'payment' : 'payments'}${p.got_back_paise ? ` · got back ${rupees(p.got_back_paise)}` : ''}`} />
              <Money paise={p.sent_paise} />
            </RowButton>
          ))}
        </Section>
      )}
      <Stats a={a} />
    </>
  )
}

function Named({ name, detail }: { name: string; detail: string }) {
  return (
    <span className="min-w-[min(8rem,40vw)] flex-1">
      <span className="block wrap-break-word">{name}</span>
      <span className="block text-xs text-muted">{detail}</span>
    </span>
  )
}

/** Spent per month as bars, then a table with Invested, Paid back and Net beside it. */
function MonthBars({ a }: { a: Data }) {
  const top = Math.max(1, ...a.months.map((m) => m.spent_paise))
  const W = 24
  const H = 96
  const width = a.months.length * W
  const every = a.months.length > 6 ? 2 : 1 // month names every other bar on a long range
  return (
    <Section title="Spent per month">
      <div className="px-4 pt-3">
        <svg viewBox={`0 0 ${width} ${H + 16}`} className="block h-32 w-full" role="group" aria-label="Spent per month">
          <line x1="0" x2={width} y1={H} y2={H} stroke="var(--color-line)" strokeWidth="1" />
          {a.months.map((m, i) => {
            const h = m.spent_paise > 0 ? Math.max(2, (m.spent_paise / top) * (H - 6)) : 0
            const label = `${monthLabel(m.month)}: Spent ${rupees(m.spent_paise)}`
            return (
              <g key={m.month} role="button" tabIndex={0} aria-label={label} className="cursor-pointer outline-none focus-visible:opacity-70" onClick={() => seeTransactions({ month: m.month })} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && seeTransactions({ month: m.month })}>
                <title>{label}</title>
                <rect x={i * W} y="0" width={W} height={H + 16} fill="transparent" />
                <rect x={i * W + 5} y={H - h} width={W - 10} height={h} rx="2" fill="var(--color-accent)" />
                {i % every === (a.months.length - 1) % every && (
                  <text x={i * W + W / 2} y={H + 12} textAnchor="middle" fontSize="8" fill="var(--color-muted)">{short(m.month)}</text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
      <div className="overflow-x-auto px-4 pb-3">
        <table className="w-full text-right text-xs tabular-nums">
          <caption className="sr-only">Each month: Spent, Invested, Paid back and Net</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-1 text-left font-normal">Month</th>
              <th scope="col" className="py-1 font-normal">Spent</th>
              <th scope="col" className="py-1 font-normal">Invested</th>
              <th scope="col" className="py-1 font-normal">Paid back</th>
              <th scope="col" className="py-1 font-normal">Net</th>
            </tr>
          </thead>
          <tbody>
            {[...a.months].reverse().map((m) => (
              <tr key={m.month} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-2 text-left font-normal whitespace-nowrap">{monthLabel(m.month)}</th>
                <td className="py-1.5 pl-1 whitespace-nowrap">{rupees(m.spent_paise)}</td>
                <td className="py-1.5 pl-1 whitespace-nowrap">{rupees(m.invested_paise)}</td>
                <td className="py-1.5 pl-1 whitespace-nowrap">{rupees(m.paid_back_paise)}</td>
                <td className="py-1.5 pl-1 font-medium whitespace-nowrap">{rupees(m.net_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

/** The biggest categories of the range, each with its months as small bars in its colour. */
function Categories({ a }: { a: Data }) {
  const shown = a.categories.filter((c) => c.total_paise > 0).slice(0, 6)
  if (!shown.length) return null
  return (
    <Section title="Categories over time">
      {shown.map((c) => {
        const top = Math.max(1, ...c.months)
        const n = c.months.length
        return (
          <RowButton key={c.slug} onClick={() => seeTransactions({ month: a.end, category: c.slug })} label={`${c.name}: ${rupees(c.total_paise)}, ${percent(c.share_bp)} of Spent`}>
            <CategoryTile slug={c.slug} />
            <span className="min-w-[min(6rem,30vw)] flex-1">
              <span className="block wrap-break-word">{c.name}</span>
              <span className="block text-xs text-muted">{percent(c.share_bp)} of Spent</span>
            </span>
            <svg viewBox={`0 0 ${n * 6} 20`} className="h-5 w-16 shrink-0" aria-hidden="true">
              {c.months.map((v, i) => {
                const h = v > 0 ? Math.max(1.5, (v / top) * 20) : 0
                return <rect key={i} x={i * 6 + 1} y={20 - h} width="4" height={h} rx="1" fill={catColor(c.slug)} />
              })}
            </svg>
            <Money paise={c.total_paise} />
          </RowButton>
        )
      })}
    </Section>
  )
}

function Stats({ a }: { a: Data }) {
  const s = a.stats
  const rows: [string, string][] = [
    ['Average a day', `${rupees(s.per_day_paise)} over ${groupIndian(s.days)} ${s.days === 1 ? 'day' : 'days'}`],
    ['Payments', groupIndian(s.payments)],
    ['Biggest payment', s.biggest ? `${rupees(s.biggest.amount_paise, true)}, ${s.biggest.name}, ${dayLabel(s.biggest.time_utc)}` : '–'],
    ['Busiest day', s.busiest_weekday ? `${s.busiest_weekday.day}, ${s.busiest_weekday.count} payments` : '–'],
    ['UPI and card', `UPI ${percent(s.ways_bp.upi)} · card ${percent(s.ways_bp.card)} · other ${percent(s.ways_bp.other)}`],
    ['Waiting for your answer', s.waiting.count ? `${groupIndian(s.waiting.count)} · ${rupees(s.waiting.amount_paise)}` : 'Nothing'],
  ]
  return (
    <>
      <Section title="Numbers">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 px-4 py-3 text-sm">
          {rows.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="text-muted">{term}</dt>
              <dd className="min-w-0 text-right wrap-break-word tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>
      {s.regular.length > 0 && (
        <Section title="Paid regularly">
          {s.regular.map((r) => (
            <RowButton key={r.name} onClick={() => seeTransactions({ month: a.end, q: r.name })}>
              <Named name={r.name} detail={`${r.months} of ${a.months.length} months`} />
              <Money paise={r.total_paise} />
            </RowButton>
          ))}
        </Section>
      )}
    </>
  )
}
