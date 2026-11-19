import { useState } from 'react'

import type { Category, Sender, Snapshot } from '../api/types.ts'
import { actions, enqueue, todoView, useOutbox, type Op } from '../data/outbox.ts'
import { useSnapshot } from '../data/store.ts'
import { dayLabel } from '../lib/dates.ts'
import { Button, Empty, Header, Loaded, Money, Section } from '../ui.tsx'
import { labelName, paymentsText } from './derive.ts'
import { Pending } from './Transactions.tsx'

export function TodoScreen() {
  const [load, retry] = useSnapshot()
  const { ops } = useOutbox()
  return (
    <>
      <Header title="To-do" />
      <Loaded load={load} retry={retry}>
        {({ todo, categories }) => {
          // An item with an answer in the outbox leaves its list at once (D-093).
          const t = todoView(todo, ops)
          return (
            <>
              {t.senders.length === 0 && t.merchants.length === 0 && t.waiting.length === 0 && <Empty>Nothing to do.</Empty>}
              {t.waiting.length > 0 && (
                <Section title="Waiting to sync">
                  {t.waiting.map((op) => <WaitingRow key={op.seq} op={op} />)}
                </Section>
              )}
              {t.senders.length > 0 && (
                <Section title="Who sent you money?">
                  {t.senders.map((s) => <SenderRow key={s.id} s={s} />)}
                </Section>
              )}
              {t.merchants.length > 0 && (
                <Section title="Pick a category">
                  {t.merchants.map((m) => <MerchantRow key={m.name} m={m} cats={categories} />)}
                </Section>
              )}
              {todo.unnamed > 0 && (
                <p className="px-4 pt-3 text-xs text-muted">
                  {todo.unnamed} uncategorised {todo.unnamed === 1 ? 'payment has' : 'payments have'} no name. Set them in Transactions.
                </p>
              )}
              {t.answered.length > 0 && (
                <Section title="Answered">
                  {t.answered.map((s) => <SenderRow key={s.id} s={s} answered />)}
                </Section>
              )}
            </>
          )
        }}
      </Loaded>
    </>
  )
}

/** "Rohit V" over "Friend · Waiting to sync · Undo". */
function WaitingRow({ op }: { op: Op }) {
  return (
    <div className="px-4 py-2.5">
      <span className="block truncate">{op.item}</span>
      <span className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="min-w-0 truncate">{op.choice}</span>
        <Pending op={op} />
      </span>
    </div>
  )
}

/** The answer as the server has it (role, and the income label it saved). */
function answerText(s: Sender): string {
  if (s.role === 'payback') return 'Friend: counts as paid back'
  if (s.role === 'income') return `Income: ${s.income_label ?? 'no label'}`
  if (s.role === 'ignored') return 'Ignored: not counted'
  return 'Not answered'
}

function SenderRow({ s, answered = false }: { s: Sender; answered?: boolean }) {
  const [mode, setMode] = useState<'answer' | 'family' | 'shown'>(answered ? 'shown' : 'answer')
  const [family, setFamily] = useState(s.income_label ?? 'Family')
  const rule = labelName(family, [])
  // Saved on the phone first; the row moves to "Waiting to sync" (D-091).
  const answer = (a: Parameters<typeof actions.answerSender>[1]) => void enqueue(actions.answerSender(s, a))
  return (
    <div className="px-4 py-2.5">
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate">{s.display_name ?? 'Bank transfer in'}</span>
        <Money paise={s.total_paise} credit />
      </div>
      <p className="truncate text-xs text-muted">
        {s.count} {s.count === 1 ? 'credit' : 'credits'} · last {dayLabel(s.last_time_utc)}
      </p>
      {mode === 'shown' && (
        <div className="mt-1 flex items-center gap-3">
          <span className="min-w-0 flex-1 text-sm wrap-break-word">{answerText(s)}</span>
          <Button onClick={() => setMode('answer')}>Change</Button>
        </div>
      )}
      {mode === 'answer' && (
        <>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button className="flex-1" onClick={() => answer({ answer: 'friend' })}>Friend</Button>
            <Button className="flex-1" onClick={() => setMode('family')}>Family</Button>
            <Button className="flex-1" onClick={() => answer({ answer: 'ignore' })}>Ignore</Button>
          </div>
          {answered && (
            <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3">
              <button type="button" className="min-h-11 text-sm text-accent" onClick={() => void enqueue(actions.resetSender(s))}>
                Ask me again later
              </button>
              <button type="button" className="min-h-11 text-sm text-muted" onClick={() => setMode('shown')}>Cancel</button>
            </div>
          )}
        </>
      )}
      {mode === 'family' && (
        <form
          className="mt-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!rule.error) answer({ answer: 'income', label: rule.name })
          }}
        >
          <label className="block text-xs text-muted" htmlFor={`family-${s.id}`}>Income, labelled (1 to 30 characters)</label>
          <div className="mt-1 flex flex-wrap gap-2">
            <input
              id={`family-${s.id}`}
              value={family}
              onChange={(e) => setFamily(e.target.value)}
              aria-invalid={Boolean(rule.error)}
              className="min-h-11 min-w-32 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" kind="primary" disabled={Boolean(rule.error)}>Save</Button>
            <Button onClick={() => setMode(answered ? 'shown' : 'answer')}>Cancel</Button>
          </div>
          {rule.error && <p className="pt-1 text-xs text-danger" aria-live="polite">{rule.error}</p>}
        </form>
      )}
    </div>
  )
}

function MerchantRow({ m, cats }: { m: Snapshot['todo']['merchants'][number]; cats: Category[] }) {
  const when = paymentsText(m.count, m.last_time_utc)
  return (
    <div className="px-4 py-2.5">
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate">{m.name}</span>
        <Money paise={m.total_paise} />
      </div>
      <p className="truncate text-xs text-muted">{when}</p>
      <select
        aria-label={`Category for ${m.name}, ${when}`}
        value=""
        onChange={(e) => {
          const picked = cats.find((c) => c.slug === e.target.value)
          if (picked) void enqueue(actions.setCategory({ id: m.txn_id, display_name: m.name }, picked, 'merchant', m.name))
        }}
        className="mt-1.5 min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm"
      >
        <option value="">Pick a category</option>
        {cats.filter((c) => c.slug !== 'uncategorised').map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
      </select>
    </div>
  )
}
