import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ApiError, SendRequest } from './client.ts'
import { HttpApi } from './http.ts'

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

const op = (over: Partial<SendRequest> = {}): SendRequest => ({
  op_id: '00000000-0000-4000-8000-000000000001',
  method: 'PUT',
  path: '/senders/s_ab%2Fc',
  body: { answer: 'income', label: 'Family' },
  defer: false,
  ...over,
})

test('an owner action: token, Idempotency-Key, path, body; defer only when asked', async () => {
  const { api, calls } = stub(200, { result: {}, recompute: { status: 'done', run: 1 } })
  assert.deepEqual(await api.send(op(), signal), { status: 200, detail: null, message: '' })
  const headers = calls[0].init.headers as Record<string, string>
  assert.equal(calls[0].url, 'https://api.test/api/v1/senders/s_ab%2Fc')
  assert.equal(calls[0].init.method, 'PUT')
  assert.equal(calls[0].init.body, '{"answer":"income","label":"Family"}')
  assert.equal(headers['Idempotency-Key'], '00000000-0000-4000-8000-000000000001')
  assert.equal(headers.Accept, 'application/json')
  assert.equal(headers['X-Defer-Recompute'], undefined)
  await api.send(op({ method: 'DELETE', body: null, defer: true }), signal)
  const second = calls[1].init.headers as Record<string, string>
  assert.equal(calls[1].init.body, undefined)
  assert.equal(second['X-Defer-Recompute'], '1')
  assert.equal(second['Content-Type'], undefined)
})

test('an owner action answers every status; it never signs anyone out', async () => {
  const cases: [number, unknown, unknown, RegExp][] = [
    [401, { detail: 'not logged in' }, 'not logged in', /session ended/],
    [403, { detail: 'no access' }, 'no access', /no access/],
    [409, { detail: 'in_progress' }, 'in_progress', /In_progress/],
    [422, { detail: 'idempotency_key_reused' }, 'idempotency_key_reused', /Idempotency_key_reused/],
    [503, { detail: 'TEST internal' }, 'TEST internal', /not ready/],
    [500, 'not json', null, /had a problem/],
  ]
  for (const [status, body, detail, text] of cases) {
    const s = stub(status, body)
    const answer = await s.api.send(op(), signal)
    assert.equal(answer.status, status)
    assert.equal(answer.detail, detail)
    assert.match(answer.message, text)
    assert.deepEqual(s.lost, [], String(status))
  }
})

test('the snapshot: 401 and 403 tell the login layer', async () => {
  for (const [status, lost] of [[401, [401]], [403, [403]], [503, []]] as const) {
    const s = stub(status, { detail: 'x' })
    await assert.rejects(s.api.snapshot(null, signal), (e: ApiError) => e.status === status)
    assert.deepEqual(s.lost, lost)
  }
})

test('unreachable: an ApiError 0, and no request without a refreshable token', async () => {
  const failed = stub(0, null)
  await assert.rejects(failed.api.send(op(), signal), (e: ApiError) => e.status === 0)
  await assert.rejects(failed.api.snapshot(null, signal), /Could not reach the server/)
  const expired = stub(200, {}, async () => {
    throw new TypeError('Failed to fetch') // the token refresh could not reach Supabase
  })
  await assert.rejects(expired.api.send(op(), signal), (e: ApiError) => e.status === 0)
  assert.deepEqual([expired.calls.length, expired.lost], [0, []])
  const none = stub(200, {}, null)
  assert.equal((await none.api.send(op(), signal)).status, 401)
  assert.deepEqual([none.calls.length, none.lost], [0, []])
})

test('no session: no request, and the owner goes to login', async () => {
  const { api, calls, lost } = stub(200, {}, null)
  await assert.rejects(api.snapshot(null, signal), (e: ApiError) => e.status === 401)
  assert.deepEqual([calls.length, lost], [0, [401]])
})
