import { useState } from 'react'

import type { Txn } from '../api/types.ts'
import { useSnapshot } from '../data/store.ts'
import { currentMonth, dayKey, dayLabel, fullLabel } from '../lib/dates.ts'
import { useApp, useNav } from '../state.tsx'
import { Button, CategoryTile, Empty, Freshness, Icon, Loaded, Money, MonthSwitcher, RowButton, Section, Sheet } from '../ui.tsx'
import { countsInSpent, labelName, matches, monthTxns } from './derive.ts'
import { isCredit, nameOf, roleText, subtitle } from './common.ts'

export function Transactions() {
  const { view, month, replace } = useNav()
  const [load, retry] = useSnapshot()
  const cats = load.status === 'ready' ? load.data.categories : []
  const labels = load.status === 'ready' ? load.data.labels : []
  const field = 'min-h-11 w-full min-w-0 rounded-lg border border-line bg-surface px-3 text-sm text-ink'
  return (
    <>
      <div className="pt-2">
        <MonthSwitcher month={month} setMonth={(m) => replace({ month: m })} latest={currentMonth()} />
        <Freshness />
      </div>
      <div className="space-y-2 px-4 pt-2">
        <label className="relative block">
          <span className="sr-only">Search names</span>
          <Icon name="search" className="pointer-events-none absolute top-3 left-3 text-muted" />
          <input
            type="search"
            value={view.q}
            onChange={(e) => replace({ q: e.target.value })}
            placeholder="Search names"
            className={`${field} pl-10`}
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="min-w-0 text-xs text-muted">
            Category
            <select className={field} value={view.category ?? ''} onChange={(e) => replace({ category: e.target.value || null })}>
              <option value="">All</option>
              {cats.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
            </select>
          </label>
          <label className="min-w-0 text-xs text-muted">
            Label
            <select
              className={field}
              value={view.label ?? ''}
              onChange={(e) => replace({ label: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">All</option>
              {labels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </label>
        </div>
      </div>
      <Loaded load={load} retry={retry}>
        {(s) => (
          <TxnList
            txns={monthTxns(s, month).filter(
              (t) =>
                (!view.category || t.category === view.category) &&
                (view.label === null || t.label?.id === view.label) &&
                matches(t, view.q),
            )}
            empty={view.q.trim() ? `No names match "${view.q.trim()}".` : undefined}
          />
        )}
      </Loaded>
    </>
  )
}

/**
 * Transactions grouped by IST day under sticky day headers, or one titled list (`title`).
 * A row opens its sheet; the open sheet is in the URL (?txn=).
 */
export function TxnList({ txns, title, empty = 'No transactions.' }: { txns: Txn[]; title?: string; empty?: string }) {
  const { view, open, back } = useNav()
  const [load] = useSnapshot()
  // A deep link to a transaction that is not in this list finds it in the whole snapshot.
  const all = load.status === 'ready' ? load.data.transactions : []
  const current = view.txn === null ? undefined : (txns.find((t) => t.id === view.txn) ?? all.find((t) => t.id === view.txn))
  const sheet =
    view.txn !== null &&
    (current ? (
      <TxnSheet txn={current} onClose={back} />
    ) : (
      <Sheet title="Transaction" onClose={back}>
        <Empty>This transaction is not in your data.</Empty>
      </Sheet>
    ))
  if (!txns.length) {
    return (
      <>
        <Empty>{empty}</Empty>
        {sheet}
      </>
    )
  }
  const days: [string, Txn[]][] = []
  if (title) days.push([title, txns])
  else {
    for (const t of txns) {
      const key = dayKey(t.time_utc)
      if (days.at(-1)?.[0] === key) days.at(-1)![1].push(t)
      else days.push([key, [t]])
    }
  }
  return (
    <>
      {days.map(([key, rows]) => (
        <Section key={key} title={title ?? dayLabel(rows[0].time_utc)} sticky={!title}>
          {rows.map((t) => (
            <RowButton key={t.id} onClick={() => open({ txn: t.id })}>
              <CategoryTile slug={t.category} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{nameOf(t)}</span>
                <span className="block truncate text-xs text-muted">
                  {title && `${dayLabel(t.time_utc)} · `}
                  {subtitle(t)}
                  {t.label && ` · ${t.label.name}`}
                </span>
              </span>
              <Money
                paise={t.amount_paise}
                credit={isCredit(t)}
                className={t.role === 'duplicate' || t.role === 'ignored' ? 'text-muted line-through' : ''}
              />
            </RowButton>
          ))}
        </Section>
      ))}
      {sheet}
    </>
  )
}

type Step = { kind: 'detail' } | { kind: 'category' } | { kind: 'scope'; slug: string } | { kind: 'label' }

function TxnSheet({ txn, onClose }: { txn: Txn; onClose: () => void }) {
  const { api, changed } = useApp()
  const [step, setStep] = useState<Step>({ kind: 'detail' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [load] = useSnapshot()
  const cats = load.status === 'ready' ? load.data.categories : []
  const labels = load.status === 'ready' ? load.data.labels : []
  const rule = labelName(newLabel, labels.map((l) => l.name))
  const counts = countsInSpent(txn)

  const run = async (write: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await write()
      changed()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.')
      setBusy(false)
    }
  }
  const choice = 'flex min-h-12 w-full items-center justify-between gap-3 px-4 py-2 text-left active:bg-press'

  return (
    <Sheet title={nameOf(txn)} onClose={onClose}>
      {step.kind === 'detail' && (
        <div className="px-4 py-4">
          <p className="text-3xl font-semibold">
            <Money paise={txn.amount_paise} credit={isCredit(txn)} exact />
          </p>
          <dl className="mt-4 space-y-3 text-sm">
            <Item term="When" value={fullLabel(txn.time_utc)} />
            <Item term="Counted" value={roleText(txn)} />
            <Item term="Category" value={`${txn.category_name} · ${txn.category_basis === 'owner' ? 'set by you' : 'automatic'}`} />
            <Item term="Label" value={txn.label?.name ?? 'None'} />
          </dl>
          <div className="mt-5 grid grid-cols-2 gap-2">
            <Button onClick={() => setStep({ kind: 'category' })} disabled={!counts}>Change category</Button>
            <Button onClick={() => setStep({ kind: 'label' })}>Label</Button>
          </div>
          {!counts && <p className="mt-2 text-xs text-muted">Only spending has a category to change.</p>}
        </div>
      )}
      {step.kind === 'category' && (
        <ul aria-label="Categories" className="divide-y divide-line">
          {cats.map((c) => (
            <li key={c.slug}>
              <button type="button" className={choice} onClick={() => setStep({ kind: 'scope', slug: c.slug })}>
                <CategoryTile slug={c.slug} />
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                {c.slug === txn.category && <span className="shrink-0 text-sm text-muted">current</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {step.kind === 'scope' && (
        <div className="space-y-2 px-4 py-4">
          <p className="text-sm text-muted">{cats.find((c) => c.slug === step.slug)?.name}</p>
          <div className="grid gap-2">
            <Button disabled={busy} onClick={() => run(() => api.setCategory(txn.id, step.slug, 'transaction'))}>Just this one</Button>
            {txn.display_name && (
              <Button kind="primary" disabled={busy} onClick={() => run(() => api.setCategory(txn.id, step.slug, 'merchant'))}>
                All from {txn.display_name}
              </Button>
            )}
          </div>
          <p className="text-xs text-muted">"All from" also covers future payments to them.</p>
        </div>
      )}
      {step.kind === 'label' && (
        <div>
          <ul aria-label="Labels" className="divide-y divide-line">
            {txn.label && (
              <li>
                <button type="button" className={choice} disabled={busy} onClick={() => run(() => api.clearLabel(txn.id))}>No label</button>
              </li>
            )}
            {labels.map((l) => (
              <li key={l.id}>
                <button type="button" className={choice} disabled={busy} onClick={() => run(() => api.setLabel(txn.id, l.id))}>
                  <span className="min-w-0 truncate">{l.name}</span>
                  {txn.label?.id === l.id && <span className="shrink-0 text-sm text-muted">current</span>}
                </button>
              </li>
            ))}
          </ul>
          <form
            className="flex gap-2 border-t border-line px-4 pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (rule.error) return
              void run(async () => {
                const made = await api.createLabel(rule.name)
                await api.setLabel(txn.id, made.id)
              })
            }}
          >
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="New label"
              aria-label="New label"
              aria-invalid={Boolean(newLabel && rule.error)}
              aria-describedby="new-label-rule"
              className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" kind="primary" disabled={busy || Boolean(rule.error)}>Add</Button>
          </form>
          <p id="new-label-rule" className="px-4 pt-1 text-xs text-danger" aria-live="polite">{newLabel && rule.error}</p>
        </div>
      )}
      {error && <p className="px-4 pb-2 text-sm text-danger" role="alert">{error}</p>}
    </Sheet>
  )
}

function Item({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-muted">{term}</dt>
      <dd className="min-w-0 text-right wrap-anywhere">{value}</dd>
    </div>
  )
}
