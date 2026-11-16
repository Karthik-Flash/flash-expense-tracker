import { useState } from 'react'

import { allTransactions } from '../api/client.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { useApp, useLoad } from '../state.tsx'
import { Bar, Button, Empty, Header, Loaded, Section } from '../ui.tsx'
import { TxnList } from './Transactions.tsx'

export function Labels() {
  const { api, go, changed } = useApp()
  const [load, retry] = useLoad(async () => {
    const labels = await api.labels()
    return Promise.all(labels.map((l) => api.label(l.id)))
  }, ['labels'])
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const create = async () => {
    setError('')
    try {
      await api.createLabel(name)
      setName('')
      changed()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.')
    }
  }
  return (
    <>
      <Header title="Labels" />
      <p className="px-4 text-sm text-muted">A label groups payments across months, like a trip. It never changes a category.</p>
      <Loaded load={load} retry={retry}>
        {(views) =>
          views.length === 0 ? (
            <Empty>No labels yet.</Empty>
          ) : (
            <Section>
              {views.map((v) => (
                <button key={v.id} type="button" onClick={() => go(`labels/${v.id}`)} className="block w-full border-b border-line px-4 py-3 text-left last:border-b-0 active:bg-press">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="truncate font-medium">{v.name}</span>
                    <span className="tabular-nums">{rupees(v.net_paise)}</span>
                  </span>
                  <span className="block text-xs text-muted tabular-nums">
                    Spent {rupees(v.spent_paise)} · Paid back {rupees(v.paid_back_paise)} · {v.transactions}{' '}
                    {v.transactions === 1 ? 'payment' : 'payments'}
                  </span>
                </button>
              ))}
            </Section>
          )
        }
      </Loaded>
      <form className="flex gap-2 px-4 pt-6" onSubmit={(e) => { e.preventDefault(); void create() }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New label"
          aria-label="New label"
          maxLength={80}
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3"
        />
        <Button type="submit" kind="primary" disabled={!name.trim()}>Create</Button>
      </form>
      {error && <p className="px-4 pt-2 text-sm text-danger" role="alert">{error}</p>}
    </>
  )
}

export function LabelDetail({ id }: { id: number }) {
  const { api, go } = useApp()
  const [load, retry] = useLoad(
    () => Promise.all([api.label(id), allTransactions(api, { label: id })]),
    [id],
  )
  return (
    <Loaded load={load} retry={retry}>
      {([view, txns]) => {
        const top = Math.max(1, ...view.categories.map((c) => c.amount_paise))
        const parts = [...view.categories].sort((a, b) => b.amount_paise - a.amount_paise)
        return (
          <>
            <Header title={view.name} back={() => go('labels')} />
            <div className="px-4 pt-2 text-center">
              <p className="text-sm text-muted">Net</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums">{rupees(view.net_paise)}</p>
              <p className="mt-2 text-sm text-muted tabular-nums">
                Spent {rupees(view.spent_paise)} · Paid back {rupees(view.paid_back_paise)}
              </p>
            </div>
            {parts.length > 0 && (
              <Section title="By category">
                {parts.map((p) => (
                  <div key={p.slug} className="border-b border-line px-4 py-3 last:border-b-0">
                    <span className="flex items-baseline justify-between gap-3">
                      <span>{p.name}</span>
                      <span className="tabular-nums">
                        {rupees(p.amount_paise)}
                        <span className="ml-2 inline-block w-10 text-right text-sm text-muted">{percentOf(p.amount_paise, view.spent_paise)}</span>
                      </span>
                    </span>
                    <Bar share={p.amount_paise / top} />
                  </div>
                ))}
              </Section>
            )}
            <TxnList txns={txns} />
          </>
        )
      }}
    </Loaded>
  )
}
