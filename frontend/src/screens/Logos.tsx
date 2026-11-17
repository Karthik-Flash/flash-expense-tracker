// Dev page (#/dev/logos, local demo only): the brand at the sizes it is used, light and dark,
// and the PWA icons as built (public/).

import { Mark, Wordmark } from '../brand.tsx'

function Panel({ theme }: { theme: 'light' | 'dark' }) {
  const colours = theme === 'light' ? 'bg-[#f6f6f4] text-[#1b1c1e] [--color-accent:#0e6862]' : 'bg-[#111214] text-[#e7e7e4] [--color-accent:#6bb7af]'
  return (
    <section className={`space-y-6 p-6 ${colours}`}>
      <h2 className="text-sm font-medium opacity-70">{theme === 'light' ? 'Light' : 'Dark'}</h2>
      <div className="flex flex-wrap items-end gap-5">
        {[16, 20, 24, 32, 48, 96].map((size) => (
          <span key={size} className="flex flex-col items-center gap-1">
            <Mark size={size} />
            <span className="text-xs opacity-60">{size}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-6">
        <Wordmark height={22} />
        <Wordmark height={40} />
        <Wordmark height={72} />
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <img src="/favicon.svg" width={16} height={16} alt="favicon 16" />
        <img src="/favicon.svg" width={32} height={32} alt="favicon 32" />
        <img src="/apple-touch-icon.png" width={60} height={60} alt="apple-touch-icon" />
        <img src="/pwa-192x192.png" width={96} height={96} alt="pwa 192" />
        <img src="/maskable-512x512.png" width={96} height={96} alt="maskable 512" className="rounded-full" />
      </div>
    </section>
  )
}

export function Logos() {
  return (
    <main className="mx-auto max-w-5xl">
      <h1 className="px-6 pt-6 text-lg font-semibold">Logo</h1>
      <p className="px-6 pt-1 pb-4 text-sm text-muted">The $ mark, the FLA$H wordmark and the icons, as shipped. The maskable icon is shown in a circle, as Android may crop it.</p>
      <div className="grid md:grid-cols-2">
        <Panel theme="light" />
        <Panel theme="dark" />
      </div>
    </main>
  )
}
