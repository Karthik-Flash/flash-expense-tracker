import { useState, useSyncExternalStore } from 'react'

import { signUpProblem } from '../account.ts'
import { DEMO } from '../api/index.ts'
import { OFFLINE_SIGN_IN } from '../auth.ts'
import { Wordmark } from '../brand.tsx'
import { navigate } from '../state.tsx'
import { Button } from '../ui.tsx'
import { HOME } from '../view.ts'

function onConnection(change: () => void) {
  window.addEventListener('online', change)
  window.addEventListener('offline', change)
  return () => {
    window.removeEventListener('online', change)
    window.removeEventListener('offline', change)
  }
}

/** Email and password. `submit` answers '' when signed in, else what went wrong. With an
 *  invite code (5C, D-128), `join` makes the account first; public sign-up stays off. */
export function Login({ submit, join, note }: {
  submit: (email: string, password: string) => Promise<string>
  join: (email: string, password: string, code: string) => Promise<string>
  note: string
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [invited, setInvited] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const online = useSyncExternalStore(onConnection, () => navigator.onLine)
  const field = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-surface px-3'
  const link = 'min-h-11 text-sm text-accent'
  return (
    <main className="mx-auto flex w-full max-w-[480px] flex-1 flex-col justify-center px-6 py-8">
      <h1>
        <Wordmark height={40} />
      </h1>
      <p className="mt-3 text-sm text-muted">{invited ? 'Make your account with the invite code you were sent.' : 'Sign in to see your spending.'}</p>
      <form
        className="mt-8 space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          const early = invited && !DEMO ? signUpProblem(email, password, code) : ''
          if (early) return setError(early)
          setBusy(true)
          setError('')
          const problem = invited ? await join(email, password, code) : await submit(email, password)
          setBusy(false)
          setError(problem)
        }}
      >
        <label className="block text-sm">
          Email
          <input type="email" required={!DEMO} autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </label>
        <label className="block text-sm">
          Password
          <input
            type="password"
            required={!DEMO}
            autoComplete={invited ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={field}
          />
        </label>
        {invited && (
          <label className="block text-sm">
            Invite code
            <input
              required={!DEMO}
              autoCapitalize="characters"
              autoComplete="off"
              placeholder="ABCD-EFGH-JKLM"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={`${field} font-mono tracking-wider`}
            />
          </label>
        )}
        {!online && !DEMO ? (
          <p className="text-sm text-muted" role="status">{OFFLINE_SIGN_IN}</p>
        ) : error ? (
          <p className="text-sm text-danger" role="alert">{error}</p>
        ) : (
          note && <p className="text-sm text-muted" role="status">{note}</p>
        )}
        <div className="pt-2">
          <Button type="submit" kind="primary" disabled={busy}>
            {invited ? (busy ? 'Making your account' : 'Make my account') : busy ? 'Signing in' : 'Sign in'}
          </Button>
        </div>
        {DEMO && <p className="text-xs text-muted">Demo: any input continues.</p>}
      </form>
      <div className="mt-6 flex flex-col items-start">
        <button type="button" className={link} onClick={() => { setInvited(!invited); setError('') }}>
          {invited ? 'I have an account' : 'Have an invite code?'}
        </button>
        <button type="button" className={link} onClick={() => navigate({ ...HOME, sheet: 'privacy' }, 'open')}>
          What Flash stores
        </button>
      </div>
    </main>
  )
}
