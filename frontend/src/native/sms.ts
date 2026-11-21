// Bank SMS on this phone (5A, D-122, D-124): the Android plugin "FlashSms"
// (mobile/android .../FlashSmsPlugin.kt). In a browser there is no plugin and the status says
// so. The device token passes through here once (connectPhone) and is never stored here.

import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'
import { useSyncExternalStore } from 'react'

import type { Api } from '../api/client.ts'
import { NOT_NATIVE, periodStart, type Period, type SmsStatus } from './smsState.ts'

export interface FlashSms {
  status(): Promise<SmsStatus>
  requestSms(): Promise<SmsStatus>
  openAppInfo(): Promise<void>
  connect(options: { token: string; apiUrl: string; user: string }): Promise<SmsStatus>
  disconnect(): Promise<SmsStatus>
  startHistory(options: { sinceMs: number }): Promise<SmsStatus>
  syncNow(): Promise<SmsStatus>
  addListener(event: 'uploaded', listener: (e: { stored: number }) => void): Promise<PluginListenerHandle>
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
 *  disconnected first: its SMS never go to someone else's account. */
export async function startSms(refresh: () => Promise<void>, user: string): Promise<void> {
  if (!plugin) return
  const s = await loadSms()
  if (s.connected && s.user && s.user !== user) set(await plugin.disconnect())
  if (wired) return
  wired = await plugin.addListener('uploaded', (e) => {
    void loadSms()
    if (e.stored > 0) void refresh()
  })
}

export async function allowSms(): Promise<SmsStatus> {
  return plugin ? set(await plugin.requestSms()) : status
}

/** Registers this phone (online, the login token) and hands its device token to the plugin. */
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

export async function syncNow(): Promise<SmsStatus> {
  return plugin ? set(await plugin.syncNow()) : status
}

export async function openAppInfo(): Promise<void> {
  await plugin?.openAppInfo()
}

/** Sign-out (D-122): revoke this phone on the server (best effort, 5 s), then wipe its token,
 *  queue and status. Direct, not through the outbox: sign-out deletes the outbox. */
export async function signOutPhone(api: Api): Promise<void> {
  if (!plugin) return
  const s = await loadSms()
  if (s.connected && !s.revoked && s.deviceId) {
    try {
      await api.send({ op_id: crypto.randomUUID(), method: 'DELETE', path: `/devices/${s.deviceId}`, body: null, defer: false }, AbortSignal.timeout(5000))
    } catch {
      // Offline: the token is wiped here anyway; revoke the phone from another device.
    }
  }
  try {
    set(await plugin.disconnect())
  } catch {
    // nothing to wipe
  }
}

/** Tests: a stand-in plugin (null: a browser). */
export function setPluginForTests(fake: FlashSms | null): void {
  plugin = fake
  wired = null
  status = NOT_NATIVE
}
