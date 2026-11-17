import { useState } from 'react'

import { DEMO } from '../api/index.ts'
import { Button } from '../ui.tsx'

/** Email and password, no sign-up. `submit` answers '' when signed in, else what went wrong. */
export function Login({ submit, note }: { submit: (email: string, password: string) => Promise<string>; note: string }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const field = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-surface px-3'
  return (
    <main className="mx-auto flex w-full max-w-[480px] flex-1 flex-col justify-center px-6 py-8">
      <h1 className="text-2xl font-semibold">Flash</h1>
      <p className="mt-1 text-sm text-muted">Sign in to see your spending.</p>
      <form
        className="mt-8 space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError('')
          const problem = await submit(email, password)
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
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={field}
          />
        </label>
        {error ? (
          <p className="text-sm text-danger" role="alert">{error}</p>
        ) : (
          note && <p className="text-sm text-muted" role="status">{note}</p>
        )}
        <div className="pt-2">
          <Button type="submit" kind="primary" disabled={busy}>{busy ? 'Signing in' : 'Sign in'}</Button>
        </div>
        {DEMO && <p className="text-xs text-muted">Demo: any input continues.</p>}
      </form>
    </main>
  )
}
