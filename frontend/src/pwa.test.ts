import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildId, pwaOptions } from './pwa.ts'

test('the manifest has what an install needs', () => {
  const m = pwaOptions.manifest
  assert.ok(m)
  assert.equal(m.name, 'Flash Expense Tracker')
  assert.equal(m.short_name, 'Flash')
  assert.equal(m.display, 'standalone')
  assert.equal(m.start_url, '/')
  assert.equal(m.scope, '/')
  assert.equal(m.id, '/')
  assert.match(m.theme_color ?? '', /^#[0-9a-f]{6}$/)
  assert.equal(m.background_color, m.theme_color)
  const sizes = (m.icons ?? []).map((i) => `${i.sizes} ${i.purpose ?? 'any'}`)
  assert.deepEqual(sizes, ['192x192 any', '512x512 any', '512x512 maskable'])
})

test('updates wait for the owner', () => {
  assert.equal(pwaOptions.registerType, 'prompt')
})

test('the service worker caches the app shell only', () => {
  const wb = pwaOptions.workbox
  assert.ok(wb)
  assert.equal(wb.navigateFallback, 'index.html')
  const never = [
    'https://flash-expense-tracker.onrender.com/api/v1/summary?month=2026-11',
    'https://abcd.supabase.co/auth/v1/token?grant_type=password',
    'https://abcd.supabase.co/auth/v1/.well-known/jwks.json',
  ]
  for (const entry of wb.runtimeCaching ?? []) {
    const p = entry.urlPattern
    for (const url of never) {
      const hit =
        p instanceof RegExp ? p.test(url)
        : typeof p === 'string' ? url.startsWith(p)
        : Boolean(p({ url: new URL(url), sameOrigin: false } as never))
      assert.equal(hit, false, `runtimeCaching matches ${url}`)
    }
  }
})

test('build id: the first 7 characters of the commit, else dev', () => {
  assert.equal(buildId('0123456789abcdef0123456789abcdef01234567'), '0123456')
  assert.equal(buildId(' abc '), 'abc')
  assert.equal(buildId(undefined), 'dev')
  assert.equal(buildId(''), 'dev')
})
