// Bank SMS on the phone (5A, D-122, D-124): the sheet's steps, the status rows of the Bank
// SMS and Speed sheets, the first-run period, and the plugin bridge (a stand-in plugin):
// an upload refreshes the snapshot, connect registers then hands over the token, sign-out
// revokes then wipes. FAKE values only.
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import type { Api, SendRequest } from '../api/client.ts'
import { connectPhone, isNativeApp, loadSms, setPluginForTests, signOutPhone, startSms, type FlashSms, type OpenAt } from './sms.ts'
import { bucketText, eventText, needsBatteryHint, NOT_NATIVE, periodStart, phoneText, smsStep, statusRows, type SmsStatus } from './smsState.ts'

const ON: SmsStatus = {
  ...NOT_NATIVE,
  available: true,
  deviceId: '00000000-0000-4000-8000-00000000000a',
  deviceName: 'TEST PHONE',
  permission: 'granted',
  connected: true,
  cursorMs: Date.UTC(2026, 10, 1),
  historyFromMs: Date.UTC(2026, 7, 1),
  queued: 2,
  awaiting: 1,
  lastUpload: { at: Date.UTC(2026, 10, 21, 9, 0), stored: 3 },
  lastAttempt: { at: Date.UTC(2026, 10, 21, 9, 5), result: 'server_error' },
  lastError: 'server_error',
  batteryUnrestricted: false,
  manufacturer: 'samsung',
}

afterEach(() => setPluginForTests(null))

test('the sheet walks permission, restricted settings, connect, period, on, revoked', () => {
  assert.equal(smsStep(NOT_NATIVE), 'browser')
  assert.equal(smsStep({ ...ON, permission: 'prompt', connected: false }), 'permission')
  assert.equal(smsStep({ ...ON, permission: 'denied', connected: false }), 'blocked')
  assert.equal(smsStep({ ...ON, connected: false, cursorMs: undefined }), 'connect')
  assert.equal(smsStep({ ...ON, cursorMs: undefined }), 'period')
  assert.equal(smsStep(ON), 'on')
  assert.equal(smsStep({ ...ON, revoked: true }), 'revoked')
  // Permission comes first: a revoked phone with SMS taken away asks for SMS again.
  assert.equal(smsStep({ ...ON, revoked: true, permission: 'denied' }), 'blocked')
})

test('the status rows: codes, counts and times only (the Speed sheet shows them too)', () => {
  const rows = Object.fromEntries(statusRows(ON))
  assert.equal(rows['SMS permission'], 'allowed')
  assert.equal(rows['This phone'], 'connected')
  assert.equal(rows['Waiting on phone'], '3')
  assert.equal(rows['Last upload'], 'Sat 21 Nov, 14:30, 3 new')
  // 5B-2 (D-142): the last problem in plain words; the code is in the diagnostics.
  assert.equal(rows['Last problem'], "the server didn't answer (it may be waking up)")
  assert.equal(rows['Last bank SMS seen'], '–')
  assert.equal(rows['Reading since'], 'Sat 1 Aug, 05:30')
  assert.equal(rows.Battery, 'optimised')
  assert.deepEqual(statusRows(NOT_NATIVE), [['Bank SMS', 'Android app only']])
  assert.equal(Object.fromEntries(statusRows({ ...ON, revoked: true, lastError: 'revoked' }))['This phone'], 'disconnected')
})

test('the battery hint shows only for a connected phone that Android may hold back', () => {
  assert.equal(needsBatteryHint(ON), true)
  assert.equal(needsBatteryHint({ ...ON, batteryUnrestricted: true }), false)
  assert.equal(needsBatteryHint({ ...ON, connected: false }), false)
  assert.equal(needsBatteryHint(NOT_NATIVE), false)
})

test('the first scan: from the newest message on the server less a day, or 3, 6, 12 months', () => {
  const now = Date.UTC(2026, 10, 22, 10, 0)
  assert.equal(periodStart('server', '2026-11-14T08:00:00Z', now), Date.UTC(2026, 10, 13, 8, 0))
  assert.equal(periodStart('server', null, now), Date.UTC(2026, 7, 22, 10, 0)) // nothing yet: 3 months
  assert.equal(periodStart(3, null, now), Date.UTC(2026, 7, 22, 10, 0))
  assert.equal(periodStart(6, null, now), Date.UTC(2026, 4, 22, 10, 0))
  assert.equal(periodStart(12, null, now), Date.UTC(2025, 10, 22, 10, 0))
})

function fakePlugin(start: SmsStatus, firstOpen: OpenAt | null = null) {
  let status = { ...start }
  let listener: ((e: { stored: number }) => void) | null = null
  let opener: ((e: OpenAt) => void) | null = null
  let pending = firstOpen
  const calls: string[] = []
  const plugin: FlashSms = {
    status: async () => status,
    requestSms: async () => status,
    requestNotifications: async () => (status = { ...status, notifications: 'granted' }),
    openAppInfo: async () => {},
    openSleepingApps: async () => ({ opened: true }),
    connect: async (o) => {
      calls.push(`connect ${o.token} ${o.apiUrl} ${o.user}`)
      return (status = { ...status, connected: true, revoked: false, signedOut: false })
    },
    disconnect: async (o) => {
      calls.push(o?.keep ? 'disconnect keep' : 'disconnect')
      if (o?.keep) return (status = { ...status, connected: false, signedOut: true })
      return (status = { ...status, connected: false, queued: 0, cursorMs: undefined, user: undefined })
    },
    startHistory: async () => status,
    syncNow: async () => status,
    takeOpen: async () => {
      const open = pending
      pending = null
      return { open }
    },
    diagnostics: async () => ({ text: 'Flash diagnostics' }),
    shareFile: async () => ({ shared: true }),
    addListener: (async (event: string, f: (e: never) => void) => {
      if (event === 'open') opener = f as (e: OpenAt) => void
      else listener = f as (e: { stored: number }) => void
      return { remove: async () => {} }
    }) as FlashSms['addListener'],
  }
  return { plugin, calls, emit: (stored: number) => listener?.({ stored }), tap: (at: OpenAt) => opener?.(at) }
}

function api(sendFails = false) {
  const sent: SendRequest[] = []
  const registered: [string, string][] = []
  const a: Api = {
    demo: false,
    snapshot: async () => ({ status: 304 }),
    async send(req) {
      sent.push(req)
      if (sendFails) throw new Error('offline')
      return { status: 200, detail: null, message: '' }
    },
    createInvite: async () => ({ code: 'TEST-CODE-0001' }),
    exportFile: async () => new Blob(),
    deleteAccount: async () => ({ status: 200, detail: null, message: '' }),
    async registerDevice(id, name) {
      registered.push([id, name])
      return { token: 'test-device-token' }
    },
  }
  return { api: a, sent, registered }
}

test('a browser has no plugin: the status says so', async () => {
  assert.equal(isNativeApp(), false)
  assert.equal((await loadSms()).available, false)
})

test('an upload that stored something refreshes the snapshot; one with nothing new does not', async () => {
  const fake = fakePlugin(ON)
  setPluginForTests(fake.plugin)
  let refreshes = 0
  await startSms(async () => void refreshes++, 'user-a')
  await startSms(async () => void refreshes++, 'user-a') // once only: one listener
  fake.emit(2)
  fake.emit(0)
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(refreshes, 1)
})

test('connect registers this phone with the login, then hands the token to the plugin', async () => {
  const fake = fakePlugin({ ...ON, connected: false })
  setPluginForTests(fake.plugin)
  const a = api()
  const s = await connectPhone(a.api, 'https://api.example.invalid', 'user-a')
  assert.deepEqual(a.registered, [[ON.deviceId, 'TEST PHONE']])
  assert.deepEqual(fake.calls, ['connect test-device-token https://api.example.invalid user-a'])
  assert.equal(s.connected, true)
})

test('sign-out revokes this phone on the server, then wipes it; offline it still wipes', async () => {
  for (const offline of [false, true]) {
    const fake = fakePlugin(ON)
    setPluginForTests(fake.plugin)
    const a = api(offline)
    await signOutPhone(a.api)
    assert.deepEqual(a.sent.map((r) => `${r.method} ${r.path}`), [`DELETE /devices/${ON.deviceId}`])
    assert.deepEqual(fake.calls, ['disconnect keep']) // 5B-2: the cursor and queue stay (D-143)
  }
  // Not connected: nothing to revoke.
  const fake = fakePlugin({ ...ON, connected: false })
  setPluginForTests(fake.plugin)
  const a = api()
  await signOutPhone(a.api)
  assert.equal(a.sent.length, 0)
})

test('another login on this phone disconnects it first: its SMS never go to the old account', async () => {
  const fake = fakePlugin({ ...ON, user: 'user-a' })
  setPluginForTests(fake.plugin)
  await startSms(async () => {}, 'user-b')
  assert.deepEqual(fake.calls, ['disconnect'])
  const same = fakePlugin({ ...ON, user: 'user-a' })
  setPluginForTests(same.plugin)
  await startSms(async () => {}, 'user-a')
  assert.deepEqual(same.calls, [])
})
test('5B-2: the same login after a sign-out reconnects by itself and keeps its place', async () => {
  const fake = fakePlugin({ ...ON, user: 'user-a', connected: false, signedOut: true, cursorMs: 5 })
  setPluginForTests(fake.plugin)
  const a = api()
  await startSms(async () => {}, 'user-a', () => connectPhone(a.api, 'https://api.example.invalid', 'user-a'))
  assert.deepEqual(fake.calls, ['connect test-device-token https://api.example.invalid user-a'])
  assert.equal((await loadSms()).cursorMs, 5) // no new scan, no new setup
  // Never set up (no cursor): nothing happens by itself.
  const fresh = fakePlugin({ ...ON, connected: false, cursorMs: undefined, user: undefined })
  setPluginForTests(fresh.plugin)
  await startSms(async () => {}, 'user-a', () => connectPhone(a.api, 'https://api.example.invalid', 'user-a'))
  assert.deepEqual(fresh.calls, [])
})

test('5B-2: a notification tap opens its payment, at a cold start and a warm one', async () => {
  const fake = fakePlugin(ON, { txnId: 42, act: 'category' })
  setPluginForTests(fake.plugin)
  const opened: OpenAt[] = []
  await startSms(async () => {}, 'user-a', undefined, (at) => opened.push(at))
  fake.tap({ txnId: 7, act: 'sheet' })
  assert.deepEqual(opened, [{ txnId: 42, act: 'category' }, { txnId: 7, act: 'sheet' }])
})

test('5B-2: the status in plain words, events and the standby bucket', () => {
  const rows = Object.fromEntries(statusRows({ ...ON, notifications: 'denied', standbyBucket: 40, lastError: 'server_error', signedOut: false }))
  assert.equal(rows['Notifications'], 'off')
  assert.match(rows['Battery'], /rarely used: Android delays uploads/)
  assert.match(rows['Last problem'], /didn't answer/)
  assert.equal(rows['This phone'], 'connected')
  assert.equal(bucketText(10), 'in use')
  assert.match(bucketText(45), /restricted/)
  assert.equal(bucketText(undefined), '')
  assert.equal(phoneText({ ...ON, connected: false, signedOut: true }), 'signed out (reconnects at sign-in)')
  assert.match(eventText({ at: Date.UTC(2026, 10, 22, 8, 35), type: 'sms_live', detail: 'HDFCBK' }), /14:05 · sms live · HDFCBK$/)
})