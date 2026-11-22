// Export (5F, D-146): the date ranges the Export section offers, as IST days, and a file name.
// Pure: tested in Node. The server builds the file; this only names the days.

import { shiftMonth, today } from './lib/dates.ts'

export type Preset = 'month' | 'last' | 'three' | 'year' | 'custom'

export const PRESETS: [Preset, string][] = [
  ['month', 'This month'],
  ['last', 'Last month'],
  ['three', 'Last 3 months'],
  ['year', 'This year'],
  ['custom', 'Choose dates'],
]

function lastDay(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return `${month}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, '0')}`
}

/** [start, end] IST days, both included; custom: the owner's two dates, in order. */
export function rangeOf(preset: Preset, custom: [string, string], now = Date.now()): [string, string] {
  const day = today(now)
  const month = day.slice(0, 7)
  if (preset === 'month') return [`${month}-01`, day]
  if (preset === 'last') {
    const last = shiftMonth(month, -1)
    return [`${last}-01`, lastDay(last)]
  }
  if (preset === 'three') return [`${shiftMonth(month, -2)}-01`, day]
  if (preset === 'year') return [`${day.slice(0, 4)}-01-01`, day]
  const [a, b] = custom
  return a <= b ? [a, b] : [b, a]
}

export const fileName = (start: string, end: string, format: 'csv' | 'xlsx') => `flash-${start}-to-${end}.${format}`

export const MIME = { csv: 'text/csv', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } as const

/** Analytics (premium B, D-148): the IST months of a range, oldest first. */
export type Span = 'month' | '3' | '6' | '12' | 'custom'

export const SPANS: [Span, string][] = [
  ['month', 'This month'],
  ['3', '3 months'],
  ['6', '6 months'],
  ['12', '12 months'],
  ['custom', 'Choose months'],
]

/** [first, last] IST months, both included; custom: the owner's two months, in order. */
export function spanOf(span: Span, custom: [string, string], now = Date.now()): [string, string] {
  const month = today(now).slice(0, 7)
  if (span === 'custom') return custom[0] <= custom[1] ? custom : [custom[1], custom[0]]
  return [shiftMonth(month, span === 'month' ? 0 : 1 - Number(span)), month]
}
