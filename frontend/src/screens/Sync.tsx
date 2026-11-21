import { discard, failedOps, reasonText, retry, tryNow, undo, useOutbox, type Op } from '../data/outbox.ts'
import { istTime } from '../lib/dates.ts'
import { Button, Empty, Sheet } from '../ui.tsx'

/** An action still on the phone after 2 minutes (D-107): when, how often, why; Try now. */
export function OpSheet({ op, onClose }: { op: Op; onClose: () => void }) {
  const live = useOutbox().ops.find((o) => o.seq === op.seq) ?? op
  return (
    <Sheet title="Saved on phone" onClose={onClose}>
      <div className="px-4 py-3 text-sm">
        <p className="font-medium wrap-break-word">{live.kind}</p>
        <p className="text-muted wrap-break-word">{live.item}</p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 tabular-nums">
          <dt className="text-muted">Saved</dt>
          <dd>{istTime(Date.parse(live.created_at))}</dd>
          <dt className="text-muted">Attempts</dt>
          <dd>{live.attempts}</dd>
          <dt className="text-muted">Last try</dt>
          <dd>{istTime(live.last_attempt_at)}</dd>
          <dt className="text-muted">Reason</dt>
          <dd className="wrap-break-word">{live.state === 'confirmed' ? 'Synced' : reasonText(live)}</dd>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          {live.state !== 'confirmed' && <Button kind="primary" onClick={() => void tryNow()}>Try now</Button>}
          {live.state === 'pending' && <Button onClick={() => void undo(live).then((done) => done && onClose())}>Undo</Button>}
        </div>
        <p className="mt-3 text-xs text-muted">It stays on this phone until the server has it. Nothing is lost.</p>
      </div>
    </Sheet>
  )
}

/** The actions the server refused (`?unsaved`): what, which item, why; Retry or Discard. */
export function UnsavedSheet({ onClose }: { onClose: () => void }) {
  const failed = failedOps(useOutbox().ops)
  return (
    <Sheet title="Not saved" onClose={onClose}>
      {failed.length === 0 ? (
        <Empty>Everything is saved.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {failed.map((op) => (
            <li key={op.seq} className="px-4 py-3 text-sm">
              <p className="font-medium wrap-break-word">{op.kind}</p>
              <p className="text-muted wrap-break-word">{op.item}</p>
              <p className="mt-1 wrap-break-word">{op.message || `Not saved: ${reasonText(op)}.`}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button onClick={() => void retry(op)}>Retry</Button>
                <Button onClick={() => void discard(op)}>Discard</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="px-4 pt-3 text-xs text-muted">Discard drops the change; nothing else is lost.</p>
    </Sheet>
  )
}
