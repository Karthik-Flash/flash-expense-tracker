import { useState, type ReactNode } from 'react'

import type { Category, Sender } from '../api/types.ts'
import { dayLabel } from '../lib/dates.ts'
import { joinLoads, useApp, useLoad } from '../state.tsx'
import { Button, Empty, Header, Loaded, Money, Section } from '../ui.tsx'
import { labelName } from './derive.ts'
import { loadTodo, type Todo } from './todo-data.ts'

export function TodoScreen() {
  const { api } = useApp()
  const [todo, retryTodo] = useLoad(() => loadTodo(api), ['todo'])
  const [cats, retryCats] = useLoad(() => api.categories(), ['categories'])
  const [done, retryDone] = useLoad(() => api.senders('confirmed'), ['senders', 'confirmed'])
  return (
    <>
      <Header title="To-do" />
      <Loaded
        load={joinLoads(todo, cats, done)}
        retry={() => {
          retryTodo()
          retryCats()
          retryDone()
        }}
      >
        {([t, categories, confirmed]) => (
          <>
            {t.senders.length === 0 && t.merchants.length === 0 && <Empty>Nothing to do.</Empty>}
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
            {t.unnamed > 0 && (
              <p className="px-4 pt-3 text-xs text-muted">
                {t.unnamed} uncategorised {t.unnamed === 1 ? 'payment has' : 'payments have'} no name. Set them in Transactions.
              </p>
            )}
            {confirmed.length > 0 && (
              <Section title="Confirmed">
                {confirmed.map((s) => <SenderRow key={s.id} s={s} answered />)}
              </Section>
            )}
          </>
        )}
      </Loaded>
    </>
  )
}

/** A write that, once saved, lets its row leave with a short collapse (unless `stay`). */
function useWrite(stay = false, then = () => {}) {
  const { changed } = useApp()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [left, setLeft] = useState(false)
  const run = async (write: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await write()
      setLeft(!stay)
      then()
      changed()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, left, run }
}

/** Collapses to nothing once `left`; the reload then drops the row. */
function Leaving({ left, children }: { left: boolean; children: ReactNode }) {
  return (
    <div
      className={`grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none ${left ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr]'}`}
      aria-hidden={left || undefined}
    >
      <div className="min-h-0 overflow-hidden">
        <div className="px-4 py-2.5">{children}</div>
      </div>
    </div>
  )
}

const ANSWERED: Record<Sender['role'], string> = {
  payback: 'Friend: counts as paid back',
  income: 'Family: income',
  uncertain: 'Not answered',
}

function SenderRow({ s, answered = false }: { s: Sender; answered?: boolean }) {
  const { api } = useApp()
  const [mode, setMode] = useState<'answer' | 'family' | 'shown'>(answered ? 'shown' : 'answer')
  // A confirmed sender stays in its section with the new answer; a new answer leaves.
  const { busy, error, left, run } = useWrite(answered, () => answered && setMode('shown'))
  const [family, setFamily] = useState('Family')
  const rule = labelName(family, [])
  return (
    <Leaving left={left}>
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate">{s.display_name ?? 'Bank transfer in'}</span>
        <Money paise={s.total_paise} credit />
      </div>
      <p className="truncate text-xs text-muted">
        {s.count} {s.count === 1 ? 'credit' : 'credits'} · last {dayLabel(s.last_time_utc)}
      </p>
      {mode === 'shown' && (
        <div className="mt-1 flex items-center gap-3">
          <span className="min-w-0 flex-1 text-sm">{ANSWERED[s.role]}</span>
          <Button onClick={() => setMode('answer')}>Change</Button>
        </div>
      )}
      {mode === 'answer' && (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button className="flex-1" disabled={busy} onClick={() => run(() => api.answerSender(s.id, { answer: 'friend' }))}>Friend</Button>
          <Button className="flex-1" disabled={busy} onClick={() => setMode('family')}>Family</Button>
          <Button className="flex-1" disabled={busy} onClick={() => run(() => api.answerSender(s.id, { answer: 'ignore' }))}>Ignore</Button>
        </div>
      )}
      {mode === 'family' && (
        <form
          className="mt-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!rule.error) void run(() => api.answerSender(s.id, { answer: 'income', label: rule.name }))
          }}
        >
          <label className="block text-xs text-muted" htmlFor={`family-${s.id}`}>Income, labelled</label>
          <div className="mt-1 flex flex-wrap gap-2">
            <input
              id={`family-${s.id}`}
              value={family}
              onChange={(e) => setFamily(e.target.value)}
              aria-invalid={Boolean(rule.error)}
              className="min-h-11 min-w-32 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" kind="primary" disabled={busy || Boolean(rule.error)}>Save</Button>
            <Button onClick={() => setMode(answered ? 'shown' : 'answer')}>Cancel</Button>
          </div>
          {rule.error && <p className="pt-1 text-xs text-danger" aria-live="polite">{rule.error}</p>}
        </form>
      )}
      {error && <p className="mt-1 text-sm text-danger" role="alert">{error}</p>}
    </Leaving>
  )
}

function MerchantRow({ m, cats }: { m: Todo['merchants'][number]; cats: Category[] }) {
  const { api } = useApp()
  const { busy, error, left, run } = useWrite()
  return (
    <Leaving left={left}>
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate">{m.name}</span>
        <Money paise={m.total} />
      </div>
      <select
        aria-label={`Category for ${m.name}, ${m.count} ${m.count === 1 ? 'payment' : 'payments'}`}
        disabled={busy}
        value=""
        onChange={(e) => e.target.value && run(() => api.setCategory(m.txnId, e.target.value, 'merchant'))}
        className="mt-1.5 min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm"
      >
        <option value="">Pick a category ({m.count} {m.count === 1 ? 'payment' : 'payments'})</option>
        {cats.filter((c) => c.slug !== 'uncategorised').map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
      </select>
      {error && <p className="mt-1 text-sm text-danger" role="alert">{error}</p>}
    </Leaving>
  )
}
