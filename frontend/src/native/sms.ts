// Bank SMS on this phone (5A, D-122, D-124; 5B-2, D-142, D-143): the Android plugin "FlashSms"
// (mobile/android .../FlashSmsPlugin.kt). In a browser there is no plugin and the status says
// so. The device token passes through here once (connectPhone) and is never stored here.

import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'
import { useSyncExternalStore } from 'react'

import type { Api } from '../api/client.ts'
import { NOT_NATIVE, periodStart, type Period, type SmsStatus } from './smsState.ts'

/** A notification tap (5B-2, D-142): open this payment's sheet, or its category list. */
export interface OpenAt {
  txnId: number
  act: 'sheet' | 'category'
}

export interface FlashSms {
  status(): Promise<SmsStatus>
  requestSms(): Promise<SmsStatus>
  requestNotifications(): Promise<SmsStatus>
  openAppInfo(): Promise<void>
  openSleepingApps(): Promise<{ opened: boolean }>
  connect(options: { token: string; apiUrl: string; user: string }): Promise<SmsStatus>
  /** keep: sign-out (the cursor, the queue and the login stay); else everything goes. */
  disconnect(options?: { keep?: boolean }): Promise<SmsStatus>
  startHistory(options: { sinceMs: number }): Promise<SmsStatus>
  syncNow(): Promise<SmsStatus>
  takeOpen(): Promise<{ open: OpenAt | null }>
  diagnostics(): Promise<{ text: string }>
  shareFile(options: { name: string; mime: string; base64: string }): Promise<{ shared: boolean }>
  addListener(event: 'uploaded', listener: (e: { stored: number }) => void): Promise<PluginListenerHandle>
  addListener(event: 'open', listener: (e: OpenAt) => void): Promise<PluginListenerHandle>
}

let plugin: FlashSms | null = Capacitor.isNativePlatform() ? registerPlugin<FlashSms>('FlashSms') : null
let status: SmsStatus = NOT_NATIVE
let wired: PluginListenerHandle | null = null
const listeners = new Set<() => void>()

/** The Android app: no service worker there, updates come as a new APK (D-125). */
export const isNativeApp = () => plugin !== null

function set(next: SmsStatus): SmsStatus {
  status = next
  for (const listener of listeners) listener()
  return next
}

const subscribe = (onChange: () => void) => {
  listeners.add(onChange)
  return () => void listeners.delete(onChange)
}

export function useSms(): SmsStatus {
  return useSyncExternalStore(subscribe, () => status)
}

export async function loadSms(): Promise<SmsStatus> {
  if (!plugin) return status
  try {
    return set(await plugin.status())
  } catch {
    return status
  }
}

/** After login: an upload that stored something refreshes the snapshot, so new payments show
 *  within seconds while the app is open (3.6). A phone connected by another login is
 *  disconnected first: its SMS never go to someone else's account. The same login after a
 *  sign-out reconnects by itself and keeps its place (5B-2, D-143): no new Bank SMS setup.
 *  `open`: a notification tap, at a cold start (now) or a warm one (later). */
export async function startSms(
  refresh: () => Promise<void>,
  user: string,
  reconnect?: () => Promise<unknown>,
  open?: (at: OpenAt) => void,
): Promise<void> {
  if (!plugin) return
  const s = await loadSms()
  if (s.user && s.user !== user) set(await plugin.disconnect())
  else if (s.user === user && !s.connected && s.cursorMs !== undefined && s.permission === 'granted' && reconnect) {
    await reconnect().catch(() => {}) // offline: the next start tries again; the queue waits
  }
  if (open) {
    const first = await plugin.takeOpen().catch(() => ({ open: null }))
    if (first.open) open(first.open)
  }
  if (wired) return
  wired = await plugin.addListener('uploaded', (e) => {
    void loadSms()
    if (e.stored > 0) void refresh()
  })
  if (open) await plugin.addListener('open', (e) => open(e))
}

export async function allowSms(): Promise<SmsStatus> {
  return plugin ? set(await plugin.requestSms()) : status
}

/** Android 13+: the "Payments" notifications (D-142). Denied: everything else still works. */
export async function allowNotifications(): Promise<SmsStatus> {
  return plugin ? set(await plugin.requestNotifications()) : status
}

/** Registers this phone (online, the login token) and hands its device token to the plugin.
 *  Also Reconnect: the cursor and the queue stay, nothing is read twice (D-143). */
export async function connectPhone(api: Api, apiUrl: string, user: string): Promise<SmsStatus> {
  if (!plugin) return status
  const s = await loadSms()
  if (!s.deviceId) throw new Error('This phone has no id yet. Close the app and open it again.')
  const { token } = await api.registerDevice(s.deviceId, s.deviceName || 'Android phone')
  return set(await plugin.connect({ token, apiUrl, user }))
}

export async function startReading(period: Period, newestUtc: string | null | undefined): Promise<SmsStatus> {
  return plugin ? set(await plugin.startHistory({ sinceMs: periodStart(period, newestUtc) })) : status
}

/** Sync now: the inbox from where it was read up to, and an upload, at once (never history). */
export async function syncNow(): Promise<SmsStatus> {
  return plugin ? set(await plugin.syncNow()) : status
}

export async function openAppInfo(): Promise<void> {
  await plugin?.openAppInfo()
}

/** Samsung "Never auto sleeping apps", else Android's battery list (opened, never requested). */
export async function openSleepingApps(): Promise<void> {
  await plugin?.openSleepingApps()
}

/** "Copy diagnostics": the status and the last 100 events, codes and counts only (D-142). */
export async function diagnostics(): Promise<string> {
  return plugin ? (await plugin.diagnostics()).text : ''
}

/** 5F (D-146): a file through the Android share sheet; false in a browser. */
export async function shareFile(name: string, mime: string, base64: string): Promise<boolean> {
  if (!plugin) return false
  return (await plugin.shareFile({ name, mime, base64 })).shared
}

/** Sign-out (D-122; 5B-2, D-143): revoke this phone on the server (best effort, 5 s), then
 *  drop its token. The cursor and the queue stay for the same login, which reconnects by
 *  itself at its next sign-in; another login wipes them first. Direct, not through the outbox:
 *  sign-out deletes the outbox. */
export async function signOutPhone(api: Api): Promise<void> {
  if (!plugin) return
  const s = await loadSms()
  if (s.connected && !s.revoked && s.deviceId) {
    try {
      await api.send({ op_id: crypto.randomUUID(), method: 'DELETE', path: `/devices/${s.deviceId}`, body: null, defer: false }, AbortSignal.timeout(5000))
    } catch {
      // Offline: the token is dropped here anyway; revoke the phone from another device.
    }
  }
  try {
    set(await plugin.disconnect({ keep: true }))
  } catch {
    // nothing to drop
  }
}

/** Tests: a stand-in plugin (null: a browser). */
export function setPluginForTests(fake: FlashSms | null): void {
  plugin = fake
  wired = null
  status = NOT_NATIVE
}
