import 'fake-indexeddb/auto'

import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import type { Api } from '../api/client.ts'
import type { Snapshot, SnapshotAnswer } from '../api/types.ts'
import { monthData } from '../screens/derive.ts'
import { addTiming, readLocal, readTimings, saveLocal, touchLocal, wipeLocal, type Meta, type Timing } from './local.ts'
import { agoPhrase, clearData, dataState, freshnessLine, refresh, speedRows, startData } from './store.ts'

// FAKE snapshots: only the fields the store and the Home selector read.
function snap(spent: number, owner = 'owner-a', schema = 1): Snapshot {
  return {
    schema_version: schema,
    generated_at: '2026-11-19T04:00:00Z',
    owner_id: owner,
    engine_versions: {},
    months: [{ month: '2026-11', summary: { spent_paise: spent } }],
    transactions: [],
    todo: { senders: [], answered: [], merchants: [], unnamed: 0 },
    labels: [],
    categories: [],
  } as unknown as Snapshot
}

const meta = (over: Partial<Meta> = {}): Meta => ({
  etag: '"local"',
  fetched_at: Date.parse('2026-11-19T03:00:00Z'),
  owner_id: 'owner-a',
  user_id: 'user-a',
  schema_version: 1,
  ...over,
})

type Reply = (etag: string | null, signal: AbortSignal) => Promise<SnapshotAnswer>

/** An Api whose snapshot() is `reply`; counts calls and the most at once. */
function fakeApi(reply: Reply) {
  const seen = { calls: 0, etags: [] as (string | null)[], running: 0, most: 0 }
  const api = {
    demo: false,
    async snapshot(etag: string | null, signal: AbortSignal) {
      seen.calls++
      seen.etags.push(etag)
      seen.running++
      seen.most = Math.max(seen.most, seen.running)
      try {
        return await reply(etag, signal)
      } finally {
        seen.running--
      }
    },
  } as unknown as Api
  return { api, seen }
}

/** Never answers; rejects when aborted, like fetch. */
const never: Reply = (_etag, signal) =>
  new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))

const until = async (ok: () => boolean) => {
  for (let i = 0; i < 200 && !ok(); i++) await new Promise((r) => setTimeout(r, 5))
  assert.ok(ok(), 'condition not reached')
}

async function eventually(ok: () => Promise<boolean>) {
  for (let i = 0; i < 200; i++) {
    if (await ok()) return
    await new Promise((r) => setTimeout(r, 5))
  }
  assert.fail('condition not reached')
}

afterEach(clearData)

test('the phone copy: snapshot and meta in one go, touch, timings kept to 20, wipe', async () => {
  await saveLocal(snap(100), meta())
  assert.deepEqual(await readLocal(), { snapshot: snap(100), meta: meta() })
  await touchLocal(42)
  assert.equal((await readLocal())?.meta.fetched_at, 42)
  for (let i = 0; i < 25; i++) {
    await addTiming({ at: i, local_ms: i, fresh_ms: null, request_ms: 1, result: 'error', bytes: null, cold: false })
  }
  const kept = await readTimings()
  assert.equal(kept.length, 20)
  assert.deepEqual([kept[0].at, kept.at(-1)?.at], [24, 5]) // newest first
  await wipeLocal()
  assert.equal(await readLocal(), null)
  assert.deepEqual(await readTimings(), [])
})

test('launch: Home draws from the phone copy while the request never answers', async () => {
  await saveLocal(snap(1234), meta())
  const { api, seen } = fakeApi(never)
  await startData(api, 'user-a')
  const s = dataState().snapshot
  assert.ok(s)
  assert.equal(monthData(s, '2026-11')?.summary.spent_paise, 1234)
  assert.equal(dataState().refreshing, true)
  assert.deepEqual(seen.etags, ['"local"'])
  assert.equal(freshnessLine(dataState()), 'Updating…')
})

test('a 304 moves fetched_at only', async () => {
  await saveLocal(snap(1234), meta())
  const { api } = fakeApi(async () => ({ status: 304 }))
  const before = Date.now()
  await startData(api, 'user-a')
  await until(() => !dataState().refreshing)
  assert.equal(monthData(dataState().snapshot!, '2026-11')?.summary.spent_paise, 1234)
  assert.ok((dataState().fetchedAt ?? 0) >= before)
  const stored = await readLocal()
  assert.equal(stored?.meta.etag, '"local"')
  assert.ok((stored?.meta.fetched_at ?? 0) >= before)
})

test('a failed refresh keeps the data and says Offline', async () => {
  await saveLocal(snap(1234), meta({ fetched_at: Date.now() - 5 * 60_000 }))
  const { api } = fakeApi(async () => {
    throw new Error('Could not reach the server.')
  })
  await startData(api, 'user-a')
  await until(() => !dataState().refreshing)
  assert.equal(monthData(dataState().snapshot!, '2026-11')?.summary.spent_paise, 1234)
  assert.equal(freshnessLine(dataState()), 'Offline · showing data from 5 min ago')
})

test('a 200 replaces the copy; sign-out wipes it', async () => {
  const { api } = fakeApi(async () => ({ status: 200, etag: '"new"', snapshot: snap(999), bytes: 10 }))
  await startData(api, 'user-a')
  await until(() => dataState().snapshot !== null && !dataState().refreshing)
  await eventually(async () => (await readLocal())?.meta.etag === '"new"')
  assert.equal(freshnessLine(dataState()), 'Updated just now')
  await clearData()
  assert.equal(dataState().snapshot, null)
  assert.equal(await readLocal(), null)
})

test('another login never sees the copy; another owner from the server wipes it', async () => {
  await saveLocal(snap(1234), meta({ user_id: 'user-b' }))
  const first = fakeApi(never)
  await startData(first.api, 'user-a')
  assert.equal(dataState().snapshot, null)
  assert.deepEqual(first.seen.etags, [null])
  assert.equal(await readLocal(), null)
  await clearData()

  await saveLocal(snap(1234), meta())
  const other = fakeApi(async () => ({ status: 200, etag: '"b"', snapshot: snap(5, 'owner-b'), bytes: 1 }))
  await startData(other.api, 'user-a')
  await until(() => !dataState().refreshing)
  const stored = await readLocal()
  assert.deepEqual([stored?.meta.owner_id, stored?.snapshot.owner_id], ['owner-b', 'owner-b'])
})

test('another schema: discarded, fetched fresh', async () => {
  await saveLocal(snap(1234), meta({ schema_version: 0 }))
  const { api, seen } = fakeApi(never)
  await startData(api, 'user-a')
  assert.equal(dataState().snapshot, null)
  assert.deepEqual(seen.etags, [null])
})

test('one refresh at a time; one asked meanwhile runs after', async () => {
  let release = () => {}
  const { api, seen } = fakeApi(() => new Promise((resolve) => (release = () => resolve({ status: 304 }))))
  await saveLocal(snap(1), meta())
  await startData(api, 'user-a')
  void refresh()
  void refresh()
  assert.equal(seen.calls, 1)
  release()
  await until(() => seen.calls === 2)
  release()
  await until(() => !dataState().refreshing)
  assert.deepEqual([seen.calls, seen.most], [2, 1])
})

test('launch timing is stored with local_ms empty on a first launch', async () => {
  const { api } = fakeApi(async () => ({ status: 200, etag: '"x"', snapshot: snap(1), bytes: 2048 }))
  await startData(api, 'user-a')
  await until(() => !dataState().refreshing)
  let timings: Timing[] = []
  await eventually(async () => (timings = await readTimings()).length === 1)
  assert.equal(timings[0].local_ms, null)
  assert.equal(timings[0].result, '200')
  assert.equal(timings[0].bytes, 2048)
  assert.ok((timings[0].fresh_ms ?? -1) >= 0)
})

test('freshness in IST', () => {
  const now = Date.parse('2026-11-19T10:00:00Z') // 15:30 IST
  assert.equal(agoPhrase(now - 20_000, now), 'just now')
  assert.equal(agoPhrase(now - 5 * 60_000, now), '5 min ago')
  assert.equal(agoPhrase(now - 2 * 3600_000 - 60_000, now), '2 h ago')
  assert.equal(agoPhrase(Date.parse('2026-11-18T16:10:00Z'), now), 'yesterday 21:40')
  assert.equal(agoPhrase(Date.parse('2026-11-16T16:10:00Z'), now), 'Mon 16 Nov 21:40')
  // 00:20 IST on the 19th is today in IST, though still the 18th in UTC.
  assert.equal(agoPhrase(Date.parse('2026-11-18T18:50:00Z'), now), '15 h ago')
  assert.equal(freshnessLine({ fetchedAt: null, refreshing: false, failed: false }), '')
})

test('Speed sheet rows from stored timings', () => {
  const rows = speedRows([
    { at: Date.parse('2026-11-19T03:00:00Z'), local_ms: 412, fresh_ms: 3250, request_ms: 2800, result: '200', bytes: 1, cold: false },
    { at: Date.parse('2026-11-18T16:10:00Z'), local_ms: null, fresh_ms: null, request_ms: 90000, result: 'timeout', bytes: null, cold: true },
  ])
  assert.deepEqual(rows, [
    { when: 'Thu 19 Nov 08:30', local: '412 ms', fresh: '3.3 s', result: '200' },
    { when: 'Wed 18 Nov 21:40', local: '–', fresh: '–', result: 'timeout, cold' },
  ])
})
