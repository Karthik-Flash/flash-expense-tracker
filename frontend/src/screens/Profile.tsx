import { useState } from 'react'

import { actions, enqueue, useOutbox } from '../data/outbox.ts'
import { useSnapshot } from '../data/store.ts'
import { Button, Sheet } from '../ui.tsx'
import { Pending } from './Transactions.tsx'

const MAX = 6

/** "Your name as banks show it" (?profile, D-117): the owner's name variants, so the app can
 *  ask "Is this you?" about a transfer to the owner's own account. Only questions come of it. */
export function ProfileSheet({ onClose }: { onClose: () => void }) {
  const [load] = useSnapshot()
  const { ops } = useOutbox()
  const waiting = ops.filter((o) => o.path === '/profile/names' && o.state !== 'failed').at(-1)
  const saved = waiting ? (waiting.body as { names: string[] }).names : (load.status === 'ready' ? (load.data.profile?.names ?? []) : [])
  const [names, setNames] = useState<string[]>(saved)
  const [draft, setDraft] = useState('')
  const text = draft.trim().replace(/\s+/g, ' ')
  const error = !text ? '' : text.length < 2 || text.length > 60 ? 'Use 2 to 60 characters.' : names.some((n) => n.toLowerCase() === text.toLowerCase()) ? 'Already in the list.' : ''
  const changed = names.join('\n') !== saved.join('\n')
  return (
    <Sheet title="Your name" onClose={onClose}>
      <div className="space-y-3 px-4 py-4 text-sm">
        <p className="text-muted">Your name as banks show it, for example on a transfer to your own account. Add every way it is written: with initials, in another order.</p>
        {names.length > 0 && (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {names.map((n) => (
              <li key={n} className="flex min-h-11 flex-wrap items-center gap-x-3 px-3">
                <span className="min-w-0 flex-1 wrap-anywhere">{n}</span>
                <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => setNames(names.filter((x) => x !== n))}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        {names.length < MAX && (
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (text && !error) {
                setNames([...names, text])
                setDraft('')
              }
            }}
          >
            <label className="sr-only" htmlFor="owner-name">A name as banks show it</label>
            <input
              id="owner-name"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="A name as banks show it"
              aria-invalid={Boolean(error)}
              className="min-h-11 min-w-32 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" disabled={!text || Boolean(error)}>Add</Button>
          </form>
        )}
        {error && <p className="text-xs text-danger" aria-live="polite">{error}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <Button kind="primary" disabled={!changed} onClick={() => void enqueue(actions.setOwnerNames(names))}>Save</Button>
          {waiting && <Pending op={waiting} />}
        </div>
        <p className="text-xs text-muted">Kept on the server as your data. The app only asks; nothing changes until you answer.</p>
      </div>
    </Sheet>
  )
}
