import { useEffect, useState } from 'react'

import type { Device } from '../api/types.ts'
import { useAuth } from '../auth.ts'
import { enqueue, useOutbox } from '../data/outbox.ts'
import { useSnapshot } from '../data/store.ts'
import { dayLabel } from '../lib/dates.ts'
import { allowSms, connectPhone, loadSms, openAppInfo, startReading, syncNow, useSms } from '../native/sms.ts'
import { errorText, needsBatteryHint, PERIODS, smsStep, statusRows, type Period, type SmsStatus } from '../native/smsState.ts'
import { useApp } from '../state.tsx'
import { Button, Sheet } from '../ui.tsx'
import { Pending } from './Transactions.tsx'

const API_URL: string = import.meta.env.VITE_API_URL ?? ''

/** The status rows (also at the top of the Speed sheet). Codes and counts: safe to paste. */
export function SmsRows({ status }: { status: SmsStatus }) {
  return (
    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 tabular-nums">
      {statusRows(status).map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted">{term}</dt>
          <dd className="wrap-break-word">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Home, in the Android app only, until bank SMS are on: one quiet line that opens the sheet. */
export function SmsPrompt({ open }: { open: () => void }) {
  const sms = useSms()
  const step = smsStep(sms)
  if (step === 'browser' || step === 'on') return null
  const text = step === 'revoked' ? 'Bank SMS stopped: this phone was disconnected' : step === 'blocked' ? 'Bank SMS: Android did not allow access' : 'Read bank SMS on this phone'
  return (
    <p className="px-4 text-center text-xs text-muted">
      {text} ·{' '}
      <button type="button" className="inline-flex min-h-11 items-center px-1 text-accent" onClick={open}>
        {step === 'period' ? 'Choose' : 'Set up'}
      </button>
    </p>
  )
}

/** Bank SMS on this phone (`?sms`, 5A): permission, connect, the history period, status. In a
 *  browser: the phones that upload, and Revoke. Only bank SMS ever leave the phone. */
export function BankSmsSheet({ onClose }: { onClose: () => void }) {
  const sms = useSms()
  const { api } = useApp()
  const [load] = useSnapshot()
  const snapshot = load.status === 'ready' ? load.data : null
  const newest = snapshot?.sms?.newest_utc ?? null
  const auth = useAuth()
  const user = auth.status === 'in' ? auth.user : ''
  // The default follows the snapshot: from the newest message the server has, when it has one.
  const [picked, setPeriod] = useState<Period | null>(null)
  const period: Period = picked ?? (newest ? 'server' : 3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    void loadSms()
    const timer = window.setInterval(() => void loadSms(), 3000)
    return () => window.clearInterval(timer)
  }, [])
  const step = smsStep(sms)
  const act = (work: () => Promise<unknown>) => async () => {
    setBusy(true)
    setError('')
    try {
      await work()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }
  const connect = act(() => connectPhone(api, API_URL, user))
  const allow = act(async () => {
    const s = await allowSms()
    if (s.permission === 'granted' && !s.connected && !s.revoked) await connectPhone(api, API_URL, user)
  })
  return (
    <Sheet title="Bank SMS" onClose={onClose}>
      <div className="space-y-3 px-4 py-4 text-sm">
        <p className="text-muted">
          Flash reads only your banks' SMS on this phone and sends them to your account, where they become payments. Other messages are never read, kept or sent.
        </p>
        {step === 'browser' && <p>Bank SMS are read by the Flash app for Android. Here you can see your phones and revoke one.</p>}
        {step === 'permission' && (
          <>
            <p>Flash needs to read SMS, and to hear new ones, to find your bank messages.</p>
            <Button kind="primary" disabled={busy} onClick={() => void allow()}>Allow SMS access</Button>
          </>
        )}
        {step === 'blocked' && (
          <>
            <p className="font-medium">Android did not allow SMS access</p>
            <p className="text-muted">An app installed outside the Play Store needs one extra step:</p>
            <ol className="list-decimal space-y-1 pl-5">
              <li>Open App info (the button below).</li>
              <li>Tap ⋮ at the top right, then Allow restricted settings. If there is no ⋮, go on.</li>
              <li>Tap Permissions, then SMS, then Allow.</li>
              <li>Come back here.</li>
            </ol>
            <div className="flex flex-wrap gap-2">
              <Button kind="primary" onClick={() => void openAppInfo()}>Open App info</Button>
              <Button disabled={busy} onClick={() => void allow()}>Check again</Button>
            </div>
          </>
        )}
        {(step === 'connect' || step === 'revoked') && (
          <>
            <p>
              {step === 'revoked'
                ? 'This phone was disconnected from your account, so it stopped uploading. Connect it again to carry on.'
                : 'Connect this phone to your account. This needs a connection.'}
            </p>
            <Button kind="primary" disabled={busy} onClick={() => void connect()}>{step === 'revoked' ? 'Connect again' : 'Connect this phone'}</Button>
          </>
        )}
        {step === 'period' && (
          <fieldset className="space-y-1">
            <legend className="font-medium">Which messages to read first</legend>
            {newest && <PeriodChoice value="server" current={period} pick={setPeriod} label={`From your newest message on the server (${dayLabel(newest)})`} />}
            {PERIODS.map((months) => (
              <PeriodChoice key={months} value={months} current={period} pick={setPeriod} label={`The last ${months} months`} />
            ))}
            <div className="pt-2">
              <Button kind="primary" disabled={busy} onClick={() => void act(() => startReading(period, newest))()}>Start reading</Button>
            </div>
            <p className="text-xs text-muted">Messages the server already has are not counted twice.</p>
          </fieldset>
        )}
        {step === 'on' && (
          <>
            <p>
              On. New bank SMS are sent within a minute when the phone is online; a check runs every 6 hours too.
              {sms.queued + sms.awaiting > 0 && ` ${sms.queued + sms.awaiting} waiting on this phone.`}
            </p>
            {sms.lastError && <p className="text-danger">Last try: {errorText(sms.lastError)}.</p>}
            <Button disabled={busy} onClick={() => void act(syncNow)()}>Sync now</Button>
          </>
        )}
        {needsBatteryHint(sms) && (
          <div className="rounded-lg border border-line px-3 py-2">
            <p>
              For uploads in the background, set Flash's battery use to Unrestricted. On Samsung: App info, Battery, Unrestricted.
            </p>
            <div className="mt-2">
              <Button onClick={() => void openAppInfo()}>Open App info</Button>
            </div>
          </div>
        )}
        {error && <p className="text-danger" role="alert">{error}</p>}
        {sms.available && (
          <section>
            <h3 className="text-xs font-medium text-muted">Status</h3>
            <SmsRows status={sms} />
          </section>
        )}
        <Phones devices={snapshot?.devices ?? []} mine={sms.deviceId} />
      </div>
    </Sheet>
  )
}

function PeriodChoice({ value, current, pick, label }: { value: Period; current: Period; pick: (p: Period) => void; label: string }) {
  return (
    <label className="flex min-h-11 items-center gap-3">
      <input type="radio" name="sms-period" checked={current === value} onChange={() => pick(value)} className="size-5 accent-accent" />
      <span>{label}</span>
    </label>
  )
}

/** The phones of this account, from the snapshot. Revoke goes through the outbox (D-091). */
function Phones({ devices, mine }: { devices: Device[]; mine: string | undefined }) {
  const { ops } = useOutbox()
  if (!devices.length) return null
  return (
    <section>
      <h3 className="text-xs font-medium text-muted">Phones</h3>
      <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
        {devices.map((d) => {
          const path = `/devices/${d.device_id}`
          const op = ops.filter((o) => o.path === path).at(-1)
          return (
            <li key={d.device_id} className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="block wrap-anywhere">
                  {d.name}
                  {d.device_id === mine && <span className="text-muted"> · this phone</span>}
                </span>
                <span className="block text-xs text-muted">
                  {d.revoked_utc ? 'Revoked' : d.last_seen_utc ? `Last upload ${dayLabel(d.last_seen_utc)}` : 'No upload yet'}
                </span>
              </span>
              {op ? (
                <Pending op={op} />
              ) : (
                !d.revoked_utc && (
                  <button
                    type="button"
                    className="min-h-11 px-1 text-sm text-accent"
                    onClick={() => void enqueue({ kind: 'Phone', item: d.name, choice: 'Revoked', method: 'DELETE', path, body: null, targets: {} })}
                  >
                    Revoke
                  </button>
                )
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
