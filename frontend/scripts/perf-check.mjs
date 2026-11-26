// Speed check (5G-A): the production build against the API with about 900 FAKE payments, in
// headless Edge with the CPU slowed 4x and "slow 3G" network. From frontend\:
//
//   node scripts/perf-check.mjs [--bulk 900] [--label before]
//
// Times, measured inside the page from the tap to the frame that shows the result:
//   warm:  Transactions open -> tap a row -> sheet; -> Change category -> picker
//   cold:  a deep link to one payment's sheet (as a notification tap opens it) with the
//          phone's copy on the device -> sheet; -> Change category -> picker
//   first: the same deep link with nothing on the device (a first install)
// plus every API response's size on the wire and unpacked, and the long tasks (> 50 ms).
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : fallback
}
const BULK = arg('bulk', '900')
const LABEL = arg('label', 'run')
const FRONTEND = resolve(import.meta.dirname, '..')
const BACKEND = resolve(FRONTEND, '..', 'backend')
const APP = 'http://localhost:4175'
const API = 'http://127.0.0.1:8766'
const AUTH = 'http://127.0.0.1:9'
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/microsoft-edge', '/usr/bin/google-chrome'].find(existsSync)
const PYTHON = [join(BACKEND, '.venv/Scripts/python.exe'), join(BACKEND, '.venv/bin/python')].find(existsSync)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const children = []
const run = (cmd, args, opts = {}) => {
  const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...opts })
  children.push(child)
  return child
}
const done = (code) => {
  for (const c of children) c.kill()
  process.exit(code)
}

const env = { ...process.env, VITE_API_URL: API, VITE_SUPABASE_URL: AUTH, VITE_SUPABASE_PUBLISHABLE_KEY: 'perf-test', VITE_DEMO: '', VITE_TEST_HOOKS: '1' }
const build = run(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', 'dist-perf', '--emptyOutDir'], { cwd: FRONTEND, env })
if ((await new Promise((r) => build.on('exit', r))) !== 0) done(2)
run(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--outDir', 'dist-perf', '--port', '4175', '--strictPort'], { cwd: FRONTEND, env })
const server = run(PYTHON, ['-m', 'tests.cross_origin_server', '8766', APP], { cwd: BACKEND, env: { ...process.env, FLASH_XO_BULK: BULK } })
let token = null
createInterface({ input: server.stdout }).on('line', (line) => {
  if (line.startsWith('{')) token = JSON.parse(line).token
})
for (let i = 0; i < 2400 && !token; i++) await sleep(250) // importing ~900 FAKE messages takes minutes
console.log(token ? "api ready" : "api did not start")
if (!token) done(2)
for (let i = 0; i < 120; i++) {
  const warm = await fetch(`${API}/api/v1/sync/snapshot`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null)
  if (warm?.status === 200) break
  await sleep(500)
}
await fetch(APP).catch(() => null)

run(EDGE, ['--headless', '--disable-gpu', '--remote-debugging-port=9336', `--user-data-dir=${mkdtempSync(join(tmpdir(), 'flash-perf-edge-'))}`, '--window-size=390,844', 'about:blank'])
let target
for (let i = 0; i < 40 && !target; i++) {
  await sleep(250)
  try {
    target = (await (await fetch('http://127.0.0.1:9336/json')).json()).find((t) => t.type === 'page')
  } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let id = 0
let loads = 0
const pending = new Map()
const responses = new Map()
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) pending.get(m.id)(m.result)
  if (m.method === 'Page.loadEventFired') loads++
  const p = m.params
  if (m.method === 'Network.responseReceived' && p.response.url.startsWith(API)) {
    responses.set(p.requestId, { path: new URL(p.response.url).pathname, status: p.response.status, encoding: p.response.headers['content-encoding'] ?? p.response.headers['Content-Encoding'] ?? 'none' })
  }
  if (m.method === 'Network.loadingFinished' && responses.has(p.requestId)) responses.get(p.requestId).wire = p.encodedDataLength
  if (m.method === 'Network.dataReceived' && responses.has(p.requestId)) {
    const r = responses.get(p.requestId)
    r.body = (r.body ?? 0) + p.dataLength
  }
})
// Every call answers within 150 s; a stuck one says which step it was.
const cdp = (method, params = {}) =>
  new Promise((r) => {
    pending.set(++id, r)
    setTimeout(() => r({ timedOut: method }), 150_000)
    ws.send(JSON.stringify({ id, method, params }))
  })
const step = (text) => console.log(`  step: ${text}`)
const js = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }))?.result?.value

await cdp('Network.enable')
// The service worker stays on: an installed app (and the APK) loads its own code locally.
await cdp('Network.setBypassServiceWorker', { bypass: false })
await cdp('Runtime.enable')
await cdp('Page.enable')
// Long tasks from the first moment of every page load.
await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__long = []; new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long.push([Math.round(e.startTime), Math.round(e.duration)]) }).observe({ type: 'longtask', buffered: true })` })
await cdp('Page.navigate', { url: `${APP}/` })
await sleep(1500)
const session = { access_token: token, refresh_token: 'perf-refresh', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: 'user-a', aud: 'authenticated', role: 'authenticated', email: 'perf@example.invalid' } }
await js(`localStorage.setItem('sb-127-auth-token', ${JSON.stringify(JSON.stringify(session))})`)

// In the page: wait (each frame) until `test` holds, then one more frame; ms since `from`.
const WAIT = `(test, from, limit = 60000) => new Promise((ok) => { const step = () => { if (test()) requestAnimationFrame(() => ok(Math.round(performance.now() - from))); else if (performance.now() - from > limit) ok(-1); else requestAnimationFrame(step) }; step() })`
const sheetOpen = `() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Change category')`
const pickerOpen = `() => [...document.querySelectorAll('[role=dialog] button')].some((b) => b.textContent.trim().startsWith('Groceries'))`

const throttle = async (on) => {
  await cdp('Emulation.setCPUThrottlingRate', { rate: on ? 4 : 1 })
  await cdp('Network.emulateNetworkConditions', on ? { offline: false, latency: 2000, downloadThroughput: 50_000, uploadThroughput: 50_000 } : { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
}

step('load Transactions unthrottled')
// 1. Unthrottled: load Transactions once, so the phone's copy is on the device.
await cdp('Page.navigate', { url: `${APP}/#/transactions?m=2026-11` })
await cdp('Page.reload', { ignoreCache: true })
await js(`(${WAIT})(() => document.querySelectorAll('main section button').length > 5, performance.now())`)
await sleep(3000)
const txnId = await js(`(() => { const b = [...document.querySelectorAll('main section button')].find((x) => /TEST|Rahul|Priya/i.test(x.textContent)); b.click(); return new URLSearchParams(location.hash.split('?')[1]).get('txn') })()`)
await sleep(500)
await js(`history.back()`)
await sleep(500)
responses.clear()

step(`picked transaction ${txnId}`)
const results = {}
await throttle(true)
step('warm')
// 2. Warm: tap a row, then Change category.
results.warm_sheet = await js(`(async () => { const t = performance.now(); [...document.querySelectorAll('main section button')][1].click(); return (${WAIT})(${sheetOpen}, t) })()`)
results.warm_picker = await js(`(async () => { const t = performance.now(); [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Change category').click(); return (${WAIT})(${pickerOpen}, t) })()`)
// A new page: wait for its load event, then time from its start (performance.now() is 0 there).
const fresh = async (url) => {
  await cdp('Page.navigate', { url: 'about:blank' }) // a real start, not a change of #fragment
  await sleep(300)
  const before = loads
  await cdp('Page.navigate', { url })
  for (let i = 0; i < 1200 && loads === before; i++) await sleep(100)
}
const pick = () => js(`(async () => { const t = performance.now(); [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Change category').click(); return (${WAIT})(${pickerOpen}, t, 120000) })()`)
// 3. Cold start from a deep link, the payment in the phone's copy (a notification of an
//    older payment).
step('cold')
await fresh(`${APP}/#/transactions?m=2026-11&txn=${txnId}`)
results.cold_sheet = await js(`(${WAIT})(${sheetOpen}, 0, 120000)`)
results.cold_picker = await pick()
results.cold_long_tasks = await js(`JSON.stringify(window.__long)`)
// 4. A new payment, uploaded after the copy was saved: what a payment notification opens.
step('notified')
const deviceId = crypto.randomUUID()
const reg = await (await fetch(`${API}/api/v1/devices`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: deviceId, name: 'PERF PHONE' }) })).json()
const notify = async (n) => {
  const body = `Sent Rs.${40 + n}.00
From HDFC Bank A/C *0001
To TEST NEW SHOP
On 20/11/26
Ref ${612499990000 + n}
Not You?
Call 18000000001/SMS BLOCK UPI to 9000000001
`
  const sms = { sender: 'VM-HDFCBK-S', body, received_at_utc: new Date(Date.UTC(2026, 10, 20, 6, n)).toISOString(), device_msg_id: `perf-${n}` }
  const answer = await (await fetch(`${API}/api/v1/ingest/sms`, { method: 'POST', headers: { Authorization: `Bearer ${reg.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: [sms] }) })).json()
  return answer.new_transactions[0]
}
//    a. As before 5G: the deep link alone; the sheet waits for the download.
const first = await notify(1)
await fresh(`${APP}/#/transactions?m=2026-11&txn=${first.id}`)
results.notified_without_item_sheet = await js(`(${WAIT})(${sheetOpen}, 0, 120000)`)
results.notified_without_item_picker = await pick()
//    b. 5G: the notification hands over the payment's basics (Wire.openItem).
const second = await notify(2)
await fresh(`${APP}/#/home`)
await js(`(${WAIT})(() => document.querySelectorAll('main section').length > 0, 0, 120000)`)
const item = { id: second.id, time_utc: second.time_utc, amount_paise: second.amount_paise, direction: second.direction, display_name: second.display_name, category: second.category ?? 'uncategorised', category_name: second.category_name ?? 'Uncategorised', role: second.role ?? 'spend' }
results.notified_with_item_sheet = await js(`(async () => { const t = performance.now(); globalThis.__flashOpen({ txnId: ${second.id}, act: 'sheet', item: ${JSON.stringify(item)} }); return (${WAIT})(${sheetOpen}, t, 120000) })()`)
results.notified_with_item_picker = await pick()
// 5. First install: nothing on the device.
step('first install')
await throttle(false)
await js(`Promise.all([indexedDB.databases ? indexedDB.databases().then((d) => Promise.all(d.map((x) => new Promise((ok) => { const r = indexedDB.deleteDatabase(x.name); r.onsuccess = r.onerror = r.onblocked = ok })))) : null])`)
await throttle(true)
await fresh(`${APP}/#/transactions?m=2026-11&txn=${txnId}`)
results.first_sheet = await js(`(${WAIT})(${sheetOpen}, 0, 120000)`)
results.first_picker = await pick()
await throttle(false)

console.log(`perf-check (${LABEL}): ${BULK} bulk payments, CPU 4x, latency 2 s, 50 KB/s`)
for (const [k, v] of Object.entries(results)) console.log(`  ${k}: ${typeof v === 'number' ? `${v} ms` : v}`)
console.log('  API responses while throttled (path status encoding wire-bytes body-bytes):')
for (const r of responses.values()) console.log(`    ${r.path} ${r.status} ${r.encoding} ${r.wire ?? '?'} ${r.body ?? '?'}`)
ws.close()
done(0)
