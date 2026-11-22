// Shared pieces: rows, money, icons, month switcher, bottom sheet, states. Calm and plain.

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { rupees } from './lib/money.ts'
import { monthLabel, shiftMonth } from './lib/dates.ts'
import { catColor, categoryIcon } from './screens/common.ts'
import { freshnessLine, refresh, useData, type Load } from './data/store.ts'
import { canStart, pullDistance, pullState, type PullState } from './pull.ts'
import { syncLine, useOutbox } from './data/outbox.ts'
import { expire, useAuth } from './auth.ts'
import type { Category } from './api/types.ts'
import { useNav } from './state.tsx'

/** Under the month: "Updated 5 min ago · 3 saved on phone, syncing · 1 not saved", "Updating…",
 *  or "Offline · showing data from …". The failed count opens its sheet. */
export function Freshness() {
  const data = useData()
  const outbox = useOutbox()
  const auth = useAuth()
  const { open } = useNav()
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  // The outbox got a 401, or the session was rejected at boot (D-095): the same link.
  const sync = syncLine(outbox.ops, outbox.signIn || (auth.status === 'in' && auth.signIn))
  const text = [data.snapshot ? freshnessLine(data, now, sync.signIn) : '', sync.waiting].filter(Boolean).join(' · ')
  const link = 'inline-flex min-h-11 items-center px-1 text-accent'
  return (
    <p className="min-h-5 px-4 text-center text-xs text-muted" role="status">
      {text}
      {/* A mouse and no touch: a Refresh link; touch screens pull down instead (5B-1). */}
      {data.snapshot && !data.refreshing && (
        <>
          {text && <span className="hidden [@media(pointer:fine)]:inline"> · </span>}
          <button type="button" className={`${link} hidden [@media(pointer:fine)]:inline-flex`} onClick={() => void refresh()}>
            Refresh
          </button>
        </>
      )}
      {sync.failed && (
        <>
          {text && ' · '}
          <button type="button" className={link} onClick={() => open({ sheet: 'unsaved' })}>{sync.failed}</button>
        </>
      )}
      {sync.signIn && (
        <>
          {(text || sync.failed) && ' · '}
          <button type="button" className={link} onClick={() => void expire('Sign in again to sync your changes.')}>Sign in to sync</button>
        </>
      )}
    </p>
  )
}

/** Pull down from the top of the page to refresh (touch screens, 5B-1). A quiet line at the
 *  top follows the finger; letting go past the trigger refreshes the snapshot. */
export function PullToRefresh() {
  const [dy, setDy] = useState(0)
  const [busy, setBusy] = useState(false) // a pull let go: "Updating…" until it ends
  useEffect(() => {
    let start: number | null = null
    let moved = 0
    const down = (e: TouchEvent) => {
      const inside = e.target instanceof Element && Boolean(e.target.closest('[role="dialog"], input, select, textarea'))
      start = e.touches.length === 1 && canStart(window.scrollY, inside) ? e.touches[0].clientY : null
      moved = 0
    }
    const move = (e: TouchEvent) => {
      if (start === null) return
      moved = e.touches[0].clientY - start
      setDy(moved > 0 ? moved : 0)
    }
    const up = () => {
      if (start !== null && pullState(moved) === 'ready') {
        setBusy(true)
        void refresh().finally(() => setBusy(false))
      }
      start = null
      moved = 0
      setDy(0)
    }
    window.addEventListener('touchstart', down, { passive: true })
    window.addEventListener('touchmove', move, { passive: true })
    window.addEventListener('touchend', up)
    window.addEventListener('touchcancel', up)
    return () => {
      window.removeEventListener('touchstart', down)
      window.removeEventListener('touchmove', move)
      window.removeEventListener('touchend', up)
      window.removeEventListener('touchcancel', up)
    }
  }, [])
  const state: PullState = pullState(dy)
  if (state === 'idle' && !busy) return null
  const words = busy ? 'Updating…' : state === 'ready' ? 'Release to refresh' : 'Pull to refresh'
  return (
    <p
      className="pointer-events-none fixed inset-x-0 top-0 z-20 text-center text-xs text-muted"
      style={{ transform: `translateY(${busy ? 8 : pullDistance(dy) / 2}px)` }}
      aria-hidden="true"
    >
      <span className="inline-block rounded-lg border border-line bg-surface px-3 py-1">{words}</span>
    </p>
  )
}

// Lucide icons (ISC, src/icons/LICENSE), copied as files: no icon package at runtime.
const SVGS = import.meta.glob('./icons/*.svg', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** A 20 px line icon in the current text colour. Decorative: the text next to it names it. */
export function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <span aria-hidden="true" className={`icon ${className}`} dangerouslySetInnerHTML={{ __html: SVGS[`./icons/${name}.svg`] ?? '' }} />
}

/** The category icon on a tile tinted with the category colour. Decorative: the name is next to it. */
export function CategoryTile({ slug, className = '' }: { slug: string; className?: string }) {
  return (
    <span className={`tile ${className}`} style={{ '--cat': catColor(slug) } as CSSProperties}>
      <Icon name={categoryIcon(slug)} />
    </span>
  )
}

export function Money({ paise, credit = false, exact = false, className = '' }: {
  paise: number
  credit?: boolean
  exact?: boolean
  className?: string
}) {
  const text = rupees(paise, exact, credit)
  return <span className={`ml-auto shrink-0 whitespace-nowrap tabular-nums ${credit ? 'text-positive' : ''} ${className}`}>{text}</span>
}

export function Header({ title, back, lead, children }: { title: string; back?: () => void; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="flex min-h-14 items-center gap-2 px-4 pt-2">
      {back && (
        <button type="button" onClick={back} className="-ml-3 flex size-11 shrink-0 items-center justify-center rounded-lg text-accent" aria-label="Back">
          <Icon name="chevron-left" />
        </button>
      )}
      {lead}
      <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">{title}</h1>
      {children}
    </header>
  )
}

export function MonthSwitcher({ month, setMonth, latest }: { month: string; setMonth: (m: string) => void; latest: string }) {
  const button = 'flex size-11 items-center justify-center rounded-lg text-accent disabled:text-faint'
  return (
    <div className="flex items-center justify-center gap-2" role="group" aria-label="Month">
      <button type="button" className={button} onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">
        <Icon name="chevron-left" />
      </button>
      <span className="min-w-28 text-center font-medium whitespace-nowrap tabular-nums" aria-live="polite">{monthLabel(month)}</span>
      <button type="button" className={button} onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= latest} aria-label="Next month">
        <Icon name="chevron-right" />
      </button>
    </div>
  )
}

/** A titled card of rows. A sticky title stays at the top while its rows scroll by. */
export function Section({ title, children, aside, sticky = false }: { title?: string; children: ReactNode; aside?: ReactNode; sticky?: boolean }) {
  return (
    <section className="mt-4 px-4">
      {title && (
        <div className={`flex flex-wrap items-baseline justify-between gap-x-3 py-2 ${sticky ? 'sticky top-0 z-10 -mx-4 bg-bg px-4' : ''}`}>
          <h2 className="min-w-0 text-sm font-medium wrap-break-word text-muted">{title}</h2>
          {aside}
        </div>
      )}
      <div className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">{children}</div>
    </section>
  )
}

export function RowButton({ onClick, children, label }: { onClick?: () => void; children: ReactNode; label?: string }) {
  // At large text sizes the amount moves under the name instead of squeezing it (4H).
  const body = <div className="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">{children}</div>
  return onClick ? (
    <button type="button" onClick={onClick} aria-label={label} className="block w-full text-left active:bg-press">
      {body}
    </button>
  ) : (
    body
  )
}

/** A thin bar in the category colour: `share` of the whole (0.37 fills 37%). */
export function Bar({ share, slug }: { share: number; slug: string }) {
  const width = Number.isFinite(share) ? Math.max(0, Math.min(1, share)) * 100 : 0
  return (
    <span className="block h-1 min-w-0 flex-1 rounded-full bg-track" aria-hidden="true">
      <span className="block h-1 rounded-full" style={{ width: `${width}%`, background: catColor(slug) }} />
    </span>
  )
}

export function Button({ children, onClick, kind = 'plain', disabled, type = 'button', className = '' }: {
  children: ReactNode
  onClick?: () => void
  kind?: 'primary' | 'plain'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
}) {
  const style = kind === 'primary' ? 'bg-accent text-on-accent border-accent' : 'bg-surface text-ink border-line'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`min-h-11 rounded-lg border px-3 text-sm font-medium wrap-break-word disabled:opacity-50 ${style} ${className}`}
    >
      {children}
    </button>
  )
}

/** One-tap category chips (the owner's most used, up to 4) and "More…" with every category.
 *  `current`: the chip that is chosen now (pressed). */
export function CategoryChips({ chips, cats, onPick, label, current }: {
  chips: Category[]
  cats: Category[]
  onPick: (c: Category) => void
  label: string
  current?: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {chips.map((c) => (
        <button
          key={c.slug}
          type="button"
          aria-pressed={c.slug === current}
          onClick={() => onPick(c)}
          className="min-h-11 rounded-lg border border-line bg-surface px-3 text-sm aria-pressed:border-accent aria-pressed:font-medium"
        >
          {c.name}
        </button>
      ))}
      <select
        aria-label={`More categories, ${label}`}
        value=""
        onChange={(e) => {
          const picked = cats.find((c) => c.slug === e.target.value)
          if (picked) onPick(picked)
        }}
        className="min-h-11 min-w-0 flex-1 basis-28 rounded-lg border border-line bg-surface px-3 text-sm"
      >
        <option value="">{chips.length ? 'More…' : 'Pick a category'}</option>
        {cats.filter((c) => c.slug !== 'uncategorised').map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
      </select>
    </div>
  )
}

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })
  useEffect(() => {
    panel.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close.current()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
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
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2">
          <h2 className="min-w-0 truncate font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="min-h-11 shrink-0 px-2 text-sm text-accent">Done</button>
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

/** A small labelled amount: "Spent" over "₹1,240". */
export function Figure({ term, paise, credit = false }: { term: string; paise: number; credit?: boolean }) {
  return (
    <span className="block">
      <span className="block text-xs text-muted">{term}</span>
      <Money paise={paise} credit={credit} />
    </span>
  )
}
