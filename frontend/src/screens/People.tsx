import { useState } from 'react'

import type { Person, PersonRole } from '../api/types.ts'
import { actions, enqueue, personMark, roleConflict, shownName, useOutbox } from '../data/outbox.ts'
import { usePeople, useSnapshot } from '../data/store.ts'
import { seePayments, useNav } from '../state.tsx'
import { Button, Empty, Icon, Sheet } from '../ui.tsx'
import type { PersonStep } from '../view.ts'
import { labelName } from './derive.ts'
import { Pending } from './Transactions.tsx'

const ROLE_NAME: Record<PersonRole, string> = { friend: 'Friend', income: 'Family', ignore: 'Ignore', none: 'Not answered yet' }
const quiet = 'min-h-11 px-1 text-sm text-accent'

type Step = { kind: 'detail' } | { kind: 'name' } | { kind: 'join' } | { kind: 'role'; into: Person }

/** One person (?person=): name, identifiers, Rename, Clear name, Same as…, Separate (D-096).
 *  Every change is saved on the phone and sent in the background (D-091). */
export function PersonSheet({ personKey, act, onClose }: { personKey: string; act: PersonStep | null; onClose: () => void }) {
  const { people, find } = usePeople()
  const { ops } = useOutbox()
  const { view, open } = useNav()
  const [load] = useSnapshot()
  // After a join syncs, the person has a new key: follow it by one of its transactions.
  const [anchor] = useState(() => find(personKey)?.txn_id)
  const moved = load.status === 'ready' ? load.data.transactions.find((t) => t.id === anchor)?.person_id : undefined
  const p = find(personKey) ?? find(moved)
  const [step, setStep] = useState<Step>({ kind: act ?? 'detail' } as Step)
  const [name, setName] = useState(() => (p ? shownName(ops, p, '') : ''))
  const [q, setQ] = useState('')
  if (!p) {
    return (
      <Sheet title="Person" onClose={onClose}>
        <Empty>This person is not in your data yet.</Empty>
      </Sheet>
    )
  }
  const title = shownName(ops, p)
  const mark = personMark(ops, p.key)
  const rule = labelName(name, [])
  const join = (into: Person, role: PersonRole | null) => {
    void enqueue(actions.joinPerson({ ...p, name: title }, into, role))
    setStep({ kind: 'detail' })
  }
  const pick = (into: Person) => (roleConflict(p, into) ? setStep({ kind: 'role', into }) : join(into, null))
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const others = people.filter(
    (o) =>
      o.key !== p.key &&
      words.every((w) => [o.name, ...o.identifiers.map((i) => i.name)].some((text) => text?.toLowerCase().includes(w))),
  )
  const choice = 'flex min-h-12 w-full items-center justify-between gap-3 px-4 py-2 text-left active:bg-press'

  return (
    <Sheet title={title} onClose={onClose}>
      {step.kind === 'detail' && (
        <div className="px-4 py-4 text-sm">
          {mark && (
            <p className="mb-2">
              {mark.choice} <Pending op={mark} />
            </p>
          )}
          {p.role && <p className="text-muted">Answer: {ROLE_NAME[p.role]}</p>}
          <h3 className="mt-3 text-xs font-medium text-muted">{p.identifiers.length === 1 ? 'Identifier' : 'Identifiers'}</h3>
          <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
            {p.identifiers.map((i) => (
              <li key={i.txn_id} className="flex min-h-11 items-center gap-3 px-3 py-1">
                <span className="min-w-0 flex-1 wrap-anywhere">
                  {i.name ?? 'No name'}
                  {i.from_file && <span className="block text-xs text-muted">From the owner file</span>}
                </span>
                {p.identifiers.length > 1 && !i.from_file && (
                  <button type="button" className={quiet} onClick={() => void enqueue(actions.separate({ ...p, name: title }, i))}>
                    Separate
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Button onClick={() => setStep({ kind: 'name' })}>{p.named ? 'Rename' : 'Name'}</Button>
            <Button onClick={() => setStep({ kind: 'join' })}>Same as…</Button>
            {p.named && <Button onClick={() => void enqueue(actions.clearName({ ...p, name: title }))}>Clear name</Button>}
            <Button onClick={() => seePayments(p.key)}>See payments</Button>
            {view.tab === 'home' && view.path[1] === 'people' && view.path.length === 2 && (
              <Button className="col-span-2" onClick={() => open({ path: ['category', 'people', p.key], person: null, act: null })}>
                This month with {title}
              </Button>
            )}
          </div>
          <p className="mt-3 text-xs text-muted">Names and joins are yours: they change no amount, only who is who.</p>
        </div>
      )}
      {step.kind === 'name' && (
        <form
          className="px-4 py-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (rule.error) return
            void enqueue(actions.namePerson({ ...p, name: title }, rule.name))
            setStep({ kind: 'detail' })
          }}
        >
          <label className="block text-xs text-muted" htmlFor="person-name">Name (1 to 30 characters)</label>
          <div className="mt-1 flex flex-wrap gap-2">
            <input
              id="person-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={Boolean(name && rule.error)}
              className="min-h-11 min-w-32 flex-1 rounded-lg border border-line bg-surface px-3"
            />
            <Button type="submit" kind="primary" disabled={Boolean(rule.error)}>Save</Button>
            <Button onClick={() => setStep({ kind: 'detail' })}>Cancel</Button>
          </div>
          <p className="pt-1 text-xs text-danger" aria-live="polite">{name && rule.error}</p>
        </form>
      )}
      {step.kind === 'join' && (
        <div>
          <p className="px-4 pt-3 text-sm text-muted">{title} is the same person as…</p>
          <label className="relative mx-4 mt-2 block">
            <span className="sr-only">Search people</span>
            <Icon name="search" className="pointer-events-none absolute top-3 left-3 text-muted" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search names and UPI IDs"
              className="min-h-11 w-full rounded-lg border border-line bg-surface pr-3 pl-10 text-sm"
            />
          </label>
          {others.length === 0 ? (
            <Empty>Nobody matches.</Empty>
          ) : (
            <ul aria-label="People" className="mt-2 divide-y divide-line">
              {others.map((o) => (
                <li key={o.key}>
                  <button type="button" className={choice} onClick={() => pick(o)}>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{shownName(ops, o)}</span>
                      {o.named && <span className="block truncate text-xs text-muted">{o.identifiers.map((i) => i.name).filter(Boolean).join(' · ')}</span>}
                    </span>
                    {o.role && <span className="shrink-0 text-xs text-muted">{ROLE_NAME[o.role]}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="px-4 pt-2">
            <Button onClick={() => setStep({ kind: 'detail' })}>Cancel</Button>
          </div>
        </div>
      )}
      {step.kind === 'role' && step.into.role && p.role && (
        <div className="space-y-3 px-4 py-4 text-sm">
          <p>
            {shownName(ops, step.into)} is {ROLE_NAME[step.into.role]}; {title} is {ROLE_NAME[p.role]}. Which answer does the person keep?
          </p>
          <div className="grid gap-2">
            <Button kind="primary" onClick={() => join(step.into, step.into.role)}>Keep {ROLE_NAME[step.into.role]}</Button>
            <Button onClick={() => join(step.into, p.role)}>Use {ROLE_NAME[p.role]}</Button>
            <Button onClick={() => setStep({ kind: 'join' })}>Cancel</Button>
          </div>
          <p className="text-xs text-muted">The answer applies to every payment from the person.</p>
        </div>
      )}
    </Sheet>
  )
}
