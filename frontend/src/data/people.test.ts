// People on the phone (4E, D-096): name, clear, same as, separate go through the outbox and
// wait offline on their person; the demo server joins and names like the real one. FAKE only.
import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { ApiError, type Api, type SendRequest } from '../api/client.ts'
import { FakeApi } from '../api/fake.ts'
import type { Person, Snapshot } from '../api/types.ts'
import { wipeLocal } from './local.ts'
import { actions, drain, enqueue, markText, personMark, roleConflict, shownName, startOutbox, stopOutbox, syncState } from './outbox.ts'
import { clearData } from './store.ts'

const rohit: Person = {
  key: 's_rohit',
  name: 'Rohit V',
  named: false,
  txn_id: 11,
  role: 'friend',
  identifiers: [{ name: 'Rohit V', txn_id: 11, from_file: false }],
}
const masked: Person = { ...rohit, key: 's_k77', name: '*k77@okhdfcbank', txn_id: 12, role: 'ignore', identifiers: [{ name: '*k77@okhdfcbank', txn_id: 12, from_file: false }] }

/** A server that cannot be reached, then one that applies every request once. */
function server() {
  const sent: SendRequest[] = []
  let offline = true
  const api: Api = {
    demo: false,
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      if (offline) throw new ApiError(0, 'Could not reach the server.')
      sent.push(req)
      return { status: 200, detail: null, message: '' }
    },
  }
  return { api, sent, online: () => (offline = false) }
}

afterEach(async () => {
  stopOutbox()
  await clearData()
  await wipeLocal()
})

test('offline: name, same as, separate and clear name wait on their person, in order', async () => {
  const s = server()
  await startOutbox(s.api)
  await enqueue(actions.namePerson(masked, 'Test Kiran'))
  assert.equal(shownName(syncState().ops, masked), 'Test Kiran') // the new name shows at once
  assert.equal(markText(personMark(syncState().ops, masked.key)!), 'Saved on phone · syncing')
  await enqueue(actions.joinPerson(masked, rohit, 'friend'))
  await enqueue(actions.separate(rohit, masked.identifiers[0]))
  await enqueue(actions.clearName(masked))
  await drain()
  assert.deepEqual(syncState().ops.map((o) => o.state), ['pending', 'pending', 'pending', 'pending'])
  assert.equal(personMark(syncState().ops, rohit.key)?.kind, 'Separate *k77@okhdfcbank')
  assert.equal(shownName(syncState().ops, masked), '*k77@okhdfcbank') // the clear waits too

  s.online()
  await drain()
  assert.deepEqual(
    s.sent.map((r) => [r.method, r.path, r.body]),
    [
      ['PUT', '/people/12/name', { name: 'Test Kiran' }],
      ['PUT', '/people/12/join', { into: 11, role: 'friend' }],
      ['DELETE', '/people/12/join', null],
      ['DELETE', '/people/12/name', null],
    ],
  )
  assert.ok(s.sent.every((r) => r.op_id && typeof r.op_id === 'string')) // each with its key
})

test('a join asks for the answer only when both sides have different ones', () => {
  assert.equal(roleConflict(masked, rohit), true)
  assert.equal(roleConflict({ role: null }, rohit), false)
  assert.equal(roleConflict(rohit, { role: 'friend' }), false)
  assert.deepEqual(actions.joinPerson(masked, rohit, null).body, { into: 11 })
})

test('demo server: join, name and separate as the real one; totals only from the server', async () => {
  const fake = new FakeApi()
  const signal = new AbortController().signal
  const snap = async (): Promise<Snapshot> => {
    const a = await fake.snapshot(null, signal)
    assert.equal(a.status, 200)
    return a.status === 200 ? a.snapshot : (null as never)
  }
  const send = (method: SendRequest['method'], path: string, body: unknown = null) =>
    fake.send({ op_id: crypto.randomUUID(), method, path, body, defer: false }, signal)
  const before = await snap()
  const who = (name: string) => before.people!.find((p) => p.name === name)!
  const a = who('Rohit V')
  const b = who('*k77@okhdfcbank')
  assert.equal((await send('PUT', `/people/${b.txn_id}/join`, { into: a.txn_id })).status, 200)
  assert.equal((await send('PUT', `/people/${a.txn_id}/name`, { name: 'Test Rohit' })).status, 200)
  const after = await snap()
  const joined = after.people!.find((p) => p.name === 'Test Rohit')!
  assert.deepEqual(joined.identifiers.map((i) => i.name).sort(), ['*k77@okhdfcbank', 'Rohit V'])
  assert.equal(joined.named, true)
  const rows = after.transactions.filter((t) => t.person_id === joined.key)
  assert.ok(rows.length >= 2 && rows.every((t) => t.display_name === 'Test Rohit'))
  assert.ok(rows.some((t) => t.identifier === '*k77@okhdfcbank'))
  const nov = after.months.find((m) => m.month === '2026-11')!
  assert.equal(nov.people.filter((p) => p.key === joined.key).length, 1) // one ledger row

  assert.equal((await send('DELETE', `/people/${a.txn_id}/join`)).status, 200)
  assert.equal((await send('DELETE', `/people/${b.txn_id}/join`)).status, 409) // the only one left
  assert.equal((await send('PUT', `/people/${b.txn_id}/name`, { name: 'T'.repeat(31) })).status, 422)
})
