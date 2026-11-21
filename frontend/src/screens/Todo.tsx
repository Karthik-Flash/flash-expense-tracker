import { useState } from 'react'

import type { Category, Sender, Snapshot, Txn } from '../api/types.ts'
import { actions, checksView, enqueue, personMark, senderMark, shownName, todoView, useOutbox, type Op } from '../data/outbox.ts'
import { usePeople, useSnapshot } from '../data/store.ts'
import { dayLabel } from '../lib/dates.ts'
import { Button, CategoryChips, Empty, Header, Loaded, Money, Section } from '../ui.tsx'
import { seePayments, useNav } from '../state.tsx'
import { isCredit, nameOf } from './common.ts'
import { identifiersText, labelName, paymentsText, topCategories } from './derive.ts'
import { Pending } from './Transactions.tsx'

export function TodoScreen() {
  const [load, retry] = useSnapshot()
  const { ops } = useOutbox()
  return (
    <>
      <Header title="To-do" />
      <Loaded load={load} retry={retry}>
        {({ todo, categories, transactions }) => {
          // An item with an answer in the outbox leaves its list at once (D-093).
          const t = todoView(todo, ops)
          const checks = checksView(transactions, ops)
          const chips = topCategories(transactions, categories)
          const personOf = (txnId: number) => transactions.find((x) => x.id === txnId)?.person_id ?? null
          return (
            <>
              {t.senders.length === 0 && t.merchants.length === 0 && t.waiting.length === 0 && checks.length === 0 && <Empty>Nothing to do.</Empty>}
              {t.waiting.length > 0 && (
                <Section title="Saved on phone">
                  {t.waiting.map((op) => <WaitingRow key={op.seq} op={op} />)}
                </Section>
              )}
              {checks.length > 0 && (
                <Section title="Check these payments">
                  {checks.map((c) => <CheckRow key={c.id} t={c} />)}
                </Section>
              )}
              {t.senders.length > 0 && (
                <Section title="Who sent you money?">
                  {t.senders.map((s) => <SenderRow key={s.id} s={s} />)}
                </Section>
              )}
              {t.merchants.length > 0 && (
                <Section title="Pick a category">
                  {t.merchants.map((m) => <MerchantRow key={m.name} m={m} cats={categories} chips={chips} who={personOf(m.txn_id)} />)}
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

/** "Rohit V" over "Friend · Saved on phone · syncing · Undo". One the server answered with a
 *  conflict shows the choice right here: try again or drop it (D-107). */
function WaitingRow({ op }: { op: Op }) {
  return (
    <div className="px-4 py-2.5">
      <span className="block truncate">{op.item}</span>
      <span className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="min-w-0 truncate">{op.choice}</span>
        <Pending op={op} />
      </span>
      {op.state === 'failed' && op.message && <p className="text-xs text-muted wrap-break-word">{op.message}</p>}
    </div>
  )
}

/** A row the app read automatically from a bank it has no parser for yet (D-101). */
function CheckRow({ t }: { t: Txn }) {
  const item = nameOf(t)
  return (
    <div className="px-4 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{item}</span>
        <Money paise={t.amount_paise} credit={isCredit(t)} exact />
      </div>
      <p className="truncate text-xs text-muted">{dayLabel(t.time_utc)} · Read automatically</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button className="flex-1" onClick={() => void enqueue(actions.looksRight(t, item))}>Looks right</Button>
        <Button className="flex-1" onClick={() => void enqueue(actions.notAPayment(t, item))}>Not a payment</Button>
      </div>
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
  const { ops } = useOutbox()
  const { open } = useNav()
  const person = usePeople().find(s.person_id)
  const mark = (person && personMark(ops, person.key)) || failedOf(senderMark(ops, [s.id]))
  const under = identifiersText(person)
  return (
    <div className="px-4 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{person ? shownName(ops, person, s.display_name ?? 'Bank transfer in') : (s.display_name ?? 'Bank transfer in')}</span>
        <Money paise={s.total_paise} credit />
      </div>
      {under && <p className="truncate text-xs text-muted">{under}</p>}
      <p className="truncate text-xs text-muted">
        {s.count} {s.count === 1 ? 'credit' : 'credits'} · last {dayLabel(s.last_time_utc)}
      </p>
      {mark && (
        <p className="text-sm">
          {mark.choice} <Pending op={mark} />
        </p>
      )}
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
          <div className="mt-1 flex flex-wrap gap-x-3">
            {person && (
              <>
                <button type="button" className={QUIET} onClick={() => open({ person: person.key, act: null })}>Person</button>
                <button type="button" className={QUIET} onClick={() => open({ person: person.key, act: 'name' })}>Name</button>
                <button type="button" className={QUIET} onClick={() => open({ person: person.key, act: 'join' })}>Same as…</button>
              </>
            )}
            {s.person_id && <button type="button" className={QUIET} onClick={() => seePayments(s.person_id!)}>See payments</button>}
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

const QUIET = 'min-h-11 text-sm text-accent'

/** A refused answer stays on its card: "Not saved", with Try again and Discard (4H). */
const failedOf = (op: Op | undefined) => (op?.state === 'failed' ? op : undefined)

function MerchantRow({ m, cats, chips, who }: { m: Snapshot['todo']['merchants'][number]; cats: Category[]; chips: Category[]; who: string | null }) {
  const when = paymentsText(m.count, m.last_time_utc)
  // "All from" as before: every payment to them, past and future (D-091 outbox).
  const pick = (c: Category) => void enqueue(actions.setCategory({ id: m.txn_id, display_name: m.name }, c, 'merchant', m.name))
  const failed = useOutbox().ops.filter((o) => o.state === 'failed' && o.targets.merchants?.includes(m.name)).at(-1)
  return (
    <div className="px-4 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{m.name}</span>
        <Money paise={m.total_paise} />
      </div>
      <p className="truncate text-xs text-muted">{when}</p>
      {failed && (
        <p className="text-sm">
          {failed.choice} <Pending op={failed} />
        </p>
      )}
      <div className="mt-1.5">
        <CategoryChips chips={chips} cats={cats} onPick={pick} label={`${m.name}, ${when}`} />
      </div>
      {who && (
        <div className="flex justify-end">
          <button type="button" className={QUIET} onClick={() => seePayments(who)}>See payments</button>
        </div>
      )}
    </div>
  )
}
