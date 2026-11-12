import { useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL?.replace(/\/+$/, '')
const RETRY_MS = 5_000
// ~2 minutes of retries: enough for a Render free-tier cold start.
const MAX_ATTEMPTS = 24

type Status =
  | { kind: 'checking'; attempt: number }
  | { kind: 'online'; version: string }
  | { kind: 'offline' }

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: 'checking', attempt: 1 })
  const [run, setRun] = useState(0)

  useEffect(() => {
    if (!API_URL) return
    let cancelled = false
    let timer: number | undefined

    const check = async (attempt: number) => {
      try {
        const res = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(10_000) })
        const body: unknown = res.ok ? await res.json() : null
        if (!isHealth(body)) throw new Error('unexpected /health response')
        if (!cancelled) setStatus({ kind: 'online', version: body.version })
      } catch {
        if (cancelled) return
        if (attempt >= MAX_ATTEMPTS) {
          setStatus({ kind: 'offline' })
          return
        }
        timer = window.setTimeout(() => {
          setStatus({ kind: 'checking', attempt: attempt + 1 })
          void check(attempt + 1)
        }, RETRY_MS)
      }
    }

    void check(1)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [run])

  const retry = () => {
    setStatus({ kind: 'checking', attempt: 1 })
    setRun((n) => n + 1)
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-950 p-6 text-slate-100">
      <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-lg">
        <h1 className="text-2xl font-semibold tracking-tight">
          <span aria-hidden="true" className="text-yellow-400">
            ⚡
          </span>{' '}
          Flash
        </h1>
        <p className="mt-1 text-sm text-slate-400">Personal expense tracker</p>

        <div role="status" aria-live="polite" className="mt-6 text-sm">
          {!API_URL ? (
            <p className="text-amber-300">
              VITE_API_URL is not set. Copy <code>frontend/.env.example</code> to{' '}
              <code>frontend/.env</code>.
            </p>
          ) : status.kind === 'online' ? (
            <p className="flex items-center gap-2">
              <Dot className="bg-emerald-400" /> Backend online · v{status.version}
            </p>
          ) : status.kind === 'offline' ? (
            <div className="flex items-center justify-between gap-4">
              <p className="flex items-center gap-2">
                <Dot className="bg-rose-500" /> Server unreachable
              </p>
              <button
                type="button"
                onClick={retry}
                className="rounded-lg bg-slate-800 px-3 py-1.5 font-medium hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-yellow-400"
              >
                Retry
              </button>
            </div>
          ) : status.attempt === 1 ? (
            <p className="flex items-center gap-2">
              <Dot className="animate-pulse bg-slate-400" /> Connecting to server…
            </p>
          ) : (
            <p className="flex items-center gap-2">
              <Dot className="animate-pulse bg-amber-400" />
              Server is waking up, this can take a minute (attempt {status.attempt}/
              {MAX_ATTEMPTS})
            </p>
          )}
        </div>
      </div>
    </main>
  )
}

function Dot({ className }: { className: string }) {
  return <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${className}`} />
}

function isHealth(body: unknown): body is { status: 'ok'; version: string } {
  return (
    typeof body === 'object' &&
    body !== null &&
    (body as { status?: unknown }).status === 'ok' &&
    typeof (body as { version?: unknown }).version === 'string'
  )
}
