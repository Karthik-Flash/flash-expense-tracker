import { useState } from 'react'

import type { Category, Sender } from '../api/types.ts'
import { dayLabel } from '../lib/dates.ts'
import { useApp, useLoad } from '../state.tsx'
import { Button, Empty, Header, Loaded, Money, Section } from '../ui.tsx'
import { loadTodo, type Todo } from './todo-data.ts'

export function TodoScreen() {
  const { api } = useApp()
  const [load, retry] = useLoad(() => Promise.all([loadTodo(api), api.categories()]), ['todo'])
  return (
    <>
      <Header title="To-do" />
      <Loaded load={load} retry={retry}>
        {([todo, cats]) =>
          todo.senders.length === 0 && todo.merchants.length === 0 ? (
            <Empty>Nothing to do.</Empty>
          ) : (
            <>
              {todo.senders.length > 0 && (
                <Section title="Who sent you money?">
                  {todo.senders.map((s) => <SenderRow key={s.id} s={s} />)}
                </Section>
              )}
              {todo.merchants.length > 0 && (
                <Section title="Pick a category">
                  {todo.merchants.map((m) => <MerchantRow key={m.name} m={m} cats={cats} />)}
                </Section>
              )}
              {todo.unnamed > 0 && (
                <p className="px-4 pt-3 text-xs text-muted">
                  {todo.unnamed} uncategorised {todo.unnamed === 1 ? 'payment has' : 'payments have'} no name. Set them in Transactions.
                </p>
              )}
            </>
          )
        }
      </Loaded>
    </>
  )
}

function useWrite() {
  const { changed } = useApp()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async (write: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await write()
      changed()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, run }
}

function SenderRow({ s }: { s: Sender }) {
  const { api } = useApp()
  const { busy, error, run } = useWrite()
  const [income, setIncome] = useState<string | null>(null)
  return (
    <div className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate">{s.display_name ?? 'Bank transfer in'}</span>
        <Money paise={s.total_paise} credit />
      </div>
      <p className="text-xs text-muted">
        {s.count} {s.count === 1 ? 'credit' : 'credits'} · last {dayLabel(s.last_time_utc)}
      </p>
      {income === null ? (
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Button disabled={busy} onClick={() => run(() => api.answerSender(s.id, { answer: 'friend' }))}>Friend</Button>
          <Button disabled={busy} onClick={() => setIncome('Family')}>Family / income</Button>
          <Button disabled={busy} onClick={() => run(() => api.answerSender(s.id, { answer: 'ignore' }))}>Ignore</Button>
        </div>
      ) : (
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void run(() => api.answerSender(s.id, { answer: 'income', label: income.trim() }))
          }}
        >
          <input
            value={income}
            onChange={(e) => setIncome(e.target.value)}
            aria-label="Income name"
            maxLength={80}
            className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3"
          />
          <Button type="submit" kind="primary" disabled={busy || !income.trim()}>Save</Button>
          <Button onClick={() => setIncome(null)}>Cancel</Button>
        </form>
      )}
      {error && <p className="mt-1 text-sm text-danger" role="alert">{error}</p>}
    </div>
  )
}

function MerchantRow({ m, cats }: { m: Todo['merchants'][number]; cats: Category[] }) {
  const { api } = useApp()
  const { busy, error, run } = useWrite()
  return (
    <div className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate">{m.name}</span>
        <Money paise={m.total} />
      </div>
      <p className="text-xs text-muted">{m.count} {m.count === 1 ? 'payment' : 'payments'}</p>
      <select
        aria-label={`Category for ${m.name}`}
        disabled={busy}
        value=""
        onChange={(e) => e.target.value && run(() => api.setCategory(m.txnId, e.target.value, 'merchant'))}
        className="mt-2 min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm"
      >
        <option value="">Pick a category</option>
        {cats.filter((c) => c.slug !== 'uncategorised').map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
      </select>
      {error && <p className="mt-1 text-sm text-danger" role="alert">{error}</p>}
    </div>
  )
}
