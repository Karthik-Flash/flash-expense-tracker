// Spent by category as a thin ring: at most 6 slices plus "Other", gaps between slices, Spent
// in the centre. Hand-drawn SVG, no chart package. Each slice and legend row opens its category.

import type { ChartSlice, MonthData } from '../api/types.ts'
import { percentOf, rupees } from '../lib/money.ts'
import { CategoryTile, Icon, Money, RowButton, Section } from '../ui.tsx'
import { catColor } from './common.ts'

/** A slice from the server, with its share of the ring (the server's total of the slices). */
type Slice = ChartSlice & { share: number }

const R = 50
const WIDTH = 7
const AROUND = 2 * Math.PI * R
const GAP = 2.4 // surface between slices, in the same units as AROUND (about 0.8% of it)
const OTHER = 'var(--color-faint)'

/** Each slice as a dash on the circle, starting at 12 o'clock, with half a gap on each side. */
function arcs(slices: Slice[]) {
  const gap = slices.length > 1 ? GAP : 0
  const starts = slices.map((_, i) => slices.slice(0, i).reduce((sum, s) => sum + s.share, 0) * AROUND)
  return slices.map((s, i) => {
    const length = Math.max(s.share * AROUND - gap, 0.8)
    return { ...s, dash: `${length} ${AROUND - length}`, offset: -(starts[i] + gap / 2) }
  })
}

export function Ring({ chart, spent, onOpen, onOther }: {
  chart: MonthData['chart']
  spent: number
  onOpen: (slug: string) => void
  onOther: () => void
}) {
  const total = chart.total_paise
  const slices: Slice[] = total > 0 ? chart.slices.map((s) => ({ ...s, share: s.amount_paise / total })) : []
  const drawn = arcs(slices)
  const label = (s: Slice) => `${s.name}, ${rupees(s.amount_paise)}, ${percentOf(s.amount_paise, total)}`
  const go = (slug: string | null) => (slug ? onOpen(slug) : onOther())
  return (
    <>
      <div className="relative mx-auto mt-2 size-[min(14rem,78vw)]">
        <svg viewBox="0 0 120 120" className="size-full -rotate-90" role="group" aria-label="Spent by category">
          {drawn.map((a) => (
            <circle key={a.slug ?? 'other'} cx="60" cy="60" r={R} fill="none" stroke={a.slug ? catColor(a.slug) : OTHER}
              strokeWidth={WIDTH} strokeDasharray={a.dash} strokeDashoffset={a.offset} />
          ))}
          {drawn.map((a) => (
            // A wider, invisible ring on top: a finger-sized target for each slice.
            <circle key={`hit-${a.slug ?? 'other'}`} cx="60" cy="60" r={R} fill="none" stroke="transparent" strokeWidth="22"
              strokeDasharray={a.dash} strokeDashoffset={a.offset} role="button" tabIndex={0} aria-label={label(a)}
              className="cursor-pointer outline-none focus-visible:stroke-ink/15" onClick={() => go(a.slug)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), go(a.slug))} />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
          <span className="text-[min(0.875rem,4vw)] text-muted">Spent</span>
          <span className="text-[min(1.5rem,7vw)] font-semibold whitespace-nowrap tabular-nums">{rupees(spent)}</span>
        </div>
      </div>
      <Section>
        {slices.map((s) => (
          <RowButton key={s.slug ?? 'other'} onClick={() => go(s.slug)}>
            {s.slug ? (
              <CategoryTile slug={s.slug} />
            ) : (
              <span className="tile text-ink" style={{ background: OTHER }}>
                <Icon name="ellipsis" />
              </span>
            )}
            <span className="min-w-[min(6rem,35vw)] flex-1 truncate">{s.name}</span>
            <Money paise={s.amount_paise} />
            <span className="w-9 shrink-0 text-right text-sm text-muted tabular-nums">{percentOf(s.amount_paise, total)}</span>
          </RowButton>
        ))}
      </Section>
    </>
  )
}
