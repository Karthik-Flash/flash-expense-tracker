// It's me and Investments (4Z, D-117, D-118): the answers go through the outbox, wait
// offline, and leave To-do at once; the demo server applies them like the real one, and a
// suggestion alone never moves a total. FAKE data only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import { FakeApi } from '../api/fake.ts'
import type { Snapshot } from '../api/types.ts'
import { wipeLocal } from './local.ts'
import { actions, drain, enqueue, shownKind, startOutbox, stopOutbox, syncState, todoView } from './outbox.ts'
import { clearData } from './store.ts'

const broker = { key: 's_groww', txn_id: 21, name: 'Test Broker' }
const todo = {
  senders: [], answered: [], merchants: [], unnamed: 0,
  suggestions: [{ kind: 'investment', key: 's_groww', txn_id: 21, name: 'Test Broker', count: 2 }],
} as unknown as Snapshot['todo']

afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('offline: It\'s me, undo, No and the owner names wait, then send in order', async () => {
  const sent: SendRequest[] = []
  let offline = true
  const api: Api = {
    demo: false,
    registerDevice: async () => ({ token: 'test-token' }),
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      if (offline) throw new ApiError(0, 'Could not reach the server.')
      sent.push(req)
      return { status: 200, detail: null, message: '' }
    },
  }
  await startOutbox(api)
  await enqueue(actions.setOwnerNames(['Test Owner Name', 'T Owner']))
  await enqueue(actions.setKind(broker, 'investment'))
  await drain()
  const ops = syncState().ops
  assert.equal(shownKind(ops, { key: 's_groww', kind: null }), 'investment')
  assert.deepEqual(todoView(todo, ops).suggestions, []) // answered: out of To-do at once
  await enqueue(actions.clearKind(broker)) // undo
  assert.equal(shownKind(syncState().ops, { key: 's_groww', kind: 'investment' }), null)
  await enqueue(actions.dismissSuggestion(broker, 'self'))
  await drain()
  offline = false
  await drain()
  assert.deepEqual(sent.map((r) => [r.method, r.path, r.body]), [
    ['PUT', '/profile/names', { names: ['Test Owner Name', 'T Owner'] }],
    ['PUT', '/people/21/kind', { kind: 'investment' }],
    ['DELETE', '/people/21/kind', null],
    ['PUT', '/people/21/suggestion', { kind: 'self' }],
  ])
})

test('demo server: a suggestion moves nothing; Yes, undo and No do what they say', async () => {
  const fake = new FakeApi()
  const signal = new AbortController().signal
  const snap = async (): Promise<Snapshot> => {
    const a = await fake.snapshot(null, signal)
    return a.status === 200 ? a.snapshot : (null as never)
  }
  const send = (method: SendRequest['method'], path: string, body: unknown = null) =>
    fake.send({ op_id: crypto.randomUUID(), method, path, body, defer: false }, signal)
  const spent = (s: Snapshot) => s.months.find((m) => m.month === '2026-11')!.summary.spent_paise
  const before = await snap()
  const groww = before.todo.suggestions!.find((x) => x.kind === 'investment')!
  assert.equal(groww.name, 'Groww')
  assert.equal((await send('PUT', `/people/${groww.txn_id}/kind`, { kind: 'investment' })).status, 200)
  const invested = await snap()
  assert.equal(spent(invested), spent(before) - 100000) // no longer spending
  assert.equal(invested.transactions.find((t) => t.id === groww.txn_id)!.role, 'investment')
  assert.equal((await send('DELETE', `/people/${groww.txn_id}/kind`)).status, 200)
  assert.equal(spent(await snap()), spent(before)) // undo: as before

  assert.equal((await send('PUT', '/profile/names', { names: ['Meera S'] })).status, 200)
  const asked = await snap()
  assert.equal(spent(asked), spent(before)) // "Is this you?" alone moves nothing
  const me = asked.todo.suggestions!.find((x) => x.kind === 'self')!
  assert.equal(me.name, 'Meera S')
  assert.equal((await send('PUT', `/people/${me.txn_id}/suggestion`, { kind: 'self' })).status, 200)
  assert.equal((await snap()).todo.suggestions!.some((x) => x.kind === 'self'), false)
})
