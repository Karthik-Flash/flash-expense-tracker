import { useState } from 'react'

import type { Category, LabelSummary, Txn } from '../api/types.ts'
import { currentMonth, dayKey, dayLabel, fullLabel } from '../lib/dates.ts'
import { useApp, useLoad } from '../state.tsx'
import { Button, Empty, Loaded, Money, MonthSwitcher, RowButton, Section, Sheet } from '../ui.tsx'
import { isCredit, nameOf, roleText, subtitle } from './common.ts'

export function Transactions() {
  const { api, month, setMonth } = useApp()
  const [category, setCategory] = useState('')
  const [label, setLabel] = useState('')
  const [pages, setPages] = useState(1)
  const [load, retry] = useLoad(async () => {
    const items: Txn[] = []
    let cursor: string | undefined
    let more = false
    for (let page = 0; page < pages; page++) {
      const result = await api.transactions({
        month,
        category: category || undefined,
        label: label ? Number(label) : undefined,
        cursor,
        limit: 40,
      })
      items.push(...result.items)
      cursor = result.next_cursor ?? undefined
      more = Boolean(cursor)
      if (!cursor) break
    }
    return { items, more }
  }, [month, category, label, pages])
  const [options] = useLoad(() => Promise.all([api.categories(), api.labels()]), ['options'])
  const [cats, labels]: [Category[], LabelSummary[]] = options.status === 'ready' ? options.data : [[], []]
  const select = 'min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm'
  return (
    <>
      <div className="pt-2">
        <MonthSwitcher month={month} setMonth={(m) => { setPages(1); setMonth(m) }} latest={currentMonth()} />
      </div>
      <div className="grid grid-cols-2 gap-2 px-4 pt-2">
        <label className="text-xs text-muted">
          Category
          <select className={select} value={category} onChange={(e) => { setPages(1); setCategory(e.target.value) }}>
            <option value="">All</option>
            {cats.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">
          Label
          <select className={select} value={label} onChange={(e) => { setPages(1); setLabel(e.target.value) }}>
            <option value="">All</option>
            {labels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
      </div>
      <Loaded load={load} retry={retry}>
        {({ items, more }) => (
          <>
            <TxnList txns={items} />
            {more && (
              <div className="px-4 pt-4 text-center">
                <Button onClick={() => setPages((n) => n + 1)}>Show more</Button>
              </div>
            )}
          </>
        )}
      </Loaded>
    </>
  )
}

/** Transactions grouped by IST day; a row opens its detail sheet. */
export function TxnList({ txns }: { txns: Txn[] }) {
  const [open, setOpen] = useState<Txn | null>(null)
  if (!txns.length) return <Empty>No transactions.</Empty>
  const days: [string, Txn[]][] = []
  for (const t of txns) {
    const key = dayKey(t.time_utc)
    if (days.at(-1)?.[0] === key) days.at(-1)![1].push(t)
    else days.push([key, [t]])
  }
  return (
    <>
      {days.map(([key, rows]) => (
        <Section key={key} title={dayLabel(rows[0].time_utc)}>
          {rows.map((t) => (
            <RowButton key={t.id} onClick={() => setOpen(t)}>
              <span className="min-w-0 flex-1">
                <span className="block truncate">{nameOf(t)}</span>
                <span className="block truncate text-xs text-muted">
                  {subtitle(t)}
                  {t.label && ` · ${t.label.name}`}
                </span>
              </span>
              <Money paise={t.amount_paise} credit={isCredit(t)} className={t.role === 'duplicate' || t.role === 'ignored' ? 'text-muted line-through' : ''} />
            </RowButton>
          ))}
        </Section>
      ))}
      {open && <TxnSheet txn={open} onClose={() => setOpen(null)} />}
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
  const [options] = useLoad(() => Promise.all([api.categories(), api.labels()]), ['options'])
  const [cats, labels]: [Category[], LabelSummary[]] = options.status === 'ready' ? options.data : [[], []]
  const counts = txn.role === 'spend' || txn.role === 'card_bill_counted' || txn.role === 'refund'

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
  const choice = 'flex min-h-12 w-full items-center justify-between border-b border-line px-4 text-left last:border-b-0 active:bg-press'

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
        <ul aria-label="Categories">
          {cats.map((c) => (
            <li key={c.slug}>
              <button type="button" className={choice} onClick={() => setStep({ kind: 'scope', slug: c.slug })}>
                {c.name}
                {c.slug === txn.category && <span className="text-sm text-muted">current</span>}
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
          <ul aria-label="Labels">
            {txn.label && (
              <li>
                <button type="button" className={choice} disabled={busy} onClick={() => run(() => api.clearLabel(txn.id))}>No label</button>
              </li>
            )}
            {labels.map((l) => (
              <li key={l.id}>
                <button type="button" className={choice} disabled={busy} onClick={() => run(() => api.setLabel(txn.id, l.id))}>
                  {l.name}
                  {txn.label?.id === l.id && <span className="text-sm text-muted">current</span>}
                </button>
              </li>
            ))}
          </ul>
          <form
            className="flex gap-2 px-4 pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                const made = await api.createLabel(newLabel)
                await api.setLabel(txn.id, made.id)
              })
            }}
          >
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="New label"
              aria-label="New label"
              maxLength={80}
              className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" kind="primary" disabled={busy || !newLabel.trim()}>Add</Button>
          </form>
        </div>
      )}
      {error && <p className="px-4 pb-2 text-sm text-danger" role="alert">{error}</p>}
    </Sheet>
  )
}

function Item({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{term}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  )
}

