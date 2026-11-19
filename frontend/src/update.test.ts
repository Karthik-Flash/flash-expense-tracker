import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { test } from 'node:test'
import { createElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

type Registered = (url: string, r: unknown) => void
type Mock = { waiting: boolean; updates: number; options?: { onRegisteredSW?: Registered } }

// A stand-in for virtual:pwa-register/react that reads this object.
const sw: Mock = { waiting: false, updates: 0 }
Object.assign(globalThis, { __pwaMock: sw })
const MOCK = `export function useRegisterSW(o) {
  const s = globalThis.__pwaMock
  s.options = o
  return { needRefresh: [s.waiting, () => {}], offlineReady: [false, () => {}], updateServiceWorker: async () => { s.updates++ } }
}`
registerHooks({
  resolve(specifier, context, next) {
    if (specifier === 'virtual:pwa-register/react') {
      return { url: `data:text/javascript,${encodeURIComponent(MOCK)}`, shortCircuit: true }
    }
    return next(specifier, context)
  },
})
const { UpdateBar } = await import('./update.ts')

type El = { type: unknown; props: { children?: ReactNode; onClick?: () => void } }

/** Renders the bar; returns its HTML and the element tree, whose handlers are the real ones. */
function render(): { html: string; tree: ReactNode } {
  let tree: ReactNode = null
  function Probe() {
    tree = UpdateBar({ aboveNav: true })
    return tree
  }
  return { html: renderToStaticMarkup(createElement(Probe)), tree }
}

function press(node: ReactNode, label: string): void {
  const find = (n: unknown): El | undefined => {
    if (Array.isArray(n)) return n.map(find).find(Boolean)
    if (!n || typeof n !== 'object') return undefined
    const el = n as El
    return el.type === 'button' && el.props.children === label ? el : find(el.props.children)
  }
  const button = find(node)
  assert.ok(button, `no ${label} button`)
  button.props.onClick?.()
}

test('hidden while no update is waiting', () => {
  const { html } = render()
  assert.match(html, /role="status"/)
  assert.doesNotMatch(html, /New version available/)
})

test('shows when an update is waiting; Reload calls the update once', async () => {
  sw.waiting = true
  const { html, tree } = render()
  assert.match(html, /New version available/)
  assert.match(html, />Reload</)
  assert.match(html, />Later</)
  press(tree, 'Reload')
  // Reload first waits for an owner action being sent (none here), then updates.
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(sw.updates, 1)
})

test('Later hides it', () => {
  sw.waiting = true
  press(render().tree, 'Later')
  assert.doesNotMatch(render().html, /New version available/)
  assert.equal(sw.updates, 1)
})

test('checks for an update on launch, on return to the foreground, and hourly', async () => {
  const calls: string[] = []
  const handlers: (() => void)[] = []
  let every = 0
  let tick = () => {}
  const doc = { visibilityState: 'visible', addEventListener: (type: string, f: () => void) => type === 'visibilitychange' && handlers.push(f) }
  const saved = { document: (globalThis as { document?: unknown }).document, setInterval: globalThis.setInterval }
  Object.assign(globalThis, {
    document: doc,
    setInterval: (f: () => void, ms: number) => {
      tick = f
      every = ms
      return 0
    },
  })
  try {
    const reg = {
      update: () => {
        calls.push(doc.visibilityState)
        // Offline: the failure is swallowed, the next check tries again.
        return calls.length === 1 ? Promise.reject(new TypeError('Failed to fetch')) : Promise.resolve()
      },
    }
    sw.options?.onRegisteredSW?.('/sw.js', reg)
    assert.equal(calls.length, 1)
    handlers.forEach((f) => f())
    assert.equal(calls.length, 2)
    doc.visibilityState = 'hidden'
    handlers.forEach((f) => f())
    assert.equal(calls.length, 2)
    assert.equal(every, 60 * 60 * 1000)
    tick()
    assert.equal(calls.length, 3)
    sw.options?.onRegisteredSW?.('/sw.js', undefined)
    await new Promise((r) => setTimeout(r, 0))
  } finally {
    Object.assign(globalThis, saved)
  }
})
