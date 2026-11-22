// Screenshots of every screen and sheet for design review (4H): the demo build (FAKE data,
// VITE_DEMO=1) in headless Edge at 360 px wide, light and dark, and at 200 % text. From
// frontend\ (another checkout's frontend folder can be given as --root):
//
//   node scripts/screens.mjs --out <folder> [--root <frontend folder>] [--port 5179]
//
// Writes <out>/<screen>-<light|dark|text200>.jpg and <out>/report.json: for each shot,
// whether the page scrolls sideways and which elements are clipped or overlap the screen
// edge. Then: node scripts/screens-page.mjs (docs/design/screens-4h.html).
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : fallback
}
const ROOT = resolve(arg('root', resolve(import.meta.dirname, '..')))
const OUT = resolve(arg('out', join(ROOT, 'screens-out')))
const PORT = Number(arg('port', '5179'))
const CDP = Number(arg('cdp', '9335'))
const APP = `http://localhost:${PORT}`
const EDGE = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/microsoft-edge', '/usr/bin/google-chrome'].find(existsSync)
const WIDTH = 360
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
mkdirSync(OUT, { recursive: true })

// The demo exists only in the dev server (src/api/index.ts).
run(process.execPath, [join(ROOT, 'node_modules/vite/bin/vite.js'), '--port', String(PORT), '--strictPort'], {
  cwd: ROOT,
  env: { ...process.env, VITE_DEMO: '1' },
})
for (let i = 0; i < 80; i++) {
  try {
    if ((await fetch(APP)).ok) break
  } catch {}
  await sleep(250)
}

run(EDGE, ['--headless', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${CDP}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'flash-shots-edge-'))}`, 'about:blank'])
let target
for (let i = 0; i < 40 && !target; i++) {
  await sleep(250)
  try {
    target = (await (await fetch(`http://127.0.0.1:${CDP}/json`)).json()).find((t) => t.type === 'page')
  } catch {}
}
if (!target) done(2)
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let id = 0
const pending = new Map()
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) pending.get(m.id)(m.result ?? m.error)
})
// Every call answers within 20 s (a hung call returns undefined and the shot is skipped).
const cdp = (method, params = {}) =>
  new Promise((r) => {
    pending.set(++id, r)
    setTimeout(r, 20_000)
    ws.send(JSON.stringify({ id, method, params }))
  })
const js = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }))?.result?.value
const click = (text, selector = 'button, a, [role=button]') =>
  js(`(() => { const b = [...document.querySelectorAll(${JSON.stringify(selector)})].find((x) => x.textContent.trim().startsWith(${JSON.stringify(text)})); if (!b) return false; b.click(); return true })()`)
const go = (hash) => js(`location.hash = ${JSON.stringify(hash)}`)
const demoState = (state) =>
  js(`(() => { const s = document.querySelector('select'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(s, ${JSON.stringify(state)}); s.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)

await cdp('Page.enable')
await cdp('Runtime.enable')

// Problems a reviewer should see: sideways scroll, and text cut off or past the screen edge.
const AUDIT = `(() => {
  const out = { sideways: document.documentElement.scrollWidth > innerWidth + 1, clipped: [], outside: [] }
  const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().replace(/\\s+/g, ' ').slice(0, 40)
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height || el.closest('.sr-only')) continue
    if (r.right > innerWidth + 1 || r.left < -1) out.outside.push(name(el))
    const style = getComputedStyle(el)
    const cut = style.overflowX === 'hidden' || style.overflowX === 'clip' || style.textOverflow === 'ellipsis'
    // Cut to less than half: a name squeezed away, not a long name with an ellipsis.
    if (cut && el.tagName !== 'INPUT' && el.children.length === 0 && el.clientWidth < el.scrollWidth / 2) out.clipped.push(name(el))
  }
  out.outside = [...new Set(out.outside)].slice(0, 12)
  out.clipped = [...new Set(out.clipped)].slice(0, 12)
  return out
})()`

const report = {}
async function shot(name, sheet) {
  for (const mode of ['light', 'dark', 'text200']) {
    await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: mode === 'dark' ? 'dark' : 'light' }] })
    await js(`document.documentElement.style.fontSize = ${JSON.stringify(mode === 'text200' ? '200%' : '')}`)
    const height = sheet ? 1400 : 780
    await cdp('Emulation.setDeviceMetricsOverride', { width: WIDTH, height, deviceScaleFactor: 1, mobile: true })
    await sleep(400)
    report[`${name}-${mode}`] = await js(AUDIT)
    // A whole screen: the viewport as tall as the page, so the tab bar sits at the bottom.
    const full = sheet ? height : Math.min(4000, Math.ceil((await js('document.documentElement.scrollHeight')) ?? height))
    if (full !== height) {
      await cdp('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: full, deviceScaleFactor: 1, mobile: true })
      await sleep(300)
    }
    let data
    for (let attempt = 0; attempt < 3 && !data; attempt++) {
      // Headless Edge sometimes misses the first frame after a resize: ask again.
      data = (await cdp('Page.captureScreenshot', { format: 'jpeg', quality: 62 }))?.data
    }
    if (!data) {
      console.log(`  no picture: ${name}-${mode}`)
      continue
    }
    writeFileSync(join(OUT, `${name}-${mode}.jpg`), Buffer.from(data, 'base64'))
  }
  await js(`document.documentElement.style.fontSize = ''`)
}

const M = '?m=2026-11'
await cdp('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: 780, deviceScaleFactor: 1, mobile: true })
await cdp('Page.navigate', { url: `${APP}/#/home` })
await sleep(2500)
await js(`sessionStorage.removeItem('flash-demo-signed-in'); localStorage.clear()`)
await cdp('Page.reload', {})
await sleep(2500)
await shot('login')

await js(`sessionStorage.setItem('flash-demo-signed-in', '1')`)
await cdp('Page.navigate', { url: `${APP}/#/home${M}` })
await cdp('Page.reload', {})
await sleep(5000) // the demo server answers after a short delay
await shot('home')
await click('Chart')
await sleep(500)
await shot('home-chart')
await click('List')
await go(`/home${M}&speed`)
await sleep(800)
await shot('sheet-speed', true)
await go(`/home${M}&unsaved`)
await sleep(800)
await shot('sheet-unsaved', true)
await go(`/home${M}&sms`) // 5A: in a browser, the phones and Revoke
await sleep(800)
await shot('sheet-sms', true)
// 5C: settings, people who use Flash, delete my account, what Flash stores, the first run.
for (const sheet of ['settings', 'members', 'delete', 'privacy', 'welcome']) {
  await go(`/home${M}&${sheet}`)
  await sleep(800)
  await shot(`sheet-${sheet}`, true)
}
// 5A: the Android app's steps, with a stand-in plugin set on the dev server's own module.
const android = (status) =>
  js(`import('/src/native/sms.ts').then(async (m) => {
    const s = ${JSON.stringify(status)}
    const answer = async () => s
    m.setPluginForTests({ status: answer, requestSms: answer, openAppInfo: async () => {}, connect: answer, disconnect: answer, startHistory: answer, syncNow: answer, addListener: async () => ({ remove: async () => {} }) })
    await m.loadSms()
    return true
  })`)
const phone = { available: true, deviceId: '00000000-0000-4000-8000-000000000001', deviceName: 'Demo phone', permission: 'granted', connected: true, revoked: false, queued: 0, awaiting: 0, dropped: 0, lastError: '', batteryUnrestricted: true, manufacturer: 'samsung' }
await go(`/home${M}`)
await android({ ...phone, permission: 'prompt', connected: false })
await sleep(800)
await shot('home-android')
await go(`/home${M}&sms`)
await sleep(800)
await shot('sheet-sms-permission', true)
await android({ ...phone, permission: 'denied', connected: false })
await sleep(800)
await shot('sheet-sms-blocked', true)
await android(phone)
await sleep(800)
await shot('sheet-sms-period', true)
const on = { ...phone, cursorMs: Date.UTC(2026, 10, 20), historyFromMs: Date.UTC(2026, 7, 22), queued: 2, lastUpload: { at: Date.UTC(2026, 10, 21, 9), stored: 3 }, lastAttempt: { at: Date.UTC(2026, 10, 21, 9, 5), result: 'server_error' }, lastError: 'server_error', batteryUnrestricted: false }
await android(on)
await sleep(800)
await shot('sheet-sms-on', true)
await go(`/home${M}&speed`)
await sleep(800)
await shot('sheet-speed-android', true)
await js(`import('/src/native/sms.ts').then((m) => { m.setPluginForTests(null); return true })`)
await go('/home?m=2026-01')
await sleep(800)
await shot('home-empty-month')
await go(`/home/category/food_drinks${M}`)
await sleep(800)
await shot('category')
await go(`/home/category/food_drinks/Swiggy${M}`)
await sleep(800)
await shot('merchant')
await go(`/home/category/people${M}`)
await sleep(800)
await shot('people')
await click('Meera S')
await sleep(800)
await shot('sheet-person', true)
await go(`/transactions${M}`)
await sleep(800)
await shot('transactions')
await js(`document.querySelector('main section button').click()`)
await sleep(800)
await shot('sheet-transaction', true)
await click('Change category')
await sleep(500)
await shot('sheet-transaction-category', true)
await go(`/transactions${M}`)
await sleep(500)
await js(`document.querySelector('main section button').click()`)
await sleep(500)
await click('Label')
await sleep(500)
await shot('sheet-transaction-label', true)
await go('/todo')
await sleep(800)
await shot('todo')
await go(`/labels${M}`)
await sleep(800)
await shot('labels')
await go(`/labels/1${M}`)
await sleep(800)
await shot('label-detail')

// States: no data, an error, waking, stale totals.
for (const state of ['empty', 'error', 'waking', 'stale']) {
  await go(`/home${M}`)
  await demoState(state)
  await sleep(state === 'waking' ? 2500 : 1500)
  await shot(`state-${state}`)
  if (state === 'empty') {
    for (const [hash, name] of [['/todo', 'todo'], [`/labels${M}`, 'labels'], [`/transactions${M}`, 'transactions'], [`/home/category/people${M}`, 'people']]) {
      await go(hash)
      await sleep(800)
      await shot(`state-empty-${name}`)
    }
  }
}
await demoState('normal')

writeFileSync(join(OUT, 'report.json'), JSON.stringify(report, null, 2))
const problems = Object.entries(report).filter(([, r]) => r.sideways || r.outside.length || r.clipped.length)
console.log(`shots: ${Object.keys(report).length}; with a finding: ${problems.length}`)
for (const [name, r] of problems) console.log(`  ${name}: ${r.sideways ? 'scrolls sideways; ' : ''}outside [${r.outside.join(' | ')}] clipped [${r.clipped.join(' | ')}]`)
ws.close()
done(0)
