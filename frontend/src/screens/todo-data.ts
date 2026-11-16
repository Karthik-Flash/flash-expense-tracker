import { allTransactions, type Api } from '../api/client.ts'
import type { Sender, Txn } from '../api/types.ts'

export interface Todo {
  senders: Sender[]
  merchants: { name: string; total: number; count: number; txnId: number }[]
  unnamed: number
}

/** What waits for the owner: senders to confirm and uncategorised merchants. */
export async function loadTodo(api: Api): Promise<Todo> {
  const [senders, open] = await Promise.all([
    api.senders('to_confirm'),
    allTransactions(api, { category: 'uncategorised' }),
  ])
  const groups = new Map<string, { total: number; count: number; txnId: number }>()
  let unnamed = 0
  for (const t of open.filter((x: Txn) => x.role === 'spend' || x.role === 'card_bill_counted')) {
    if (!t.display_name) {
      unnamed++
      continue
    }
    const g = groups.get(t.display_name) ?? { total: 0, count: 0, txnId: t.id }
    groups.set(t.display_name, { total: g.total + t.amount_paise, count: g.count + 1, txnId: g.txnId })
  }
  const merchants = [...groups.entries()]
    .map(([name, g]) => ({ name, ...g }))
    .sort((a, b) => b.total - a.total)
  return { senders, merchants, unnamed }
}
