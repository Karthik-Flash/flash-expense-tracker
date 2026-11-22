import { useState } from 'react'

import { actions, enqueue, useOutbox } from '../data/outbox.ts'
import { useSnapshot } from '../data/store.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { useNav } from '../state.tsx'
import { Bar, Button, CategoryTile, Empty, Figure, Freshness, Header, Icon, Loaded, Money, RowButton, Section } from '../ui.tsx'
import { labelName } from './derive.ts'
import { Pending, TxnList } from './Transactions.tsx'

export function Labels() {
  const { open } = useNav()
  const [load, retry] = useSnapshot()
  const { ops } = useOutbox()
  const [name, setName] = useState('')
  // Labels being made (in the outbox): no totals yet, and their names are taken.
  const making = ops.filter((o) => o.state !== 'failed' && o.method === 'POST' && o.path === '/labels')
  const rule = labelName(name, [...(load.status === 'ready' ? load.data.labels.map((v) => v.name) : []), ...making.map((o) => o.choice)])
  const create = () => {
    void enqueue(actions.createLabel(rule.name))
    setName('')
  }
  return (
    <>
      <Header title="Labels" />
      <Freshness />
      <p className="px-4 text-sm text-muted">A label groups payments across months, like a trip. It never changes a category.</p>
      <Loaded load={load} retry={retry}>
        {({ labels: views }) =>
          views.length === 0 && making.length === 0 ? (
            <Empty>No labels yet.</Empty>
          ) : (
            <Section>
              {making.map((op) => (
                <div key={op.seq} className="flex items-start gap-3 px-4 py-3">
                  <Icon name="tag" className="pt-0.5 text-muted" />
                  <span className="min-w-[min(6rem,35vw)] flex-1">
                    <span className="block truncate font-medium">{op.choice}</span>
                    <Pending op={op} />
                  </span>
                </div>
              ))}
              {views.map((v) => (
                <RowButton key={v.id} onClick={() => open({ path: [String(v.id)] })}>
                  <Icon name="tag" className="self-start pt-0.5 text-muted" />
                  <span className="min-w-[min(6rem,35vw)] flex-1">
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
          if (!rule.error) create()
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
    </>
  )
}

export function LabelDetail({ id }: { id: number }) {
  const { back } = useNav()
  const [load, retry] = useSnapshot()
  const found = load.status === 'ready' ? load.data.labels.find((l) => l.id === id) : undefined
  return (
    <>
      <Header title={found?.name ?? 'Label'} back={back} />
      <Loaded load={load} retry={retry}>
        {(s) => {
          if (!found) return <Empty>This label is not in your data.</Empty>
          const v = found
          const rows = s.transactions.filter((t) => t.label?.id === id)
          const parts = [...v.categories].sort((a, b) => b.amount_paise - a.amount_paise)
          return (
            <>
              <div className="px-4 pt-2 text-center">
                <p className="text-sm text-muted">Net</p>
                <p className="mt-1 text-[min(1.875rem,11vw)] font-semibold whitespace-nowrap tabular-nums">{rupees(v.net_paise)}</p>
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
                      <span className="min-w-[min(6rem,35vw)] flex-1">
                      <span className="flex flex-wrap items-baseline gap-x-3">
                        <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{p.name}</span>
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
