import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  currentMonth,
  dayKey,
  dayLabel,
  fullLabel,
  istTime,
  istToIso,
  monthLabel,
  monthOf,
  shiftMonth,
  timeLabel,
  today,
} from './dates.ts'

test('IST day changes at 18:30 UTC', () => {
  assert.equal(dayKey('2026-11-16T18:29:59Z'), '2026-11-16')
  assert.equal(dayKey('2026-11-16T18:30:00Z'), '2026-11-17')
  assert.equal(dayLabel('2026-11-16T18:30:00Z'), 'Tue 17 Nov')
  assert.equal(timeLabel('2026-11-17T08:35:00.000Z'), '14:05')
  assert.equal(fullLabel('2026-11-17T08:35:00Z'), 'Tue 17 Nov 2026, 14:05')
})

test('IST month edges', () => {
  assert.equal(monthOf('2026-10-31T18:29:59Z'), '2026-10')  // 23:59:59 IST on 31 Oct
  assert.equal(monthOf('2026-10-31T18:30:00Z'), '2026-11')  // 00:00:00 IST on 1 Nov
  assert.equal(monthOf('2026-12-31T18:30:00Z'), '2027-01')
  assert.equal(currentMonth(Date.parse('2026-11-30T18:30:00Z')), '2026-12')
  assert.equal(today(Date.parse('2026-11-16T18:30:00Z')), '2026-11-17')
})

test('month labels and shifting', () => {
  assert.equal(monthLabel('2026-11'), 'Nov 2026')
  assert.equal(shiftMonth('2026-01', -1), '2025-12')
  assert.equal(shiftMonth('2026-12', 1), '2027-01')
  assert.equal(shiftMonth('2026-11', -13), '2025-10')
  assert.throws(() => monthLabel('2026-13'))
  assert.throws(() => dayLabel('yesterday'))
})

test('building UTC times from IST', () => {
  assert.equal(istToIso(2026, 11, 17, 14, 5), '2026-11-17T08:35:00.000Z')
  assert.equal(istToIso(2026, 11, 1), '2026-10-31T18:30:00.000Z')
})

test('one set of formats (D-113): day, moment, full, month', () => {
  const iso = '2026-11-17T08:35:00Z' // 14:05 IST
  assert.equal(dayLabel(iso), 'Tue 17 Nov')
  assert.equal(istTime(Date.parse(iso)), 'Tue 17 Nov, 14:05')
  assert.equal(fullLabel(iso), 'Tue 17 Nov 2026, 14:05')
  assert.equal(monthLabel('2026-11'), 'Nov 2026')
  assert.equal(istTime(null), '–')
  assert.equal(istTime(Date.parse('2026-11-16T18:30:00Z')), 'Tue 17 Nov, 00:00') // IST midnight
})
