import assert from 'node:assert/strict'
import { test } from 'node:test'

import { backAction, closeTop, openSheets, pushBack } from './back.ts'
import { HOME, parseHash } from './view.ts'

test('5G-B: Back closes a sheet first, then steps out, then goes Home, then leaves', () => {
  const home = parseHash('#/home')
  assert.deepEqual(backAction(home, 1), { kind: 'close' })
  assert.deepEqual(backAction(parseHash('#/transactions?m=2026-11&txn=42'), 0), { kind: 'parent' })
  assert.deepEqual(backAction(parseHash('#/home?speed'), 0), { kind: 'parent' })
  assert.deepEqual(backAction(parseHash('#/home/category/food_drinks'), 0), { kind: 'parent' })
  for (const tab of ['transactions', 'insights', 'todo', 'labels']) {
    assert.deepEqual(backAction(parseHash(`#/${tab}`), 0), { kind: 'home', view: HOME }, tab)
  }
  assert.deepEqual(backAction(parseHash('#/transactions?m=2026-11'), 0).kind, 'home') // a month is not a layer
  assert.deepEqual(backAction(home, 0), { kind: 'leave' })
  assert.deepEqual(backAction(parseHash('#/home?m=2026-10'), 0), { kind: 'leave' })
})

test('5G-B: the topmost open sheet closes first, and a closed one is forgotten', () => {
  const closed: string[] = []
  const forgetA = pushBack(() => closed.push('a'))
  const forgetB = pushBack(() => closed.push('b'))
  assert.equal(openSheets(), 2)
  assert.equal(closeTop(), true)
  assert.deepEqual(closed, ['b'])
  forgetB() // the sheet unmounts after closing
  assert.equal(openSheets(), 1)
  forgetA()
  assert.equal(openSheets(), 0)
  assert.equal(closeTop(), false)
})
