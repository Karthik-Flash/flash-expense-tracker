import { useState } from 'react'

import { allTransactions } from '../api/client.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { joinLoads, useApp, useLoad, useNav } from '../state.tsx'
import { Bar, Button, CategoryTile, Empty, Figure, Header, Icon, Loaded, Money, RowButton, Section } from '../ui.tsx'
import { labelName } from './derive.ts'
import { TxnList } from './Transactions.tsx'

export function Labels() {
  const { api, changed } = useApp()
  const { open } = useNav()
  const [load, retry] = useLoad(() => api.labels(), ['labels'])
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const rule = labelName(name, load.status === 'ready' ? load.data.map((v) => v.name) : [])
  const create = async () => {
    setError('')
    try {
      await api.createLabel(rule.name)
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
                <RowButton key={v.id} onClick={() => open({ path: [String(v.id)] })}>
                  <Icon name="tag" className="self-start pt-0.5 text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{v.name}</span>
                    <span className="mt-1 flex flex-wrap items-end gap-x-6 gap-y-1 text-sm">
                      <Figure term="Spent" paise={v.spent_paise} />
                      <Figure term="Paid back" paise={v.paid_back_paise} />
                      <Figure term="Net" paise={v.net_paise} />
                      <span className="text-xs text-muted">
                        {v.transactions} {v.transactions === 1 ? 'payment' : 'payments'}
                      </span>
                    </span>
                  </span>
                </RowButton>
              ))}
            </Section>
          )
        }
      </Loaded>
      <form
        className="flex gap-2 px-4 pt-6"
        onSubmit={(e) => {
          e.preventDefault()
          if (!rule.error) void create()
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New label"
          aria-label="New label"
          aria-invalid={Boolean(name && rule.error)}
          aria-describedby="label-rule"
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3"
        />
        <Button type="submit" kind="primary" disabled={Boolean(rule.error)}>Create</Button>
      </form>
      <p id="label-rule" className="px-4 pt-1 text-xs text-danger" aria-live="polite">{name && rule.error}</p>
      {error && <p className="px-4 pt-2 text-sm text-danger" role="alert">{error}</p>}
    </>
  )
}

export function LabelDetail({ id }: { id: number }) {
  const { api } = useApp()
  const { back } = useNav()
  const [view, retryView] = useLoad(() => api.label(id), ['label', id])
  const [txns, retryTxns] = useLoad(() => allTransactions(api, { label: id }), ['label-txns', id])
  const title = view.status === 'ready' ? view.data.name : 'Label'
  return (
    <>
      <Header title={title} back={back} />
      <Loaded
        load={joinLoads(view, txns)}
        retry={() => {
          retryView()
          retryTxns()
        }}
      >
        {([v, rows]) => {
          const parts = [...v.categories].sort((a, b) => b.amount_paise - a.amount_paise)
          return (
            <>
              <div className="px-4 pt-2 text-center">
                <p className="text-sm text-muted">Net</p>
                <p className="mt-1 text-3xl font-semibold whitespace-nowrap tabular-nums">{rupees(v.net_paise)}</p>
                <p className="mt-2 text-sm text-muted tabular-nums">
                  <span className="whitespace-nowrap">Spent {rupees(v.spent_paise)}</span> ·{' '}
                  <span className="whitespace-nowrap">Paid back {rupees(v.paid_back_paise)}</span>
                </p>
              </div>
              {parts.length > 0 && (
                <Section title="By category">
                  {parts.map((p) => (
                    <div key={p.slug} className="flex items-center gap-3 px-4 py-3">
                      <CategoryTile slug={p.slug} />
                      <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-3">
                        <span className="min-w-0 flex-1 truncate">{p.name}</span>
                        <Money paise={p.amount_paise} />
                        <span className="w-9 shrink-0 text-right text-sm text-muted tabular-nums">{percentOf(p.amount_paise, v.spent_paise)}</span>
                      </span>
                      <span className="mt-1.5 flex">
                        <Bar slug={p.slug} share={v.spent_paise > 0 ? p.amount_paise / v.spent_paise : 0} />
                      </span>
                      </span>
                    </div>
                  ))}
                </Section>
              )}
              <TxnList txns={rows} />
            </>
          )
        }}
      </Loaded>
    </>
  )
}
