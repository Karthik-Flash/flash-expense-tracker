import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ApiError } from './client.ts'
import { HttpApi } from './http.ts'

type Call = { url: string; init: RequestInit }

/** An HttpApi whose fetch answers `status` with `body`; records calls and lost logins. */
function stub(status: number, body: unknown, token: string | null = 'TEST-TOKEN') {
  const calls: Call[] = []
  const lost: number[] = []
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    if (status === 0) throw new TypeError('Failed to fetch')
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
  const api = new HttpApi('https://api.test/', async () => token, (s) => lost.push(s))
  return { api, calls, lost }
}

test('requests carry the token, the path and the body', async () => {
  const { api, calls } = stub(200, { items: [], next_cursor: null })
  await api.transactions({ month: '2026-11', category: 'food_drinks', limit: 200 })
  assert.equal(calls[0].url, 'https://api.test/api/v1/transactions?month=2026-11&category=food_drinks&limit=200')
  assert.deepEqual(calls[0].init.headers, { Authorization: 'Bearer TEST-TOKEN' })
  await api.answerSender('s_ab/c', { answer: 'income', label: 'Family' })
  assert.equal(calls[1].url, 'https://api.test/api/v1/senders/s_ab%2Fc')
  assert.equal(calls[1].init.method, 'PUT')
  assert.equal(calls[1].init.body, '{"answer":"income","label":"Family"}')
  await api.resetSender('s_1')
  assert.equal(calls[2].init.method, 'DELETE')
})

test('401 and 403 tell the login layer; other errors keep the server words', async () => {
  const cases: [number, unknown, RegExp, number[]][] = [
    [401, { detail: 'not logged in' }, /session ended/, [401]],
    [403, { detail: 'no access' }, /no access/, [403]],
    [503, { detail: 'TEST internal' }, /not ready/, []],
    [500, 'not json', /had a problem/, []],
    [409, { detail: 'a label with this name already exists' }, /^A label with this name already exists\.$/, []],
    [422, { detail: [{ msg: 'x' }] }, /did not accept/, []],
    [0, null, /Could not reach the server/, []],
  ]
  for (const [status, body, text, lost] of cases) {
    const s = stub(status, body)
    await assert.rejects(s.api.createLabel('Trip'), (e: ApiError) => e.status === status && text.test(e.message))
    assert.deepEqual(s.lost, lost, String(status))
  }
})

test('no session: no request, and the owner goes to login', async () => {
  const { api, calls, lost } = stub(200, {}, null)
  await assert.rejects(api.summary('2026-11'), (e: ApiError) => e.status === 401)
  assert.deepEqual([calls.length, lost], [0, [401]])
})
