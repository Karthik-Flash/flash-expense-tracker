import assert from 'node:assert/strict'
import { test } from 'node:test'

import { HOME, parseHash, parentOf, stack, toHash, type View } from './view.ts'

test('view -> URL -> view keeps every part', () => {
  const views: View[] = [
    HOME,
    { ...HOME, month: '2026-10' },
    { ...HOME, path: ['category', 'food_drinks'], month: '2026-11' },
    { ...HOME, path: ['category', 'people', 'Rohit V'], month: '2026-11', txn: 1042 },
    { ...HOME, path: ['category', 'shopping', 'A/B Stores? #1 & 50%'] },
    { ...HOME, path: ['category', 'people', 'ramesh.k@okaxis'] },
    { ...HOME, tab: 'transactions', month: '2025-12', category: 'travel', label: 3, q: ' tea  stall+1 & co ', txn: 7 },
    { ...HOME, tab: 'transactions', q: 'Café ₹' },
    { ...HOME, tab: 'todo' },
    { ...HOME, tab: 'labels', path: ['12'], txn: 1001 },
    { ...HOME, tab: 'dev', path: ['logos'] },
  ]
  for (const view of views) {
    const hash = toHash(view)
    assert.deepEqual(parseHash(hash), view, hash)
    assert.equal(toHash(parseHash(hash)), hash)
  }
})

test('URL -> view -> URL cleans what it cannot use', () => {
  const cases: [string, string][] = [
    ['', '#/home'],
    ['#', '#/home'],
    ['#/', '#/home'],
    ['#/nowhere/x?m=2026-11', '#/home?m=2026-11'],
    ['#/home?m=2026-13&txn=abc&label=0', '#/home'],
    ['#/transactions?txn=-4&q=', '#/transactions'],
    ['#/home/category/bad%E0%A4', '#/home/category/bad%25E0%25A4'],
    ['#/labels/3?zzz=1', '#/labels/3'],
  ]
  for (const [hash, clean] of cases) assert.equal(toHash(parseHash(hash)), clean, hash)
})

test('Back closes the sheet, then the detail, then reaches the tab root', () => {
  const deep = parseHash('#/home/category/people/Rohit%20V?m=2026-10&txn=1042')
  assert.deepEqual(stack(deep).map(toHash), [
    '#/home?m=2026-10',
    '#/home/category/people?m=2026-10',
    '#/home/category/people/Rohit%20V?m=2026-10',
    '#/home/category/people/Rohit%20V?m=2026-10&txn=1042',
  ])
  assert.deepEqual(stack(parseHash('#/labels/2?txn=5')).map(toHash), ['#/labels', '#/labels/2', '#/labels/2?txn=5'])
  const filtered = parseHash('#/transactions?cat=travel&q=ira&txn=9')
  assert.equal(toHash(parentOf(filtered)!), '#/transactions?cat=travel&q=ira')
  assert.equal(parentOf(parseHash('#/transactions?cat=travel')), null)
  assert.equal(parentOf(parseHash('#/dev/logos')), null)
})

test('app-wide sheets live in the URL and close first on Back', () => {
  const speed = parseHash('#/home?m=2026-11&speed')
  assert.equal(speed.sheet, 'speed')
  assert.equal(toHash(speed), '#/home?m=2026-11&speed')
  assert.equal(toHash(parentOf(speed)!), '#/home?m=2026-11')
  assert.equal(toHash(parseHash('#/home?speed')), '#/home?speed')
  assert.equal(parseHash('#/todo?unsaved').sheet, 'unsaved')
  assert.equal(parseHash('#/todo?nothing').sheet, null)
  assert.deepEqual(stack(parseHash('#/transactions?txn=9&unsaved')).map(toHash), ['#/transactions', '#/transactions?txn=9', '#/transactions?txn=9&unsaved'])
})
