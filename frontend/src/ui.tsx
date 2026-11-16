// Shared pieces: rows, money, month switcher, bottom sheet, states. Calm and plain.

import { useEffect, useRef, useState, type ReactNode } from 'react'

import { moneyIn, rupees, rupeesExact } from './lib/money.ts'
import { monthLabel, shiftMonth } from './lib/dates.ts'
import type { Load } from './state.tsx'

export function Money({ paise, credit = false, exact = false, className = '' }: {
  paise: number
  credit?: boolean
  exact?: boolean
  className?: string
}) {
  const text = credit ? moneyIn(paise, exact) : exact ? rupeesExact(paise) : rupees(paise)
  return <span className={`tabular-nums ${credit ? 'text-positive' : ''} ${className}`}>{text}</span>
}

export function Header({ title, back, children }: { title: string; back?: () => void; children?: ReactNode }) {
  return (
    <header className="flex min-h-14 items-center gap-2 px-4 pt-2">
      {back && (
        <button type="button" onClick={back} className="-ml-2 flex size-11 items-center justify-center rounded-lg text-accent" aria-label="Back">
          <span aria-hidden="true" className="text-2xl leading-none">‹</span>
        </button>
      )}
      <h1 className="flex-1 truncate text-lg font-semibold">{title}</h1>
      {children}
    </header>
  )
}

export function MonthSwitcher({ month, setMonth, latest }: { month: string; setMonth: (m: string) => void; latest: string }) {
  const button = 'flex size-11 items-center justify-center rounded-lg text-xl text-accent disabled:text-faint'
  return (
    <div className="flex items-center justify-center gap-2" role="group" aria-label="Month">
      <button type="button" className={button} onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">‹</button>
      <span className="min-w-28 text-center font-medium tabular-nums" aria-live="polite">{monthLabel(month)}</span>
      <button type="button" className={button} onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= latest} aria-label="Next month">›</button>
    </div>
  )
}

export function Section({ title, children, aside }: { title?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="mt-6 px-4">
      {title && (
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-medium text-muted">{title}</h2>
          {aside}
        </div>
      )}
      <div className="overflow-hidden rounded-lg border border-line bg-surface">{children}</div>
    </section>
  )
}

export function RowButton({ onClick, children, label }: { onClick?: () => void; children: ReactNode; label?: string }) {
  const body = <div className="flex min-h-14 items-center gap-3 px-4 py-2.5">{children}</div>
  return onClick ? (
    <button type="button" onClick={onClick} aria-label={label} className="block w-full border-b border-line text-left last:border-b-0 active:bg-press">
      {body}
    </button>
  ) : (
    <div className="border-b border-line last:border-b-0">{body}</div>
  )
}

export function Bar({ share }: { share: number }) {
  return (
    <div className="mt-1.5 h-1 w-full rounded-full bg-track" aria-hidden="true">
      <div className="h-1 rounded-full bg-bar" style={{ width: `${Math.max(0, Math.min(100, share * 100))}%` }} />
    </div>
  )
}

export function Button({ children, onClick, kind = 'plain', disabled, type = 'button' }: {
  children: ReactNode
  onClick?: () => void
  kind?: 'primary' | 'plain'
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  const style =
    kind === 'primary'
      ? 'bg-accent text-on-accent border-accent'
      : 'bg-surface text-ink border-line'
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`min-h-11 rounded-lg border px-4 text-sm font-medium disabled:opacity-50 ${style}`}>
      {children}
    </button>
  )
}

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panel.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-scrim" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative max-h-[85dvh] w-full max-w-[480px] overflow-y-auto rounded-t-lg border border-line bg-surface pb-[max(1rem,env(safe-area-inset-bottom))] outline-none"
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-4 py-2">
          <h2 className="font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="min-h-11 px-2 text-sm text-accent">Done</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Waking() {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const timer = window.setInterval(() => setElapsed((Date.now() - start) / 1000), 500)
    return () => window.clearInterval(timer)
  }, [])
  // An estimate, not a promise: it slows down and never reaches the end on its own.
  const share = Math.min(0.92, 1 - Math.exp(-elapsed / 25))
  return (
    <div className="px-4 py-10 text-center" role="status">
      <p className="font-medium">Starting up, this can take about a minute</p>
      <p className="mt-1 text-sm text-muted">The server sleeps when nobody uses it.</p>
      <div
        className="mx-auto mt-5 h-1 w-48 rounded-full bg-track"
        role="progressbar"
        aria-label="Starting up"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
      >
        <div className="h-1 rounded-full bg-accent transition-[width] duration-500" style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  )
}

/** Shows loading, waking and error states; children render the data. */
export function Loaded<T>({ load, retry, children }: { load: Load<T>; retry: () => void; children: (data: T) => ReactNode }) {
  if (load.status === 'ready') return <>{children(load.data)}</>
  if (load.status === 'error') {
    return (
      <div className="px-4 py-10 text-center" role="alert">
        <p className="font-medium text-danger">Could not load</p>
        <p className="mt-1 text-sm text-muted">{load.message}</p>
        <div className="mt-4">
          <Button onClick={retry}>Try again</Button>
        </div>
      </div>
    )
  }
  return load.slow ? <Waking /> : <p className="px-4 py-10 text-center text-sm text-muted">Loading</p>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-10 text-center text-sm text-muted">{children}</p>
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="mx-4 mt-3 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-muted" role="status">{children}</p>
}
