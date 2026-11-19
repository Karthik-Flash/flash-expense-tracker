// The phone copy (D-089): the only module that touches IndexedDB. Database "flash",
// version 1: the snapshot, its meta, and the last 20 launch timings (D-090). It never leaves
// the device; sign-out deletes the whole database.

import { deleteDB, openDB, type DBSchema, type IDBPDatabase } from 'idb'

import type { Snapshot } from '../api/types.ts'

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
}

interface Schema extends DBSchema {
  snapshot: { key: string; value: Snapshot }
  meta: { key: string; value: Meta }
  timings: { key: number; value: Timing }
}

let db: Promise<IDBPDatabase<Schema>> | null = null

function open(): Promise<IDBPDatabase<Schema>> {
  db ??= openDB<Schema>(NAME, 1, {
    upgrade(d) {
      d.createObjectStore('snapshot')
      d.createObjectStore('meta')
      d.createObjectStore('timings', { autoIncrement: true })
    },
  })
  return db
}

export async function readLocal(): Promise<{ snapshot: Snapshot; meta: Meta } | null> {
  const d = await open()
  const tx = d.transaction(['snapshot', 'meta'])
  const [snapshot, meta] = await Promise.all([tx.objectStore('snapshot').get(KEY), tx.objectStore('meta').get(KEY)])
  return snapshot && meta ? { snapshot, meta } : null
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
