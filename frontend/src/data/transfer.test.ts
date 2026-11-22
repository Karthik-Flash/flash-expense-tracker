// "Moved between your accounts?" (4A, D-115): the answer goes through the outbox, the pair
// leaves To-do at once, and the demo server applies it like the real one. FAKE data only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import { FakeApi } from '../api/fake.ts'
import type { Snapshot, Transfer } from '../api/types.ts'
import { wipeLocal } from './local.ts'
import { actions, drain, enqueue, startOutbox, stopOutbox, syncState, todoView } from './outbox.ts'
import { clearData } from './store.ts'

const move: Transfer = {
  debit: 11, credit: 12, amount_paise: 300000, from_bank: 'HDFC', to_bank: 'SBI',
  debit_time_utc: '2026-11-16T04:30:00Z', credit_time_utc: '2026-11-16T04:42:00Z',
}
const todo = { senders: [], answered: [], merchants: [], unnamed: 0, transfers: [move] } as Snapshot['todo']

afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('an answer is one write, waits offline, and takes the pair out of To-do at once', async () => {
  const sent: SendRequest[] = []
  let offline = true
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    createInvite: async () => ({ code: 'TEST-CODE-0001' }),
    deleteAccount: async () => ({ status: 200, detail: null, message: '' }),
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      if (offline) throw new ApiError(0, 'Could not reach the server.')
      sent.push(req)
      return { status: 200, detail: null, message: '' }
    },
  }
  await startOutbox(api)
  assert.equal(todoView(todo, []).transfers.length, 1)
  await enqueue(actions.answerTransfer(move, true, 'HDFC to SBI'))
  await drain()
  const view = todoView(todo, syncState().ops)
  assert.equal(view.transfers.length, 0)
  assert.deepEqual(view.waiting.map((o) => o.choice), ['Moved between my accounts'])
  offline = false
  await drain()
  assert.deepEqual(sent.map((r) => [r.method, r.path, r.body]), [['PUT', '/transfers/11/12', { verdict: 'same' }]])
  assert.deepEqual(actions.answerTransfer(move, false, 'x').body, { verdict: 'different' })
  assert.equal(todoView({ ...todo, transfers: undefined }, []).transfers.length, 0) // an old phone copy
})

test('demo server: Yes makes both legs a transfer, No drops the pair, others are refused', async () => {
  const signal = new AbortController().signal
  const snap = async (fake: FakeApi): Promise<Snapshot> => {
    const a = await fake.snapshot(null, signal)
    return a.status === 200 ? a.snapshot : (null as never)
  }
  const send = (fake: FakeApi, path: string, verdict: string) =>
    fake.send({ op_id: crypto.randomUUID(), method: 'PUT', path, body: { verdict }, defer: false }, signal)
  const yes = new FakeApi()
  const before = await snap(yes)
  const [pair] = before.todo.transfers!
  assert.equal(pair.amount_paise, 300000)
  const spent = (s: Snapshot) => s.months.find((m) => m.month === '2026-11')!.summary.spent_paise
  assert.equal((await send(yes, `/transfers/${pair.debit}/${pair.credit}`, 'same')).status, 200)
  const after = await snap(yes)
  const role = (s: Snapshot, id: number) => s.transactions.find((t) => t.id === id)!.role
  assert.equal(role(after, pair.debit), 'self_transfer')
  assert.equal(role(after, pair.credit), 'self_transfer')
  assert.equal(spent(after), spent(before) - 300000) // the server's figure: no longer spending
  assert.deepEqual(after.todo.transfers, [])

  const no = new FakeApi()
  assert.equal((await send(no, `/transfers/${pair.debit}/${pair.credit}`, 'different')).status, 200)
  const kept = await snap(no)
  assert.equal(role(kept, pair.debit), 'spend')
  assert.deepEqual(kept.todo.transfers, [])
  assert.equal((await send(no, '/transfers/1001/1002', 'same')).status, 404)
})
