import { useState } from 'react'

import type { Txn } from '../api/types.ts'
import { actions, enqueue, markFor, markText, personMark, shownName, undo, useOutbox, type Op } from '../data/outbox.ts'
import { usePeople, useSnapshot } from '../data/store.ts'
import { currentMonth, dayKey, dayLabel, fullLabel } from '../lib/dates.ts'
import { useNav } from '../state.tsx'
import { Button, CategoryTile, Empty, Freshness, Icon, Loaded, Money, MonthSwitcher, RowButton, Section, Sheet } from '../ui.tsx'
import { countsInSpent, labelName, matches, monthTxns, personKey } from './derive.ts'
import { isCredit, nameOf, roleText, subtitle } from './common.ts'

export function Transactions() {
  const { view, month, replace } = useNav()
  const [load, retry] = useSnapshot()
  const cats = load.status === 'ready' ? load.data.categories : []
  const labels = load.status === 'ready' ? load.data.labels : []
  const field = 'min-h-11 w-full min-w-0 rounded-lg border border-line bg-surface px-3 text-sm text-ink'
  const { find } = usePeople()
  const { ops } = useOutbox()
  // "See payments" (4E): one person, every month; Back returns to where it was opened.
  const who = view.who
  const whoPerson = find(who)
  const whoTxn = who && load.status === 'ready' ? load.data.transactions.find((t) => personKey(t) === who) : undefined
  const whoName = whoPerson ? shownName(ops, whoPerson) : whoTxn ? nameOf(whoTxn) : 'Person'
  return (
    <>
      <div className="pt-2">
        {who ? (
          <div className="flex min-h-11 items-center gap-3 px-4">
            <h1 className="min-w-0 flex-1 truncate font-medium">Payments with {whoName}</h1>
            <button type="button" className="min-h-11 shrink-0 px-1 text-sm text-accent" onClick={() => replace({ who: null })}>Show all</button>
          </div>
        ) : (
          <MonthSwitcher month={month} setMonth={(m) => replace({ month: m })} latest={currentMonth()} />
        )}
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
            txns={(who ? s.transactions.filter((t) => personKey(t) === who) : monthTxns(s, month)).filter(
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
  const { ops } = useOutbox()
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
          {rows.map((t) => {
            // A choice waiting in the outbox shows on the row; the amount and totals do not move.
            const mark = markFor(ops, t)
            const shown = mark.category ? { ...t, category: mark.category.slug ?? t.category, category_name: mark.category.choice } : t
            const label = mark.label ? (mark.label.choice === 'No label' ? '' : mark.label.choice) : t.label?.name
            const note = [mark.category, mark.label].map((m) => m && markText(m)).find(Boolean)
            return (
            <RowButton key={t.id} onClick={() => open({ txn: t.id })}>
              <CategoryTile slug={shown.category} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{nameOf(t)}</span>
                <span className="block truncate text-xs text-muted">
                  {t.identifier && `${t.identifier} · `}
                  {title && `${dayLabel(t.time_utc)} · `}
                  {subtitle(shown)}
                  {label && ` · ${label}`}
                  {note && ` · ${note}`}
                </span>
              </span>
              <Money
                paise={t.amount_paise}
                credit={isCredit(t)}
                className={t.role === 'duplicate' || t.role === 'ignored' ? 'text-muted line-through' : ''}
              />
            </RowButton>
            )
          })}
        </Section>
      ))}
      {sheet}
    </>
  )
}

type Step = { kind: 'detail' } | { kind: 'category' } | { kind: 'scope'; slug: string } | { kind: 'label' }

function TxnSheet({ txn, onClose }: { txn: Txn; onClose: () => void }) {
  const [step, setStep] = useState<Step>({ kind: 'detail' })
  const [newLabel, setNewLabel] = useState('')
  const [load] = useSnapshot()
  const { ops } = useOutbox()
  const cats = load.status === 'ready' ? load.data.categories : []
  const labels = load.status === 'ready' ? load.data.labels : []
  const waitingLabels = ops.flatMap((o) => (o.state === 'failed' ? [] : (o.targets.labels ?? [])))
  const rule = labelName(newLabel, [...labels.map((l) => l.name), ...waitingLabels])
  const counts = countsInSpent(txn)
  const mark = markFor(ops, txn)
  const item = nameOf(txn)
  const { open } = useNav()
  const person = usePeople().find(txn.person_id)
  const personNote = person && personMark(ops, person.key)
  const here = person?.identifiers.find((i) => i.txn_id === txn.id || i.name === (txn.identifier ?? txn.display_name))

  // Saved on the phone at once and sent in the background (D-091): the sheet just closes.
  const save = (change: Parameters<typeof enqueue>[0]) => {
    void enqueue(change)
    onClose()
  }
  const choice = 'flex min-h-12 w-full items-center justify-between gap-3 px-4 py-2 text-left active:bg-press'
  const category = mark.category ? mark.category.choice : `${txn.category_name} · ${txn.category_basis === 'owner' ? 'set by you' : 'automatic'}`
  const label = mark.label ? mark.label.choice : (txn.label?.name ?? 'None')

  return (
    <Sheet title={item} onClose={onClose}>
      {step.kind === 'detail' && (
        <div className="px-4 py-4">
          <p className="text-3xl font-semibold">
            <Money paise={txn.amount_paise} credit={isCredit(txn)} exact />
          </p>
          <dl className="mt-4 space-y-3 text-sm">
            <Item term="When" value={fullLabel(txn.time_utc)} />
            <Item term="Counted" value={roleText(txn)} />
            <Item term="Category" value={category} mark={mark.category} />
            <Item term="Label" value={label} mark={mark.label} />
            {person && (
              <Item
                term="Person"
                value={`${shownName(ops, person)}${txn.identifier ? ` (${txn.identifier})` : ''}`}
                mark={personNote}
              />
            )}
          </dl>
          {person && (
            <div className="mt-2 flex flex-wrap justify-end gap-x-3">
              <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => open({ person: person.key, act: 'name' })}>
                {person.named ? 'Rename' : 'Name'}
              </button>
              <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => open({ person: person.key, act: 'join' })}>
                Same as…
              </button>
              {person.identifiers.length > 1 && here && !here.from_file && (
                <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => save(actions.separate({ ...person, name: shownName(ops, person) }, { name: here.name, txn_id: txn.id }))}>
                  Separate
                </button>
              )}
            </div>
          )}
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
                {c.slug === (mark.category?.slug ?? txn.category) && <span className="shrink-0 text-sm text-muted">current</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {step.kind === 'scope' && (() => {
        const picked = cats.find((c) => c.slug === step.slug)
        if (!picked) return null
        return (
          <div className="space-y-2 px-4 py-4">
            <p className="text-sm text-muted">{picked.name}</p>
            <div className="grid gap-2">
              <Button onClick={() => save(actions.setCategory(txn, picked, 'transaction', item))}>Just this one</Button>
              {txn.display_name && (
                <Button kind="primary" onClick={() => save(actions.setCategory(txn, picked, 'merchant', item))}>
                  All from {txn.display_name}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted">"All from" also covers future payments to them.</p>
          </div>
        )
      })()}
      {step.kind === 'label' && (
        <div>
          <ul aria-label="Labels" className="divide-y divide-line">
            {(mark.label ? mark.label.choice !== 'No label' : txn.label) && (
              <li>
                <button type="button" className={choice} onClick={() => save(actions.clearLabel(txn, item))}>No label</button>
              </li>
            )}
            {labels.map((l) => (
              <li key={l.id}>
                <button type="button" className={choice} onClick={() => save(actions.setLabel(txn, l, item))}>
                  <span className="min-w-0 truncate">{l.name}</span>
                  {(mark.label?.choice ?? txn.label?.name) === l.name && <span className="shrink-0 text-sm text-muted">current</span>}
                </button>
              </li>
            ))}
          </ul>
          <form
            className="flex gap-2 border-t border-line px-4 pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (!rule.error) save(actions.setLabel(txn, { new: rule.name }, item))
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
            <Button type="submit" kind="primary" disabled={Boolean(rule.error)}>Add</Button>
          </form>
          <p id="new-label-rule" className="px-4 pt-1 text-xs text-danger" aria-live="polite">{newLabel && rule.error}</p>
        </div>
      )}
    </Sheet>
  )
}

/** "Waiting to sync" beside a choice still in the outbox, with Undo while it can be undone. */
export function Pending({ op }: { op: Op }) {
  const text = markText(op)
  if (!text) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs text-muted">
      {text}
      {op.state === 'pending' && (
        <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => void undo(op)}>
          Undo
        </button>
      )}
    </span>
  )
}

function Item({ term, value, mark }: { term: string; value: string; mark?: Op }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 text-muted">{term}</dt>
      <dd className="min-w-0 text-right wrap-anywhere">
        {value}
        {mark && (
          <span className="block">
            <Pending op={mark} />
          </span>
        )}
      </dd>
    </div>
  )
}
