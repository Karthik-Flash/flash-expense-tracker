// Dev page (#/dev/logos): three original marks for the owner to pick from. Drawn here from
// plain shapes, not traced. The PWA icons stay as they are until one is chosen.

import { useId } from 'react'

type Mark = (props: { size: number }) => React.JSX.Element

/** Tally: three bars, longest first, like Spent by category. */
function Tally({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" aria-hidden="true">
      <path d="M6 8.5h20M6 16h13M6 23.5h6" />
    </svg>
  )
}

/** Split: a solid tile parted by a stepped line into two interlocking parts. */
function Split({ size }: { size: number }) {
  const id = `split${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <mask id={id}>
        <rect width="32" height="32" fill="#fff" />
        <path d="M1 13h14v6h16" fill="none" stroke="#000" strokeWidth="3" />
      </mask>
      <rect x="4" y="4" width="24" height="24" rx="7" fill="currentColor" mask={`url(#${id})`} />
    </svg>
  )
}

/** Step: a level line that drops once and carries on, a quick fall. */
function Step({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 10h10l3 12h9" />
    </svg>
  )
}

const MARKS: [string, string, Mark][] = [
  ['Tally', 'Three bars, longest first, like Spent by category.', Tally],
  ['Split', 'A solid tile parted by a stepped line into two parts.', Split],
  ['Step', 'A level line that drops once: a quick fall.', Step],
]

// The spec's surface, ink and muted colours, fixed here so both themes show side by side.
const THEMES = [
  { name: 'Light', bg: '#ffffff', ink: '#1b1c1e', muted: '#5c6066', line: '#e2e2de' },
  { name: 'Dark', bg: '#18191b', ink: '#e7e7e4', muted: '#a3a6ab', line: '#2a2c2f' },
]

export function Logos() {
  return (
    <main className="mx-auto max-w-[960px] px-4 py-6">
      <h1 className="text-lg font-semibold">Logo options</h1>
      <p className="mt-1 text-sm text-muted">Three monochrome marks for Flash, at 16, 24, 32, 48 and 96 px. Dev page: nothing in the app uses them yet.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {THEMES.map((t) => (
          <section key={t.name} className="rounded-lg border p-4" style={{ background: t.bg, color: t.ink, borderColor: t.line }}>
            <h2 className="text-sm font-medium" style={{ color: t.muted }}>{t.name}</h2>
            {MARKS.map(([name, note, Mark]) => (
              <div key={name} className="border-t py-4 first-of-type:border-t-0" style={{ borderColor: t.line }}>
                <p className="font-medium">{name}</p>
                <p className="text-sm" style={{ color: t.muted }}>{note}</p>
                <div className="mt-3 flex flex-wrap items-end gap-4">
                  {[16, 24, 32, 48, 96].map((size) => <Mark key={size} size={size} />)}
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <Mark size={28} />
                  <span className="text-2xl font-semibold tracking-tight">Flash</span>
                </div>
              </div>
            ))}
          </section>
        ))}
      </div>
    </main>
  )
}
