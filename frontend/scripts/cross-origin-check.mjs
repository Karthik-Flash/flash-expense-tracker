// Cross-origin check (D-104): the production build on one origin, the API on another, as on
// Vercel and Render. FAKE data, a test token, no Supabase. From frontend\:
//
//   node scripts/cross-origin-check.mjs
//
// It builds into dist-xo/, serves it on :4174, starts the API on :8765
// (backend/tests/cross_origin_server.py), then in headless Edge: a tap online, and a tap
// offline followed by going online. It prints each preflight and write with its status, and
// exits 1 when a write did not reach the server.
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

const FRONTEND = resolve(import.meta.dirname, '..')
const BACKEND = resolve(FRONTEND, '..', 'backend')
const APP = 'http://localhost:4174'
const API = 'http://127.0.0.1:8765'
const AUTH = 'http://127.0.0.1:9' // nothing listens: the stored session is all the app needs
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

// 1. The production build, pointed at the API's origin.
const env = { ...process.env, VITE_API_URL: API, VITE_SUPABASE_URL: AUTH, VITE_SUPABASE_PUBLISHABLE_KEY: 'xo-test', VITE_DEMO: '' }
const build = run(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', 'dist-xo', '--emptyOutDir'], { cwd: FRONTEND, env })
if ((await new Promise((r) => build.on('exit', r))) !== 0) done(2)
run(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--outDir', 'dist-xo', '--port', '4174', '--strictPort'], { cwd: FRONTEND, env })

// 2. The API, with the frontend's origin allowed.
const server = run(PYTHON, ['-m', 'tests.cross_origin_server', '8765', APP], { cwd: BACKEND })
const log = []
let token = null
createInterface({ input: server.stdout }).on('line', (line) => {
  if (line.startsWith('{')) token = JSON.parse(line).token
  else if (line.startsWith('request ')) log.push(line.slice(8))
})
server.stderr.on('data', (d) => process.stderr.write(d))
for (let i = 0; i < 120 && !token; i++) await sleep(250)
if (!token) done(2)
for (let i = 0; i < 40; i++) {
  try {
    await fetch(`${API}/health`)
    await fetch(APP)
    break
  } catch {
    await sleep(250)
  }
}

// 3. Headless Edge over the DevTools protocol.
run(EDGE, ['--headless', '--disable-gpu', '--remote-debugging-port=9334', `--user-data-dir=${mkdtempSync(join(tmpdir(), 'flash-xo-edge-'))}`, '--window-size=390,844', 'about:blank'])
let target
for (let i = 0; i < 40 && !target; i++) {
  await sleep(250)
  try {
    target = (await (await fetch('http://127.0.0.1:9334/json')).json()).find((t) => t.type === 'page')
  } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let id = 0
const pending = new Map()
const requests = new Map()
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) pending.get(m.id)(m.result)
  const p = m.params
  if (m.method === 'Network.requestWillBeSent' && p.request.url.startsWith(API)) requests.set(p.requestId, { method: p.request.method, path: new URL(p.request.url).pathname, result: '...' })
  if (m.method === 'Network.responseReceived' && requests.has(p.requestId)) requests.get(p.requestId).result = String(p.response.status)
  if (m.method === 'Network.loadingFailed' && requests.has(p.requestId)) requests.get(p.requestId).result = `failed: ${p.corsErrorStatus?.corsError ?? p.errorText}`
})
const cdp = (method, params = {}) => new Promise((r) => { pending.set(++id, r); ws.send(JSON.stringify({ id, method, params })) })
const js = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }))?.result?.value
const tapFirst = (text) => js(`(() => { const b = [...document.querySelectorAll('button')].filter((x) => x.textContent.trim() === ${JSON.stringify(text)}); if (!b.length) return false; b[0].click(); return true })()`)
const writes = () => [...requests.values()].filter((r) => r.method === 'PUT' || r.method === 'DELETE' || r.method === 'POST')

await cdp('Network.enable')
await cdp('Network.setBypassServiceWorker', { bypass: true })
await cdp('Runtime.enable')
await cdp('Page.enable')
await cdp('Page.navigate', { url: `${APP}/` })
await sleep(1500)
const session = { access_token: token, refresh_token: 'xo-refresh', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: 'user-a', aud: 'authenticated', role: 'authenticated', email: 'xo@example.invalid' } }
await js(`localStorage.setItem('sb-127-auth-token', ${JSON.stringify(JSON.stringify(session))})`)
await cdp('Page.navigate', { url: `${APP}/#/todo` })
await cdp('Page.reload', { ignoreCache: true })
await sleep(6000)
if (process.env.XO_DEBUG) console.log('page:', (await js('document.body.innerText')).slice(0, 400))

const results = []
// Online: one tap.
results.push(['online tap', await tapFirst('Friend')])
await sleep(4000)
const onlineWrites = writes().length
// Offline: a tap, then back online with the app open.
await cdp('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
await sleep(500)
results.push(['offline tap', await tapFirst('Friend')])
await sleep(3000)
const sentOffline = writes().length - onlineWrites
await cdp('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
await sleep(8000)

for (const [what, ok] of results) console.log(`${what}: ${ok ? 'tapped' : 'no button'}`)
console.log(`writes sent while offline: ${sentOffline} (want 0)`)
console.log('browser, API requests (method path result):')
for (const r of requests.values()) if (r.method !== 'GET') console.log(`  ${r.method} ${r.path} ${r.result}`)
console.log('server log, non-GET lines:')
for (const line of log) if (!line.startsWith('GET ')) console.log(`  ${line}`)
const put = writes()
const ok = put.length >= 2 && put.every((r) => r.result.startsWith('2')) && sentOffline === 0
console.log(ok ? 'CROSS-ORIGIN CHECK: PASS' : 'CROSS-ORIGIN CHECK: FAIL')
ws.close()
done(ok ? 0 : 1)
