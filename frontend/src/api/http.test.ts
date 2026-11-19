import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ApiError } from './client.ts'
import { HttpApi, OFFLINE } from './http.ts'

type Call = { url: string; init: RequestInit }

/** An HttpApi whose fetch answers `status` with `body` (JSON, or raw text); records calls and lost logins. */
function stub(status: number, body: unknown, token: (() => Promise<string | null>) | string | null = 'TEST-TOKEN', headers: Record<string, string> = {}) {
  const calls: Call[] = []
  const lost: number[] = []
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    if (status === 0) throw new TypeError('Failed to fetch')
    if (status === 304) return new Response(null, { status, headers })
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers })
  }) as typeof fetch
  const tokenFn = typeof token === 'function' ? token : async () => token
  const api = new HttpApi('https://api.test/', tokenFn, (s) => lost.push(s))
  return { api, calls, lost }
}

const signal = new AbortController().signal

test('the snapshot: Accept JSON, If-None-Match, ETag and size', async () => {
  const { api, calls } = stub(200, { schema_version: 1, months: [] }, 'TEST-TOKEN', { ETag: '"abc"' })
  const answer = await api.snapshot(null, signal)
  assert.equal(calls[0].url, 'https://api.test/api/v1/sync/snapshot')
  assert.deepEqual(calls[0].init.headers, { Authorization: 'Bearer TEST-TOKEN', Accept: 'application/json' })
  assert.equal(calls[0].init.cache, 'no-store')
  assert.equal(answer.status, 200)
  assert.equal(answer.status === 200 && answer.etag, '"abc"')
  assert.equal(answer.status === 200 && answer.bytes, '{"schema_version":1,"months":[]}'.length)

  const again = stub(304, null)
  assert.deepEqual(await again.api.snapshot('"abc"', signal), { status: 304 })
  assert.equal((again.calls[0].init.headers as Record<string, string>)['If-None-Match'], '"abc"')
})

test('a waking server page instead of JSON is an error, not data', async () => {
  const { api } = stub(200, '<!doctype html><title>Waking</title>')
  await assert.rejects(api.snapshot(null, signal), (e: ApiError) => e.status === 502)
})

test('writes carry the token, the path and the body', async () => {
  const { api, calls } = stub(200, { result: {}, recompute: { status: 'done', run: 1 } })
  await api.answerSender('s_ab/c', { answer: 'income', label: 'Family' })
  assert.equal(calls[0].url, 'https://api.test/api/v1/senders/s_ab%2Fc')
  assert.equal(calls[0].init.method, 'PUT')
  assert.equal(calls[0].init.body, '{"answer":"income","label":"Family"}')
  assert.equal((calls[0].init.headers as Record<string, string>).Accept, 'application/json')
  await api.resetSender('s_1')
  assert.equal(calls[1].init.method, 'DELETE')
})

test('401 and 403 tell the login layer; other errors keep the server words', async () => {
  const cases: [number, unknown, RegExp, number[]][] = [
    [401, { detail: 'not logged in' }, /session ended/, [401]],
    [403, { detail: 'no access' }, /no access/, [403]],
    [503, { detail: 'TEST internal' }, /not ready/, []],
    [500, 'not json', /had a problem/, []],
    [409, { detail: 'a label with this name already exists' }, /^A label with this name already exists\.$/, []],
    [422, { detail: [{ msg: 'x' }] }, /did not accept/, []],
  ]
  for (const [status, body, text, lost] of cases) {
    const s = stub(status, body)
    await assert.rejects(s.api.createLabel('Trip'), (e: ApiError) => e.status === status && text.test(e.message))
    assert.deepEqual(s.lost, lost, String(status))
  }
})

test('an owner action offline says so and queues nothing', async () => {
  const failed = stub(0, null)
  await assert.rejects(failed.api.createLabel('Trip'), (e: ApiError) => e.status === 0 && e.message === OFFLINE)
  await assert.rejects(failed.api.snapshot(null, signal), /Could not reach the server/)

  const expired = stub(200, {}, async () => {
    throw new TypeError('Failed to fetch') // the token refresh could not reach Supabase
  })
  await assert.rejects(expired.api.setLabel(1, 2), (e: ApiError) => e.message === OFFLINE)
  assert.deepEqual([expired.calls.length, expired.lost], [0, []])

  const saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', { value: { onLine: false }, configurable: true })
  try {
    const off = stub(200, {})
    await assert.rejects(off.api.clearLabel(1), (e: ApiError) => e.message === OFFLINE)
    assert.equal(off.calls.length, 0)
  } finally {
    if (saved) Object.defineProperty(globalThis, 'navigator', saved)
  }
})

test('no session: no request, and the owner goes to login', async () => {
  const { api, calls, lost } = stub(200, {}, null)
  await assert.rejects(api.snapshot(null, signal), (e: ApiError) => e.status === 401)
  assert.deepEqual([calls.length, lost], [0, [401]])
})
