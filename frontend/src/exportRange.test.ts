import assert from 'node:assert/strict'
import { test } from 'node:test'

import { fileName, rangeOf, spanOf } from './exportRange.ts'

test('5F: export ranges are IST days, both ends included', () => {
  const now = Date.parse('2026-03-15T20:00:00Z') // 16 Mar 01:30 IST
  assert.deepEqual(rangeOf('month', ['', ''], now), ['2026-03-01', '2026-03-16'])
  assert.deepEqual(rangeOf('last', ['', ''], now), ['2026-02-01', '2026-02-28'])
  assert.deepEqual(rangeOf('three', ['', ''], now), ['2026-01-01', '2026-03-16'])
  assert.deepEqual(rangeOf('year', ['', ''], now), ['2026-01-01', '2026-03-16'])
  assert.deepEqual(rangeOf('custom', ['2026-02-10', '2026-01-05'], now), ['2026-01-05', '2026-02-10']) // in order
  assert.deepEqual(rangeOf('last', ['', ''], Date.parse('2026-01-10T06:00:00Z')), ['2025-12-01', '2025-12-31'])
  assert.deepEqual(rangeOf('last', ['', ''], Date.parse('2024-03-10T06:00:00Z')), ['2024-02-01', '2024-02-29'])
  assert.equal(fileName('2026-01-01', '2026-01-31', 'xlsx'), 'flash-2026-01-01-to-2026-01-31.xlsx')
})

test('analytics spans end this IST month and hold 1, 3, 6 or 12 months', () => {
  const now = Date.parse('2026-01-31T20:00:00Z') // already 1 Feb in IST
  assert.deepEqual(spanOf('month', ['', ''], now), ['2026-02', '2026-02'])
  assert.deepEqual(spanOf('3', ['', ''], now), ['2025-12', '2026-02'])
  assert.deepEqual(spanOf('12', ['', ''], now), ['2025-03', '2026-02'])
  assert.deepEqual(spanOf('custom', ['2026-05', '2026-01'], now), ['2026-01', '2026-05'])
})
