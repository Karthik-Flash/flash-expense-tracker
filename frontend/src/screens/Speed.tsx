import { useEffect, useState } from 'react'

import { readTimings, type Timing } from '../data/local.ts'
import { failedOps, useOutbox, waiting } from '../data/outbox.ts'
import { speedRows } from '../data/store.ts'
import { dayLabel, timeLabel } from '../lib/dates.ts'
import { Sheet } from '../ui.tsx'

/** The outbox: what waits, what failed, the last drain, the last error. */
function SyncBlock() {
  const s = useOutbox()
  const last = s.lastDrain
  const at = last && new Date(last.at).toISOString()
  return (
    <>
      <h3 className="mt-4 text-xs font-medium text-muted">Sync</h3>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 tabular-nums">
        <dt className="text-muted">Waiting</dt>
        <dd>{waiting(s.ops)}</dd>
        <dt className="text-muted">Couldn't save</dt>
        <dd>{failedOps(s.ops).length}</dd>
        <dt className="text-muted">Last drain</dt>
        <dd>{last && at ? `${dayLabel(at)} ${timeLabel(at)}, ${last.sent} sent, ${(last.ms / 1000).toFixed(1)} s` : '–'}</dd>
        <dt className="text-muted">Last error</dt>
        <dd className="wrap-break-word">{s.signIn ? 'Sign in to sync' : s.lastError || '–'}</dd>
      </dl>
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
  return (
    <Sheet title="Speed" onClose={onClose}>
      <div className="px-4 py-3 text-sm">
        <h3 className="text-xs font-medium text-muted">Targets</h3>
        <ul className="mt-1 space-y-0.5">
          <li>Open from phone copy: 2 s or less</li>
          <li>Fresh data, server awake: 5 s or less</li>
        </ul>
        <h3 className="mt-4 text-xs font-medium text-muted">Last launch</h3>
        {last ? (
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 tabular-nums">
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
          <table className="mt-4 w-full text-left tabular-nums">
            <caption className="pb-1 text-left text-xs font-medium text-muted">Last {rows.length} launches</caption>
            <thead className="text-xs text-muted">
              <tr>
                <th className="py-1 font-normal">Time</th>
                <th className="py-1 text-right font-normal">Local</th>
                <th className="py-1 text-right font-normal">Fresh</th>
                <th className="py-1 pl-3 font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 whitespace-nowrap">{r.when}</td>
                  <td className="py-1 text-right whitespace-nowrap">{r.local}</td>
                  <td className="py-1 text-right whitespace-nowrap">{r.fresh}</td>
                  <td className="py-1 pl-3">{r.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <SyncBlock />
        <p className="mt-4 text-xs text-muted">Measured on this phone and kept only here. Never sent anywhere.</p>
      </div>
    </Sheet>
  )
}
