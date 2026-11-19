// The phone copy (D-089): the only module that touches IndexedDB. Database "flash",
// version 2: the snapshot, its meta, the last 20 launch timings (D-090) and, since 4B-2,
// the outbox of owner actions (D-091). It never leaves the device; sign-out deletes the
// whole database.

import { deleteDB, openDB, type DBSchema, type IDBPDatabase } from 'idb'

import type { Snapshot } from '../api/types.ts'
import type { Op } from './outbox.ts'

const NAME = 'flash'
const KEY = 'current'
const KEEP_TIMINGS = 20

export interface Meta {
  etag: string
  /** ms since the epoch: when the server last confirmed this copy (200 or 304). */
  fetched_at: number
  owner_id: string
  /** The signed-in login the copy belongs to. */
  user_id: string
  schema_version: number
}

export interface Timing {
  /** ms since the epoch, when the launch started. */
  at: number
  /** Navigation start to Home drawn from the phone copy; null on a first launch. */
  local_ms: number | null
  /** Navigation start to the fresh snapshot (or 304) applied; null when it failed. */
  fresh_ms: number | null
  request_ms: number | null
  result: '200' | '304' | 'error' | 'timeout'
  bytes: number | null
  /** The request took over 10 s: the server was asleep. */
  cold: boolean
  /** How the launch reached its first screen (boot.ts); absent before 4B-3. */
  boot?: string | null
}

interface Schema extends DBSchema {
  snapshot: { key: string; value: Snapshot }
  meta: { key: string; value: Meta }
  timings: { key: number; value: Timing }
  outbox: { key: number; value: Op }
}

let db: Promise<IDBPDatabase<Schema>> | null = null

function open(): Promise<IDBPDatabase<Schema>> {
  db ??= openDB<Schema>(NAME, 2, {
    upgrade(d, from) {
      if (from < 1) {
        d.createObjectStore('snapshot')
        d.createObjectStore('meta')
        d.createObjectStore('timings', { autoIncrement: true })
      }
      // Version 2 only adds a store: the stored copy, meta and timings stay.
      if (from < 2) d.createObjectStore('outbox', { keyPath: 'seq' })
    },
    blocking() {
      // A newer tab wants to upgrade or delete the database: let it.
      void db?.then((d) => d.close())
      db = null
    },
  })
  return db
}

export async function readLocal(): Promise<{ snapshot: Snapshot | null; meta: Meta } | null> {
  const d = await open()
  const tx = d.transaction(['snapshot', 'meta'])
  const [snapshot, meta] = await Promise.all([tx.objectStore('snapshot').get(KEY), tx.objectStore('meta').get(KEY)])
  return meta ? { snapshot: snapshot ?? null, meta } : null
}

/** A copy of another schema: drop it, keep the meta (whose it is) and the outbox. */
export async function dropSnapshot(): Promise<void> {
  const tx = (await open()).transaction(['snapshot', 'meta'], 'readwrite')
  const meta = await tx.objectStore('meta').get(KEY)
  await Promise.all([
    tx.objectStore('snapshot').delete(KEY),
    meta ? tx.objectStore('meta').put({ ...meta, etag: '' }, KEY) : undefined,
    tx.done,
  ])
}

/** The outbox, first in first out. */
export async function readOutbox(): Promise<Op[]> {
  return (await open()).getAll('outbox')
}

export async function putOp(op: Op): Promise<void> {
  await (await open()).put('outbox', op)
}

export async function deleteOp(seq: number): Promise<void> {
  await (await open()).delete('outbox', seq)
}

/** Replace the copy and its meta in one transaction. */
export async function saveLocal(snapshot: Snapshot, meta: Meta): Promise<void> {
  const tx = (await open()).transaction(['snapshot', 'meta'], 'readwrite')
  await Promise.all([tx.objectStore('snapshot').put(snapshot, KEY), tx.objectStore('meta').put(meta, KEY), tx.done])
}

/** A 304: the copy is still current. */
export async function touchLocal(fetchedAt: number): Promise<void> {
  const tx = (await open()).transaction('meta', 'readwrite')
  const meta = await tx.store.get(KEY)
  if (meta) await tx.store.put({ ...meta, fetched_at: fetchedAt }, KEY)
  await tx.done
}

export async function addTiming(t: Timing): Promise<void> {
  const tx = (await open()).transaction('timings', 'readwrite')
  await tx.store.add(t)
  const keys = await tx.store.getAllKeys()
  for (const key of keys.slice(0, Math.max(0, keys.length - KEEP_TIMINGS))) await tx.store.delete(key)
  await tx.done
}

/** Newest first. */
export async function readTimings(): Promise<Timing[]> {
  return (await (await open()).getAll('timings')).reverse()
}

/** Delete the whole database: sign-out, another login, another schema. */
export async function wipeLocal(): Promise<void> {
  const current = db
  db = null
  if (current) (await current.catch(() => null))?.close()
  await deleteDB(NAME)
}
