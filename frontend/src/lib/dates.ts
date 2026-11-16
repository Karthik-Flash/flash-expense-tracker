// Times arrive as UTC ISO strings; they are shown in IST, a fixed +05:30 (D-002).

const IST_OFFSET_MS = 330 * 60_000
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** The IST wall clock as a Date read with getUTC*. */
function ist(iso: string): Date {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) throw new Error('not an ISO time')
  return new Date(ms + IST_OFFSET_MS)
}

const two = (n: number) => String(n).padStart(2, '0')

/** "Tue 17 Nov" */
export function dayLabel(iso: string): string {
  const d = ist(iso)
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
}

/** "14:05" */
export function timeLabel(iso: string): string {
  const d = ist(iso)
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`
}

/** "Tue 17 Nov 2026, 14:05" */
export function fullLabel(iso: string): string {
  return `${dayLabel(iso)} ${ist(iso).getUTCFullYear()}, ${timeLabel(iso)}`
}

/** "2026-11-17": the IST day, for grouping. */
export function dayKey(iso: string): string {
  const d = ist(iso)
  return `${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())}`
}

/** "2026-11": the IST month of a time. */
export function monthOf(iso: string): string {
  return dayKey(iso).slice(0, 7)
}

function parseMonth(key: string): [number, number] {
  const m = /^(\d{4})-(\d{2})$/.exec(key)
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) throw new Error('month must look like 2026-11')
  return [Number(m[1]), Number(m[2])]
}

/** "Nov 2026" */
export function monthLabel(key: string): string {
  const [year, month] = parseMonth(key)
  return `${MONTHS[month - 1]} ${year}`
}

/** shiftMonth("2026-01", -1) -> "2025-12" */
export function shiftMonth(key: string, delta: number): string {
  const [year, month] = parseMonth(key)
  const index = year * 12 + (month - 1) + delta
  return `${Math.floor(index / 12)}-${two((index % 12) + 1)}`
}

/** The IST month of a moment (now by default). */
export function currentMonth(now: number = Date.now()): string {
  return monthOf(new Date(now).toISOString())
}

/** UTC ISO string of an IST wall-clock time: for building data. */
export function istToIso(year: number, month: number, day: number, hour = 0, minute = 0): string {
  return new Date(Date.UTC(year, month - 1, day, hour, minute) - IST_OFFSET_MS).toISOString()
}
