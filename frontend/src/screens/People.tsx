import { useState } from 'react'

import type { Category, Person, PersonRole, Sender, SenderAnswer, Snapshot, Txn } from '../api/types.ts'
import {
  actions,
  enqueue,
  markFor,
  personCategoryMark,
  personFailed,
  kindMark,
  personMark,
  shownKind,
  roleConflict,
  senderMark,
  shownName,
  useOutbox,
} from '../data/outbox.ts'
import { usePeople, useSnapshot } from '../data/store.ts'
import { dayLabel } from '../lib/dates.ts'
import { seePayments, useNav } from '../state.tsx'
import { Button, CategoryChips, Empty, Icon, Money, Sheet } from '../ui.tsx'
import type { PersonStep } from '../view.ts'
import { isCredit, nameOf, subtitle } from './common.ts'
import { countsInSpent, labelName, personKey, topCategories } from './derive.ts'
import { AnswerButtons, type AnswerKey } from './Answers.tsx'
import { Pending } from './Transactions.tsx'

const ROLE_NAME: Record<PersonRole, string> = { friend: 'Friend', income: 'Family', ignore: 'Ignore', none: 'Not answered yet' }
const quiet = 'min-h-11 px-1 text-sm text-accent'

type Step = { kind: 'detail' } | { kind: 'name' } | { kind: 'join' } | { kind: 'role'; into: Person }

/** One person (?person=): how payments to them count, what money from them is, their recent
 *  payments (D-110); then name, identifiers, Rename, Clear name, Same as…, Separate (D-096).
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
  const mark = personMark(ops, p.key) ?? personFailed(ops, p.key)
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
      {step.kind === 'detail' && load.status === 'ready' && <PersonActions p={p} title={title} snapshot={load.data} />}
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
          <div className="mt-4 flex flex-wrap gap-2 [&>button]:flex-1 [&>button]:basis-36">
            <Button onClick={() => setStep({ kind: 'name' })}>{p.named ? 'Rename' : 'Name'}</Button>
            <Button onClick={() => setStep({ kind: 'join' })}>Same as…</Button>
            {p.named && <Button onClick={() => void enqueue(actions.clearName({ ...p, name: title }))}>Clear name</Button>}
            {view.tab === 'home' && view.path[1] === 'people' && view.path.length === 2 && (
              <Button className="basis-full" onClick={() => open({ path: ['category', 'people', p.key], person: null, act: null })}>
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
                    <span className="min-w-[min(6rem,35vw)] flex-1">
                      <span className="block truncate">{shownName(ops, o)}</span>
                      {o.named && <span className="block text-xs wrap-break-word text-muted">{o.identifiers.map((i) => i.name).filter(Boolean).join(' · ')}</span>}
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

const FAMILY = 'Family'

/** The answer an outbox entry or the server's sender stands for. */
function answerKey(a: SenderAnswer | undefined, s: Sender | undefined): AnswerKey | undefined {
  if (a) return a.answer === 'income' ? (a.label === FAMILY ? 'family' : 'income') : a.answer
  if (!s || s.status === 'to_confirm') return undefined
  if (s.status === 'ignored') return 'ignore'
  return s.role === 'income' ? (s.income_label === FAMILY ? 'family' : 'income') : 'friend'
}

/** The category every payment to them has now, when they all have the same one. */
function oneCategory(rows: Txn[]): string | undefined {
  const slugs = new Set(rows.map((t) => t.category))
  return slugs.size === 1 ? [...slugs][0] : undefined
}

/** D-110: change how a person's payments count without opening each one. Quiet and compact:
 *  their default category, the sender answer (only when they sent money), recent payments. */
function PersonActions({ p, title, snapshot }: { p: Person; title: string; snapshot: Snapshot }) {
  const { ops } = useOutbox()
  const [openRow, setOpenRow] = useState<number | null>(null)
  const [income, setIncome] = useState<string | null>(null)
  const cats: Category[] = snapshot.categories
  const chips = topCategories(snapshot.transactions, cats)
  const rows = snapshot.transactions.filter((t) => personKey(t) === p.key)
  const spends = rows.filter((t) => t.direction === 'debit' && countsInSpent(t))
  const senders = [...snapshot.todo.senders, ...snapshot.todo.answered].filter((s) => s.person_id === p.key)
  const catMark = personCategoryMark(ops, p.key)
  const answerMark = senderMark(ops, senders.map((s) => s.id))
  const liveAnswer = answerMark && answerMark.state !== 'failed' ? (answerMark.body as SenderAnswer) : undefined
  const nav = useNav()
  const kind = shownKind(ops, p)
  const answered: AnswerKey | undefined = kind ?? answerKey(liveAnswer, senders[0])
  const warn = (snapshot.todo.suggestions ?? []).find((x) => x.key === p.key)?.kind
  const pick = (a: AnswerKey) => {
    if (a === 'self' || a === 'investment') {
      void enqueue(kind === a ? actions.clearKind({ ...p, name: title }) : actions.setKind({ ...p, name: title }, a))
    } else if (a === 'income') {
      setIncome(senders[0]?.income_label && senders[0].income_label !== FAMILY ? senders[0].income_label : 'Income')
    } else answer(a === 'family' ? { answer: 'income', label: FAMILY } : { answer: a })
  }
  const rule = labelName(income ?? '', [])
  const answer = (a: SenderAnswer) => {
    for (const s of senders) void enqueue(actions.answerSender(s, a))
    setIncome(null)
  }
  const head = 'text-xs font-medium text-muted'
  return (
    <div className="space-y-4 px-4 pt-4 text-sm">
      {spends.length > 0 && (
        <section aria-labelledby="person-counts">
          <h3 id="person-counts" className={head}>Payments to them count as</h3>
          <div className="mt-1.5">
            <CategoryChips
              chips={chips}
              cats={cats}
              label={`Category for every payment to ${title}`}
              current={catMark && catMark.state !== 'failed' ? catMark.slug : oneCategory(spends)}
              onPick={(c) =>
                void enqueue(
                  actions.setCategory({ id: spends[0].id, display_name: spends[0].display_name }, c, 'merchant', title, { key: p.key, name: title }),
                )
              }
            />
          </div>
          {catMark && (
            <p className="mt-1">
              {catMark.choice} <Pending op={catMark} />
            </p>
          )}
          <p className="mt-1 text-xs text-muted">Every payment to them, also future ones.</p>
        </section>
      )}
      <section aria-labelledby="person-money-in">
          <h3 id="person-money-in" className={head}>{senders.length > 0 ? 'Money from them is' : 'This person is'}</h3>
          <div className="mt-1.5">
            {senders.length > 0 ? (
              <AnswerButtons label={`Money from ${title}`} current={answered} warn={warn} onAnswer={pick} />
            ) : (
              <div className="flex flex-wrap gap-2" role="group" aria-label={`Who is ${title}?`}>
                {(['self', 'investment'] as const).map((a) => (
                  <button
                    key={a}
                    type="button"
                    aria-pressed={kind === a}
                    className="min-h-11 flex-1 basis-20 rounded-lg border border-line bg-surface px-2 text-sm aria-pressed:border-accent aria-pressed:font-medium"
                    onClick={() => pick(a)}
                  >
                    {a === 'self' ? "It's me" : 'Investments'}
                  </button>
                ))}
              </div>
            )}
          </div>
          {income !== null && (
            <form
              className="mt-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (!rule.error) answer({ answer: 'income', label: rule.name })
              }}
            >
              <label className="block text-xs text-muted" htmlFor="person-income">Income, labelled (1 to 30 characters)</label>
              <div className="mt-1 flex flex-wrap gap-2">
                <input
                  id="person-income"
                  value={income}
                  onChange={(e) => setIncome(e.target.value)}
                  aria-invalid={Boolean(rule.error)}
                  className="min-h-11 min-w-32 flex-1 rounded-lg border border-line bg-surface px-3"
                />
                <Button type="submit" kind="primary" disabled={Boolean(rule.error)}>Save</Button>
                <Button onClick={() => setIncome(null)}>Cancel</Button>
              </div>
              {rule.error && <p className="pt-1 text-xs text-danger" aria-live="polite">{rule.error}</p>}
            </form>
          )}
          {answerMark && (
            <p className="mt-1">
              {answerMark.choice} <Pending op={answerMark} />
            </p>
          )}
          {kindMark(ops, p.key) && (
            <p className="mt-1">
              {kindMark(ops, p.key)!.choice} <Pending op={kindMark(ops, p.key)!} />
            </p>
          )}
          <p className="mt-1 text-xs text-muted">
            Friend counts as paid back; Family and Income as income; It's me and Investments in no total. Tap again to undo.{' '}
            <button type="button" className="min-h-11 text-accent" onClick={() => nav.open({ sheet: 'profile' })}>Your names</button>
          </p>
        </section>
      {rows.length > 0 && (
        <section aria-labelledby="person-recent">
          <h3 id="person-recent" className={head}>Recent payments</h3>
          <ul className="mt-1.5 divide-y divide-line rounded-lg border border-line">
            {rows.slice(0, 10).map((t) => {
              const mark = markFor(ops, t)
              const note = mark.category ?? mark.failed
              const shown = mark.category ? { ...t, category: mark.category.slug ?? t.category, category_name: mark.category.choice } : t
              const line = (
                <>
                  <span className="min-w-[min(6rem,35vw)] flex-1">
                    <span className="block truncate">{dayLabel(t.time_utc)}</span>
                    <span className="block text-xs wrap-break-word text-muted">{subtitle(shown)}</span>
                  </span>
                  <Money paise={t.amount_paise} credit={isCredit(t)} exact />
                </>
              )
              return (
                <li key={t.id} className="px-3 py-1">
                  {countsInSpent(t) ? (
                    <button
                      type="button"
                      aria-expanded={openRow === t.id}
                      className="flex min-h-11 w-full flex-wrap items-center gap-x-3 text-left"
                      onClick={() => setOpenRow(openRow === t.id ? null : t.id)}
                    >
                      {line}
                    </button>
                  ) : (
                    <div className="flex min-h-11 flex-wrap items-center gap-x-3">{line}</div>
                  )}
                  {note && <Pending op={note} />}
                  {openRow === t.id && (
                    <div className="pb-2">
                      <p className="pb-1 text-xs text-muted">Just this one</p>
                      <CategoryChips
                        chips={chips}
                        cats={cats}
                        label={`Category for the payment of ${dayLabel(t.time_utc)}`}
                        current={shown.category}
                        onPick={(c) => {
                          void enqueue(actions.setCategory(t, c, 'transaction', nameOf(t)))
                          setOpenRow(null)
                        }}
                      />
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="mt-1 flex justify-end">
            <button type="button" className="min-h-11 px-1 text-sm text-accent" onClick={() => seePayments(p.key)}>
              See all payments
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
