import { useEffect, useState } from 'react'

import type { CreditAnswer, Sender, Txn } from '../api/types.ts'
import { actions, creditMark, discard, enqueue, isStuck, markFor, markText, personMark, retry, senderMark, shownName, STUCK_MS, timing, undo, useOutbox, waitingLabels, type Op } from '../data/outbox.ts'
import { OpSheet } from './Sync.tsx'
import { usePeople, useSnapshot } from '../data/store.ts'
import { currentMonth, dayKey, dayLabel, fullLabel } from '../lib/dates.ts'
import { provisionalTxn, takeCategoryOpen } from '../provisional.ts'
import { useNav } from '../state.tsx'
import { Button, CategoryTile, Empty, Freshness, Icon, Loaded, Money, MonthSwitcher, RowButton, Section, Sheet } from '../ui.tsx'
import { asksPaidBack, countsInSpent, inCategory, investmentTag, labelName, matches, monthTxns, paybackLines, personKey, senderOfCredit } from './derive.ts'
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
                inCategory(t, view.category) &&
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
  // 5G-A: a payment a notification just announced is not in the phone's copy yet: its sheet
  // opens from the notification's basics until the refresh brings the full row.
  const current = view.txn === null ? undefined : (txns.find((t) => t.id === view.txn) ?? all.find((t) => t.id === view.txn) ?? provisionalTxn(view.txn))
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
            const note = [mark.category, mark.label, mark.counted, mark.failed].map((m) => m && markText(m)).find(Boolean)
            return (
            <RowButton key={t.id} onClick={() => open({ txn: t.id })}>
              <CategoryTile slug={shown.category} />
              <span className="min-w-[min(6rem,35vw)] flex-1">
                <span className="block wrap-break-word">{nameOf(t)}</span>
                <span className="block text-xs wrap-break-word text-muted">
                  {t.identifier && `${t.identifier} · `}
                  {title && `${dayLabel(t.time_utc)} · `}
                  {subtitle(shown)}
                  {investmentTag(t) && ` · ${investmentTag(t)}`}
                  {label && ` · ${label}`}
                  {note && ` · ${note}`}
                </span>
              </span>
              <Money
                paise={t.amount_paise}
                credit={isCredit(t)}
                exact
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
  // "Change category" on a payment notification opens at the category list (5B-2, D-142).
  const [step, setStep] = useState<Step>(() => (takeCategoryOpen(txn.id) && countsInSpent(txn) ? { kind: 'category' } : { kind: 'detail' }))
  const [newLabel, setNewLabel] = useState('')
  const [load] = useSnapshot()
  const { ops } = useOutbox()
  const cats = load.status === 'ready' ? load.data.categories : []
  const labels = load.status === 'ready' ? load.data.labels : []
  // A label made on the phone can be picked before it syncs (D-110): by name, as new_label.
  const madeHere = waitingLabels(ops, labels.map((l) => l.name))
  const rule = labelName(newLabel, [...labels.map((l) => l.name), ...madeHere])
  const counts = countsInSpent(txn)
  const mark = markFor(ops, txn)
  const item = nameOf(txn)
  const { open } = useNav()
  const person = usePeople().find(txn.person_id)
  const personNote = person && personMark(ops, person.key)
  const here = person?.identifiers.find((i) => i.txn_id === txn.id || i.name === (txn.identifier ?? txn.display_name))
  // 5B-1 (D-134): a credit from a person asks "Paid back?"; a payment lists its paybacks.
  const sender = load.status === 'ready' ? senderOfCredit(txn, load.data.todo) : undefined
  const paybacks = load.status === 'ready' && txn.direction === 'debit' ? paybackLines(txn, load.data, nameOf) : []
  // Not a payment (D-103) as it will be once a waiting action syncs.
  const pendingCount = mark.counted && mark.counted.kind !== 'Looks right' ? mark.counted : undefined
  const ignoredNow = pendingCount ? pendingCount.kind === 'Not a payment' : txn.role === 'ignored'

  // Saved on the phone at once and sent in the background (D-091): the sheet just closes.
  const save = (change: Parameters<typeof enqueue>[0]) => {
    void enqueue(change)
    onClose()
  }
  const choice = 'flex min-h-12 w-full flex-wrap items-center justify-between gap-x-3 px-4 py-2 text-left active:bg-press'
  const how = txn.category_basis === 'owner' ? 'set by you' : txn.category_guessed ? 'guessed from the name' : 'automatic'
  const category = mark.category ? mark.category.choice : `${txn.category_name} · ${how}`
  const label = mark.label ? mark.label.choice : (txn.label?.name ?? 'None')

  return (
    <Sheet title={item} onClose={onClose}>
      {step.kind === 'detail' && (
        <div className="px-4 py-4">
          <p className="text-[min(1.875rem,11vw)] font-semibold whitespace-nowrap">
            <Money paise={txn.amount_paise} credit={isCredit(txn)} exact />
          </p>
          {txn.generic && <p className="mt-1 text-xs text-muted">Read automatically</p>}
          {txn.statement && <p className="mt-1 text-xs text-muted">Read from the bank statement</p>}
          {mark.failed && (
            <p className="mt-2 text-sm wrap-break-word">
              {mark.failed.kind} <Pending op={mark.failed} />
            </p>
          )}
          <dl className="mt-4 space-y-3 text-sm">
            <Item term="When" value={fullLabel(txn.time_utc)} />
            {investmentTag(txn) && <Item term="Investment" value={txn.investment === 'confirmed' ? 'Yes, you said so' : 'To confirm in To-do'} />}
            <Item term="Counted" value={mark.counted ? mark.counted.choice : roleText(txn)} mark={mark.counted} />
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
          {sender && asksPaidBack(txn, sender) && <PaidBack s={sender} txn={txn} server={load.status === 'ready' ? load.data.profile?.credit_answers?.[String(txn.id)] : undefined} />}
          {paybacks.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm" aria-label="Paid back">
              {paybacks.map((line) => <li key={line} className="wrap-break-word">{line}</li>)}
            </ul>
          )}
          {person && (
            <div className="mt-2 flex flex-wrap justify-end gap-x-3">
              <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => open({ person: person.key, act: null })}>
                Person
              </button>
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
          <div className="mt-2 flex flex-wrap justify-end gap-x-3">
            {txn.check && !mark.counted && (
              <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => save(actions.looksRight(txn, item))}>
                Looks right
              </button>
            )}
            {ignoredNow ? (
              <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => save(actions.countAgain(txn, item))}>
                Count it again
              </button>
            ) : (
              txn.role !== 'duplicate' && (
                <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => save(actions.notAPayment(txn, item))}>
                  Not a payment
                </button>
              )
            )}
          </div>
        </div>
      )}
      {step.kind === 'category' && (
        <ul aria-label="Categories" className="divide-y divide-line">
          {cats.map((c) => (
            <li key={c.slug}>
              <button type="button" className={choice} onClick={() => setStep({ kind: 'scope', slug: c.slug })}>
                <CategoryTile slug={c.slug} />
                <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{c.name}</span>
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
              <Button onClick={() => save(actions.setCategory(txn, picked, 'transaction', item))}>Just this payment</Button>
              {txn.display_name && (
                <Button kind="primary" onClick={() => save(actions.setCategory(txn, picked, 'merchant', item))}>
                  All payments to {txn.display_name}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted">"All payments" covers past and future payments to them. Undo it in Insights, Your rules.</p>
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
            {madeHere.map((name) => (
              <li key={`new:${name}`}>
                <button type="button" className={choice} onClick={() => save(actions.setLabel(txn, { new: name }, item))}>
                  <span className="min-w-0 truncate">{name}</span>
                  <span className="shrink-0 text-xs text-muted">{mark.label?.choice === name ? 'current · ' : ''}saved on phone</span>
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

/** "Saved on phone · syncing" beside a choice still in the outbox, with Undo while it can be
 *  undone; "Synced" a moment once it is on the server. After 2 minutes it says why, and a tap
 *  opens its details (D-107). One the server refused says "Not saved" on its item, with Try
 *  again and Discard (4H). */
export function Pending({ op }: { op: Op }) {
  const [details, setDetails] = useState(false)
  const [, setNow] = useState(0)
  useEffect(() => {
    // Re-render when "syncing" turns into "not synced yet", and when "Synced" goes.
    const due = op.state === 'confirmed' ? timing.syncedMs : STUCK_MS - (Date.now() - Date.parse(op.created_at))
    if (op.state === 'failed' || due < 0) return
    const timer = setTimeout(() => setNow(Date.now()), due + 50)
    return () => clearTimeout(timer)
  }, [op.state, op.created_at])
  const text = markText(op)
  if (!text) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs text-muted">
      {isStuck(op) ? (
        <button type="button" className="min-h-11 text-left text-xs text-muted underline" onClick={() => setDetails(true)}>
          {text}
        </button>
      ) : (
        text
      )}
      {details && <OpSheet op={op} onClose={() => setDetails(false)} />}
      {op.state === 'pending' && (
        <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => void undo(op)}>
          Undo
        </button>
      )}
      {op.state === 'failed' && (
        <>
          <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => void retry(op)}>
            Try again
          </button>
          <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => void discard(op)}>
            Discard
          </button>
        </>
      )}
    </span>
  )
}

/** Paid back / Not paid back on a credit (D-134, D-149): "Just this one" answers this credit
 *  only and beats the person-level answer; "Always for <name>" is the To-do sender answer
 *  (Friend / Ignore), the same outbox action, so it clears To-do and the other way round. */
function PaidBack({ s, txn, server }: { s: Sender; txn: Txn; server: CreditAnswer | undefined }) {
  const { ops } = useOutbox()
  const mark = senderMark(ops, [s.id])
  const one = creditMark(ops, txn.id)
  const waiting = mark && mark.state !== 'failed' ? (mark.body as { answer?: string } | null)?.answer : undefined
  const person = waiting ?? (s.status === 'to_confirm' ? null : s.role === 'payback' ? 'friend' : s.role === 'ignored' ? 'ignore' : s.role)
  const pending = one && one.state !== 'failed' ? ((one.body as { answer?: CreditAnswer } | null)?.answer ?? null) : undefined
  const mine = pending === undefined ? (server ?? null) : pending
  const now = mine === 'paid_back' ? 'friend' : mine === 'not_paid_back' ? 'ignore' : person
  const [asking, setAsking] = useState<'friend' | 'ignore' | null>(null)
  const who = s.display_name ?? 'this sender'
  const item = nameOf(txn)
  const justThis = (a: 'friend' | 'ignore') => {
    setAsking(null)
    void enqueue(actions.answerCredit(txn, a === 'friend' ? 'paid_back' : 'not_paid_back', item))
  }
  const always = (a: 'friend' | 'ignore') => {
    setAsking(null)
    void enqueue(actions.answerSender(s, { answer: a }))
  }
  const pressed = 'aria-pressed:border-accent aria-pressed:font-medium'
  const others = s.count === 1 ? `the 1 credit from ${who}` : `all ${s.count} credits from ${who}`
  return (
    <div className="mt-4 text-sm">
      <p className="text-muted">Is this money paid back to you?</p>
      <div className="mt-2 grid grid-cols-2 gap-2" role="group" aria-label="Paid back?">
        <button type="button" aria-pressed={now === 'friend'} className={`min-h-11 rounded-lg border border-line bg-surface px-3 ${pressed}`} onClick={() => setAsking('friend')}>Paid back</button>
        <button type="button" aria-pressed={now === 'ignore'} className={`min-h-11 rounded-lg border border-line bg-surface px-3 ${pressed}`} onClick={() => setAsking('ignore')}>Not paid back</button>
      </div>
      {mine ? (
        <p className="mt-1 text-xs text-muted">
          Answered for this credit only.{' '}
          <button type="button" className="min-h-11 text-accent underline underline-offset-2" onClick={() => void enqueue(actions.answerCredit(txn, null, item))}>Use the answer for {who}</button>
        </p>
      ) : (
        now === 'income' && <p className="mt-1 text-xs text-muted">Answered as income ({s.income_label ?? 'no label'}).</p>
      )}
      {asking && (
        <div className="mt-2 rounded-lg border border-line px-3 py-2" role="alert">
          <p>{asking === 'friend' ? 'Paid back' : 'Not paid back'}: for which credits?</p>
          <div className="mt-2 grid gap-2">
            <Button onClick={() => justThis(asking)}>Just this one</Button>
            <Button kind="primary" onClick={() => always(asking)}>Always for {who}</Button>
            <Button onClick={() => setAsking(null)}>Cancel</Button>
          </div>
          <p className="mt-1 text-xs text-muted">"Always" covers {others} and new ones; a "Just this one" answer stays as it is.</p>
        </div>
      )}
      {one && <Pending op={one} />}
      {mark && <Pending op={mark} />}
    </div>
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
