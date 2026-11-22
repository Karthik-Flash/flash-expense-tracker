import { useEffect, useState } from 'react'

import { readBoot } from '../boot.ts'
import { readTimings, type Timing } from '../data/local.ts'
import { failedOps, useOutbox, waiting } from '../data/outbox.ts'
import { speedRows } from '../data/store.ts'
import { istTime } from '../lib/dates.ts'
import { loadSms, useSms } from '../native/sms.ts'
import { needsBatteryHint } from '../native/smsState.ts'
import { useNav } from '../state.tsx'
import { Sheet } from '../ui.tsx'
import { SmsRows } from './BankSms.tsx'

/** The outbox first (D-107): what is on the phone, what failed, the last try and success. */
function SyncBlock() {
  const s = useOutbox()
  const attempt = s.lastAttempt
  return (
    <>
      <h3 className="text-xs font-medium text-muted">Sync</h3>
      <dl className="mt-1 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-0.5 tabular-nums [&_dt]:wrap-break-word">
        <dt className="text-muted">Saved on phone</dt>
        <dd>{waiting(s.ops)}</dd>
        <dt className="text-muted">Failed</dt>
        <dd>{failedOps(s.ops).length}</dd>
        <dt className="text-muted">Last attempt</dt>
        <dd>{attempt ? `${istTime(attempt.at)}, ${attempt.result}` : '–'}</dd>
        <dt className="text-muted">Last success</dt>
        <dd>{istTime(s.lastSuccess)}</dd>
        <dt className="text-muted">Last error</dt>
        <dd className="wrap-break-word">{s.signIn ? 'needs_sign_in: sign in to sync' : s.lastError || '–'}</dd>
      </dl>
    </>
  )
}


/** Bank SMS on this phone first (5A): permission, queue, last upload, last error. In a
 *  browser only the link (the phones and Revoke). */
function SmsBlock({ open }: { open: () => void }) {
  const sms = useSms()
  useEffect(() => void loadSms(), [])
  const link = (
    <button type="button" className="block min-h-11 text-left text-accent" onClick={open}>
      {sms.available ? 'Bank SMS settings' : 'Bank SMS and your phones'}
    </button>
  )
  if (!sms.available) return link
  return (
    <div>
      <h3 className="text-xs font-medium text-muted">Bank SMS</h3>
      <SmsRows status={sms} />
      {needsBatteryHint(sms) && <p className="mt-1 text-xs text-muted">Battery: set Flash to Unrestricted for background uploads.</p>}
      {link}
    </div>
  )
}

/** How this launch reached its first screen, and the last boot errors (D-095). */
function BootBlock() {
  const [log] = useState(readBoot)
  return (
    <>
      <h3 className="mt-4 text-xs font-medium text-muted">Boot</h3>
      <dl className="mt-1 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-0.5 tabular-nums [&_dt]:wrap-break-word">
        <dt className="text-muted">Path</dt>
        <dd>{log.last?.path ?? '–'}</dd>
        <dt className="text-muted">First screen</dt>
        <dd>{log.last ? `${log.last.paint_ms} ms` : '–'}</dd>
        <dt className="text-muted">Boot errors</dt>
        <dd>{log.errors.length || 'None'}</dd>
      </dl>
      {log.errors.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {log.errors.map((e, i) => (
            <li key={i} className="wrap-break-word">
              <span className="text-muted tabular-nums">{istTime(e.at)}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

/** The last launches, measured on this phone and kept only here (D-090). */
export function SpeedSheet({ onClose }: { onClose: () => void }) {
  const [timings, setTimings] = useState<Timing[] | null>(null)
  useEffect(() => {
    readTimings().then(setTimings, () => setTimings([]))
  }, [])
  const rows = speedRows((timings ?? []).slice(0, 10))
  const last = timings?.[0]
  const { replace } = useNav()
  return (
    <Sheet title="Speed" onClose={onClose}>
      <div className="px-4 py-3 text-sm">
        <SmsBlock open={() => replace({ sheet: 'sms' })} />
        <button type="button" className="-mt-1 mb-2 min-h-11 text-left text-accent" onClick={() => replace({ sheet: 'profile' })}>
          Your name as banks show it
        </button>
        <SyncBlock />
        <h3 className="mt-4 text-xs font-medium text-muted">Targets</h3>
        <ul className="mt-1 space-y-0.5">
          <li>Open from phone copy: 2 s or less</li>
          <li>Fresh data, server awake: 5 s or less</li>
        </ul>
        <h3 className="mt-4 text-xs font-medium text-muted">Last launch</h3>
        {last ? (
          <dl className="mt-1 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-0.5 tabular-nums [&_dt]:wrap-break-word">
            <dt className="text-muted">Phone copy</dt>
            <dd>{rows[0].local}</dd>
            <dt className="text-muted">Fresh data</dt>
            <dd>{rows[0].fresh}</dd>
            <dt className="text-muted">Request</dt>
            <dd>{last.request_ms === null ? '–' : `${last.request_ms} ms`}</dd>
            <dt className="text-muted">Size</dt>
            <dd>{last.bytes === null ? '–' : `${Math.round(last.bytes / 1024)} KB`}</dd>
            <dt className="text-muted">Result</dt>
            <dd>{rows[0].result}</dd>
          </dl>
        ) : (
          <p className="mt-1 text-muted">{timings ? 'No launches measured yet.' : 'Loading'}</p>
        )}
        {rows.length > 0 && (
          // At large text sizes the table scrolls inside its box; the page never scrolls sideways.
          <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left tabular-nums">
            <caption className="pb-1 text-left text-xs font-medium text-muted">{rows.length === 1 ? 'Last launch' : `Last ${rows.length} launches`}</caption>
            <thead className="text-xs text-muted">
              <tr>
                <th className="py-1 font-normal">Time</th>
                <th className="py-1 pl-2 font-normal">Boot</th>
                <th className="py-1 text-right font-normal">Local</th>
                <th className="py-1 text-right font-normal">Fresh</th>
                <th className="py-1 pl-3 font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="py-1">{r.when}</td>
                  <td className="py-1 pl-2">{r.boot}</td>
                  <td className="py-1 text-right">{r.local}</td>
                  <td className="py-1 text-right">{r.fresh}</td>
                  <td className="py-1 pl-3">{r.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
        <BootBlock />
        <p className="mt-4 text-xs text-muted">Measured on this phone and kept only here. Never sent anywhere.</p>
      </div>
    </Sheet>
  )
}
