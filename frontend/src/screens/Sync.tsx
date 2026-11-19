import { discard, failedOps, retry, useOutbox } from '../data/outbox.ts'
import { Button, Empty, Sheet } from '../ui.tsx'

/** The actions the server refused (`?unsaved`): what, which item, why; Retry or Discard. */
export function UnsavedSheet({ onClose }: { onClose: () => void }) {
  const failed = failedOps(useOutbox().ops)
  return (
    <Sheet title="Couldn't save" onClose={onClose}>
      {failed.length === 0 ? (
        <Empty>Everything is saved.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {failed.map((op) => (
            <li key={op.seq} className="px-4 py-3 text-sm">
              <p className="font-medium wrap-break-word">{op.kind}</p>
              <p className="text-muted wrap-break-word">{op.item}</p>
              <p className="mt-1 wrap-break-word">{op.last_error || 'The server did not accept this.'}</p>
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
