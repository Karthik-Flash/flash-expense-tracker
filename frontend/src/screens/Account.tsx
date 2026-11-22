import { useEffect, useState } from 'react'

import { deleteProblem, welcomeDone } from '../account.ts'
import type { InviteItem, Member, Settings } from '../api/types.ts'
import { reauthenticate, signOut, useAuth } from '../auth.ts'
import { actions, enqueue, settingsMark, shownSettings, useOutbox } from '../data/outbox.ts'
import { useSnapshot } from '../data/store.ts'
import { dayLabel } from '../lib/dates.ts'
import { isNativeApp } from '../native/sms.ts'
import { useApp, useNav } from '../state.tsx'
import { Button, Sheet } from '../ui.tsx'
import type { SheetName } from '../view.ts'
import { Pending } from './Transactions.tsx'

const LINK = 'flex min-h-11 w-full items-center px-4 text-left text-accent'

/** Settings (`?settings`, 5C): one quiet list of links. */
export function SettingsSheet({ onClose }: { onClose: () => void }) {
  const { replace } = useNav()
  const [load] = useSnapshot()
  const admin = load.status === 'ready' && load.data.account?.role === 'admin'
  const go = (sheet: SheetName) => () => replace({ sheet })
  return (
    <Sheet title="Settings" onClose={onClose}>
      <ul className="divide-y divide-line py-1 text-sm">
        <li><button type="button" className={LINK} onClick={go('profile')}>Your name as banks show it</button></li>
        <li><button type="button" className={LINK} onClick={go('sms')}>{isNativeApp() ? 'Bank SMS on this phone' : 'Bank SMS and your phones'}</button></li>
        {admin && <li><button type="button" className={LINK} onClick={go('members')}>People who use Flash</button></li>}
        <li><button type="button" className={LINK} onClick={go('privacy')}>What Flash stores</button></li>
        <li><button type="button" className={LINK} onClick={go('speed')}>Speed and sync</button></li>
        <li><button type="button" className={LINK} onClick={go('delete')}>Delete my account</button></li>
      </ul>
      <InvestmentsSetting server={load.status === 'ready' ? load.data.profile?.settings : undefined} />
    </Sheet>
  )
}

/** "Count investments in Spent" (D-136), off by default; saved through the outbox. Only
 *  investments you confirmed move; ones still to confirm are in Spent either way. */
export function InvestmentsSetting({ server }: { server: Settings | undefined }) {
  const { ops } = useOutbox()
  const on = shownSettings(ops, server).count_investments_in_spent
  const mark = settingsMark(ops)
  return (
    <div className="border-t border-line px-4 py-3 text-sm">
      <label className="flex min-h-11 items-center justify-between gap-3">
        <span>Count investments in Spent</span>
        <input
          type="checkbox"
          role="switch"
          className="size-5 accent-accent"
          checked={on}
          onChange={(e) => void enqueue(actions.setSettings({ count_investments_in_spent: e.target.checked }))}
        />
      </label>
      <p className="text-xs text-muted">Off: money you marked as invested is shown as Invested, apart from Spent.</p>
      {mark && <Pending op={mark} />}
    </div>
  )
}

/** People who use Flash (`?members`, the admin, D-128): invites and members, counts only. */
export function MembersSheet({ onClose }: { onClose: () => void }) {
  const { api } = useApp()
  const [load, retry] = useSnapshot()
  const admin = load.status === 'ready' ? load.data.admin : undefined
  const [code, setCode] = useState('')
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const create = async () => {
    setBusy(true)
    setError('')
    setCopied(false)
    try {
      setCode((await api.createInvite()).code)
      void retry()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make an invite. Try again.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Sheet title="People who use Flash" onClose={onClose}>
      <div className="space-y-4 px-4 py-4 text-sm">
        {!admin ? (
          <p className="text-muted">Only the admin sees this.</p>
        ) : (
          <>
            <section className="space-y-2">
              <p className="text-muted">An invite lets one person make an account. It works once, for 7 days.</p>
              <Button kind="primary" disabled={busy} onClick={() => void create()}>New invite</Button>
              {code && (
                <div className="rounded-lg border border-line px-3 py-2">
                  <p className="text-xs text-muted">Send this code to the person. It is shown only now.</p>
                  <p className="mt-1 font-mono text-lg tracking-wider tabular-nums" aria-label="Invite code">{code}</p>
                  <button
                    type="button"
                    className="min-h-11 text-accent"
                    onClick={() => void navigator.clipboard?.writeText(code).then(() => setCopied(true), () => setCopied(false))}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
              )}
              {error && <p className="text-danger" role="alert">{error}</p>}
            </section>
            <Invites invites={admin.invites} />
            <Members members={admin.members} />
          </>
        )}
      </div>
    </Sheet>
  )
}

function inviteState(i: InviteItem): string {
  if (i.used_utc) return `Used ${dayLabel(i.used_utc)}`
  if (i.revoked_utc) return 'Revoked'
  if (i.expires_utc && Date.parse(i.expires_utc) <= Date.now()) return 'Expired'
  return i.expires_utc ? `Open until ${dayLabel(i.expires_utc)}` : 'Open'
}

function Invites({ invites }: { invites: InviteItem[] }) {
  const { ops } = useOutbox()
  if (!invites.length) return null
  return (
    <section>
      <h3 className="text-xs font-medium text-muted">Invites</h3>
      <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
        {[...invites].reverse().map((i) => {
          const path = `/invites/${i.id}`
          const op = ops.filter((o) => o.path === path).at(-1)
          const open = inviteState(i).startsWith('Open')
          return (
            <li key={i.id} className="flex min-h-11 flex-wrap items-center gap-x-3 px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="block">{i.created_utc ? `Made ${dayLabel(i.created_utc)}` : 'Invite'}</span>
                <span className="block text-xs text-muted">{inviteState(i)}</span>
              </span>
              {op ? (
                <Pending op={op} />
              ) : (
                open && (
                  <button
                    type="button"
                    className="min-h-11 px-1 text-accent"
                    onClick={() => void enqueue({ kind: 'Invite', item: i.created_utc ? `Made ${dayLabel(i.created_utc)}` : 'Invite', choice: 'Revoked', method: 'DELETE', path, body: null, targets: {} })}
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

function Members({ members }: { members: Member[] }) {
  return (
    <section>
      <h3 className="text-xs font-medium text-muted">Members</h3>
      <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
        {members.map((m, n) => (
          <li key={`${m.email}:${n}`} className="px-3 py-2">
            <span className="block wrap-anywhere">
              {m.email ?? 'No email on record'}
              {m.role === 'admin' && <span className="text-muted"> · admin</span>}
            </span>
            <span className="block text-xs text-muted tabular-nums">
              {[
                m.joined_utc ? `Joined ${dayLabel(m.joined_utc)}` : '',
                m.last_seen_utc ? `last sync ${dayLabel(m.last_seen_utc)}` : 'not synced yet',
                `${m.transactions} payments`,
                `${m.phones} ${m.phones === 1 ? 'phone' : 'phones'}`,
              ].filter(Boolean).join(' · ')}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs text-muted">Counts only. Nobody sees another person's payments.</p>
    </section>
  )
}

/** Delete my account (`?delete`, D-131): what goes, type DELETE, the password again. */
export function DeleteSheet({ onClose }: { onClose: () => void }) {
  const { api } = useApp()
  const [load] = useSnapshot()
  const admin = load.status === 'ready' && load.data.account?.role === 'admin'
  const [typed, setTyped] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const field = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-surface px-3'
  const remove = async () => {
    setBusy(true)
    setError('')
    const again = await reauthenticate(password)
    const answer = again ? null : await api.deleteAccount().catch(() => ({ status: 0, detail: null, message: 'Could not reach the server. Check the connection and try again.' }))
    const problem = again || (answer ? deleteProblem(answer) : '')
    setBusy(false)
    if (problem) return setError(problem)
    await signOut('Your account and all its data were deleted.') // this phone's copy, queue and token too
  }
  return (
    <Sheet title="Delete my account" onClose={onClose}>
      <div className="space-y-3 px-4 py-4 text-sm">
        {admin ? (
          <p>The admin account cannot be deleted from the app, so Flash can never be locked out. Ask for help if you need it gone.</p>
        ) : (
          <>
            <p>This deletes everything Flash holds for you, on the server and on this phone, and then your login. It cannot be undone.</p>
            <ul className="list-disc space-y-1 pl-5 text-muted">
              <li>your bank messages and payments</li>
              <li>your answers, names, categories and labels</li>
              <li>your phones and their uploads</li>
            </ul>
            <label className="block">
              Type DELETE to confirm
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoCapitalize="characters" className={field} />
            </label>
            <label className="block">
              Your password
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
            </label>
            {error && <p className="text-danger" role="alert">{error}</p>}
            <Button disabled={busy || typed !== 'DELETE' || !password} onClick={() => void remove()} className="border-danger! text-danger!">
              {busy ? 'Deleting' : 'Delete my account'}
            </Button>
          </>
        )}
      </div>
    </Sheet>
  )
}

/** What Flash stores (`?privacy`, D-132): docs/privacy.md in plain words. Also before login. */
export function PrivacySheet({ onClose }: { onClose: () => void }) {
  return (
    <Sheet title="What Flash stores" onClose={onClose}>
      <div className="space-y-3 px-4 py-4 text-sm">
        <ul className="list-disc space-y-2 pl-5">
          <li>Only your banks' SMS: payments, refunds and transfers. Never one-time passwords, never promotions, never anyone's personal messages.</li>
          <li>Your answers: names, categories, labels and who sent you money.</li>
          <li>Your email, to sign in. Your password is kept by the sign-in service, not by Flash.</li>
          <li>It is stored on servers in Singapore (Supabase), and only you can see it.</li>
          <li>It is never shared or sold. Flash does not lend money or score your credit.</li>
          <li>You can delete everything at any time: Settings, Delete my account.</li>
        </ul>
        <p className="text-xs text-muted">The Android app reads SMS on your phone and sends only the bank ones. Nothing else leaves the phone.</p>
      </div>
    </Sheet>
  )
}

/** First run (`?welcome`, D-132): welcome, your name, then bank SMS. Skippable; once. */
export function WelcomeSheet({ onClose }: { onClose: () => void }) {
  const auth = useAuth()
  const user = auth.status === 'in' ? auth.user : null
  const { replace } = useNav()
  const [step, setStep] = useState(0)
  const done = () => welcomeDone(user)
  useEffect(() => welcomeDone(user), [user]) // shown once, however it is closed
  const finish = () => {
    done()
    onClose()
  }
  const steps = [
    {
      title: 'Welcome to Flash',
      text: 'Flash turns your bank SMS into a calm monthly picture of your spending. Two short steps.',
      action: <Button kind="primary" onClick={() => setStep(1)}>Start</Button>,
    },
    {
      title: 'Your name as banks show it',
      text: 'When you move money to your own account, banks print your name. Add it, and Flash asks before counting such a payment.',
      action: <Button kind="primary" onClick={() => { done(); replace({ sheet: 'profile' }) }}>Add my name</Button>,
      next: () => setStep(2),
    },
    isNativeApp()
      ? {
          title: 'Read my bank SMS',
          text: 'Flash reads only your banks\' SMS on this phone and sends them to your account.',
          action: <Button kind="primary" onClick={() => { done(); replace({ sheet: 'sms' }) }}>Read my bank SMS</Button>,
        }
      : {
          title: 'Bank SMS',
          text: 'Reading bank SMS needs the Flash app for Android. Until then this page shows what is already there.',
          action: <Button kind="primary" onClick={finish}>Done</Button>,
        },
  ]
  const s = steps[step]
  return (
    <Sheet title={s.title} onClose={finish}>
      <div className="space-y-4 px-4 py-4 text-sm">
        <p>{s.text}</p>
        <div className="flex flex-wrap gap-2">
          {s.action}
          {'next' in s && s.next && <Button onClick={s.next}>Later</Button>}
          {step === 0 && <Button onClick={finish}>Skip</Button>}
        </div>
        <p className="text-xs text-muted tabular-nums">Step {step + 1} of 3</p>
      </div>
    </Sheet>
  )
}
