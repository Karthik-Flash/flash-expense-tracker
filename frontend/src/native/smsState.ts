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
  /** 5B-2 (D-142): "Payments" notifications; absent from an app before 5B-2. */
  notifications?: 'granted' | 'denied' | 'prompt'
  /** Signed out with the cursor kept: the same login reconnects by itself (D-143). */
  signedOut?: boolean
  /** When the newest bank SMS was seen on this phone (ms). */
  lastSmsSeenMs?: number
  /** Android's app standby bucket (UsageStatsManager), Android 9+. */
  standbyBucket?: number
  /** The newest events on the phone: codes and counts, never a message. */
  events?: { at: number; type: string; detail: string }[]
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
  offline: 'no connection, or the server took too long',
  server_error: "the server didn't answer (it may be waking up)",
  rejected: 'the server refused the upload',
  invalid: 'one message was refused and left out',
  revoked: 'this phone was disconnected on the server',
  unauthorised: 'the server does not know this phone',
}

/** Android's app standby bucket in plain words (developer.android.com, App Standby Buckets). */
export function bucketText(bucket: number | undefined): string {
  if (bucket === undefined) return ''
  if (bucket <= 10) return 'in use'
  if (bucket <= 20) return 'used often'
  if (bucket <= 30) return 'used now and then: uploads may wait a little'
  if (bucket <= 40) return 'rarely used: Android delays uploads'
  return 'restricted: Android blocks uploads in the background'
}

/** A short code in plain words, for the sheet. */
export function errorText(code: string): string {
  return code ? (ERRORS[code] ?? code) : ''
}

/** The phone, in one word: connected, disconnected (Reconnect), signed out, not connected. */
export function phoneText(s: SmsStatus): string {
  if (s.revoked) return 'disconnected'
  if (s.connected) return 'connected'
  return s.signedOut ? 'signed out (reconnects at sign-in)' : 'not connected'
}

/** The status block of the Bank SMS and Speed sheets (5B-2, D-142). Plain words, times in
 *  IST, codes and counts only: safe to paste. */
export function statusRows(s: SmsStatus): [string, string][] {
  if (!s.available) return [['Bank SMS', 'Android app only']]
  const permission = { granted: 'allowed', denied: 'not allowed', prompt: 'not asked yet' }[s.permission]
  const notify = s.notifications ? { granted: 'on', denied: 'off', prompt: 'not asked yet' }[s.notifications] : '–'
  const upload = s.lastUpload ? `${istTime(s.lastUpload.at)}, ${s.lastUpload.stored} new` : '–'
  const bucket = bucketText(s.standbyBucket)
  const battery = (s.batteryUnrestricted ? 'unrestricted' : 'optimised') + (bucket ? `; ${bucket}` : '')
  const rows: [string, string][] = [
    ['SMS permission', permission],
    ['Notifications', notify],
    ['Battery', battery],
    ['Last bank SMS seen', s.lastSmsSeenMs ? istTime(s.lastSmsSeenMs) : '–'],
    ['Last upload', upload],
    ['Waiting on phone', String(s.queued + s.awaiting)],
    ['Last problem', errorText(s.lastError) || 'none'],
    ['This phone', phoneText(s)],
  ]
  if (s.historyFromMs) rows.push(['Reading since', istTime(s.historyFromMs)])
  if (s.dropped) rows.push(['Not in inbox, dropped', String(s.dropped)])
  return rows
}

/** One event line for the on-phone log: time (IST), type, detail. */
export function eventText(e: { at: number; type: string; detail: string }): string {
  return [istTime(e.at), e.type.replaceAll('_', ' '), e.detail].filter(Boolean).join(' · ')
}

/** Show the battery hint: connected, and Android may stop background work. */
export function needsBatteryHint(s: SmsStatus): boolean {
  return s.available && s.connected && !s.revoked && !s.batteryUnrestricted
}
