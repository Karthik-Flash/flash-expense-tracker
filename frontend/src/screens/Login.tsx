import { useState } from 'react'

import { Button } from '../ui.tsx'

/** Email and password, no sign-up. In demo mode any input continues. */
export function Login({ onDone, demo }: { onDone: () => void; demo: boolean }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const field = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-surface px-3'
  return (
    <main className="mx-auto flex min-h-dvh max-w-[480px] flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold">Flash</h1>
      <p className="mt-1 text-sm text-muted">Sign in to see your spending.</p>
      <form
        className="mt-8 space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (demo) onDone()
        }}
      >
        <label className="block text-sm">
          Email
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </label>
        <label className="block text-sm">
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
        </label>
        <div className="pt-2">
          <Button type="submit" kind="primary">Sign in</Button>
        </div>
        {demo && <p className="text-xs text-muted">Demo: any input continues.</p>}
      </form>
    </main>
  )
}
