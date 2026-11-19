/// <reference lib="dom" />
/// <reference types="vite-plugin-pwa/react" />
import { createElement as h, useSyncExternalStore } from 'react'
import { useRegisterSW } from 'virtual:pwa-register/react'

import { waitForSending } from './data/outbox.ts'

// Plain createElement, not JSX, so node --test can load this file (update.test.ts).

const HOUR = 60 * 60 * 1000

/** Look for a new service worker on launch, on return to the foreground, and hourly (D-085). */
function watchForUpdates(_url: string, r: ServiceWorkerRegistration | undefined): void {
  if (!r) return
  // Offline or a failed fetch: nothing to do, the next check tries again.
  const check = () => void r.update().catch(() => {})
  check()
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check()
  })
  setInterval(check, HOUR)
}

// "Later" lasts until the next launch: a module flag, gone when the page loads again.
let later = false
const listeners = new Set<() => void>()
const subscribe = (f: () => void) => {
  listeners.add(f)
  return () => void listeners.delete(f)
}
const isLater = () => later
function hideUntilNextLaunch(): void {
  later = true
  listeners.forEach((f) => f())
}

const BUTTON = 'min-h-11 rounded-lg border px-3 text-sm font-medium wrap-break-word'

/**
 * "New version available" with Reload and Later, above the bottom navigation when there is one.
 * Mount once: the hook registers the service worker. The new worker waits; only Reload
 * activates it, and the page then reloads once. The app never reloads by itself. Reload first
 * waits (at most 10 s) for an owner action being sent (D-091).
 */
export function UpdateBar({ aboveNav }: { aboveNav: boolean }) {
  const {
    needRefresh: [waiting],
    updateServiceWorker,
  } = useRegisterSW({ onRegisteredSW: watchForUpdates })
  const hidden = useSyncExternalStore(subscribe, isLater, isLater)
  const bottom = aboveNav ? 'bottom-[calc(3.5rem+1px+env(safe-area-inset-bottom)+0.5rem)]' : 'bottom-[calc(env(safe-area-inset-bottom)+0.5rem)]'
  // The live region is always there, so a screen reader announces the text when it appears.
  return h(
    'div',
    { role: 'status', className: `pointer-events-none fixed inset-x-0 z-30 px-4 ${bottom}` },
    waiting &&
      !hidden &&
      h(
        'div',
        { className: 'pointer-events-auto mx-auto flex max-w-[448px] flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line bg-surface px-4 py-2' },
        h('span', { className: 'mr-auto text-sm font-medium' }, 'New version available'),
        h(
          'span',
          { className: 'flex flex-wrap gap-2' },
          h('button', { type: 'button', onClick: hideUntilNextLaunch, className: `${BUTTON} border-line bg-surface text-ink` }, 'Later'),
          h('button', { type: 'button', onClick: () => void waitForSending(10_000).then(() => updateServiceWorker(true)), className: `${BUTTON} border-accent bg-accent text-on-accent` }, 'Reload'),
        ),
      ),
  )
}
