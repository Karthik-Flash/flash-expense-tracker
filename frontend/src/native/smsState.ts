// What the Bank SMS sheet and the Speed sheet show about bank SMS on this phone (5A, D-124).
// Pure: the status comes from the Android plugin (native/sms.ts); tests run it in Node.

import { istTime } from '../lib/dates.ts'

/** The plugin's status: codes and counts only, never a message. */
export interface SmsStatus {
  /** False in a browser: bank SMS are read only by the Android app. */
  available: boolean
  deviceId?: string
  deviceName?: string
  /** denied: Android said no for good, or "Restricted setting" (sideloaded, Android 15+). */
  permission: 'granted' | 'denied' | 'prompt'
  connected: boolean
  /** The login that connected this phone; another login disconnects it first. */
  user?: string
  /** The server revoked this phone (or does not know its token): uploads stopped. */
  revoked: boolean
  /** Bank messages on the phone, waiting to upload. */
  queued: number
  /** Live messages waiting for their inbox row. */
  awaiting: number
  /** Live messages dropped after 24 h without an inbox row. */
  dropped: number
  lastUpload?: { at: number; stored: number }
  lastAttempt?: { at: number; result: string }
  /** The last failure as a short code: offline, server_error, rejected, revoked, unauthorised. */
  lastError: string
  /** Inbox date of the newest message queued; absent until a period is chosen. */
  cursorMs?: number
  historyFromMs?: number
  batteryUnrestricted: boolean
  manufacturer: string
  /** The permission dialog was just shown (requestSms). */
  asked?: boolean
}

export const NOT_NATIVE: SmsStatus = {
  available: false,
  permission: 'prompt',
  connected: false,
  revoked: false,
  queued: 0,
  awaiting: 0,
  dropped: 0,
  lastError: '',
  batteryUnrestricted: true,
  manufacturer: '',
}

/** Where the sheet is: what the owner does next. */
export type Step = 'browser' | 'permission' | 'blocked' | 'connect' | 'revoked' | 'period' | 'on'

export function smsStep(s: SmsStatus): Step {
  if (!s.available) return 'browser'
  if (s.permission === 'denied') return 'blocked'
  if (s.permission !== 'granted') return 'permission'
  if (s.revoked) return 'revoked'
  if (!s.connected) return 'connect'
  if (s.cursorMs === undefined) return 'period'
  return 'on'
}

/** The first run offers these; the default is from the newest message the server has. */
export const PERIODS = [3, 6, 12] as const
export type Period = 'server' | (typeof PERIODS)[number]
const DAY_MS = 86_400_000

/** Where the first scan starts (ms): the server's newest message minus a day (repeats are
 *  harmless: the server says "duplicate"), or 3, 6 or 12 calendar months back. */
export function periodStart(period: Period, newestUtc: string | null | undefined, now = Date.now()): number {
  if (period === 'server') {
    const newest = newestUtc ? Date.parse(newestUtc) : NaN
    if (!Number.isNaN(newest)) return Math.max(0, newest - DAY_MS)
    return periodStart(3, null, now)
  }
  const d = new Date(now)
  d.setUTCMonth(d.getUTCMonth() - period)
  return d.getTime()
}

const ERRORS: Record<string, string> = {
  offline: 'no connection',
  server_error: "the server didn't answer",
  rejected: 'the server refused the upload',
  revoked: 'this phone was disconnected on the server',
  unauthorised: 'the server does not know this phone',
}

/** A short code in plain words, for the sheet. */
export function errorText(code: string): string {
  return code ? (ERRORS[code] ?? code) : ''
}

/** The status block of the Bank SMS and Speed sheets. Codes stay codes: safe to paste. */
export function statusRows(s: SmsStatus): [string, string][] {
  if (!s.available) return [['Bank SMS', 'Android app only']]
  const permission = { granted: 'allowed', denied: 'not allowed', prompt: 'not asked yet' }[s.permission]
  const phone = s.revoked ? 'disconnected' : s.connected ? 'connected' : 'not connected'
  const upload = s.lastUpload ? `${istTime(s.lastUpload.at)}, ${s.lastUpload.stored} new` : '–'
  const attempt = s.lastAttempt ? `${istTime(s.lastAttempt.at)}, ${s.lastAttempt.result}` : '–'
  const rows: [string, string][] = [
    ['SMS permission', permission],
    ['This phone', phone],
    ['Waiting on phone', String(s.queued + s.awaiting)],
    ['Last upload', upload],
    ['Last attempt', attempt],
    ['Last error', s.lastError || '–'],
  ]
  if (s.historyFromMs) rows.push(['Reading since', istTime(s.historyFromMs)])
  if (s.dropped) rows.push(['Not in inbox, dropped', String(s.dropped)])
  rows.push(['Battery', s.batteryUnrestricted ? 'unrestricted' : 'optimised'])
  return rows
}

/** Show the battery hint: connected, and Android may stop background work. */
export function needsBatteryHint(s: SmsStatus): boolean {
  return s.available && s.connected && !s.revoked && !s.batteryUnrestricted
}
