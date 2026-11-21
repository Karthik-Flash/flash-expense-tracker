// Builds docs/design/screens-4h.html from two screens.mjs runs (before and after 4H): one
// self-contained page, the pictures inlined, no external resources. From frontend\:
//
//   node scripts/screens-page.mjs --after <folder> --before <folder>
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? resolve(process.argv[i + 1]) : null
}
const AFTER = arg('after')
const BEFORE = arg('before')
const OUT = resolve(import.meta.dirname, '../../docs/design/screens-4h.html')

const SCREENS = [
  ['login', 'Login'],
  ['home', 'Home'],
  ['home-chart', 'Home, chart'],
  ['home-empty-month', 'Home, a month with no data'],
  ['category', 'A category'],
  ['merchant', 'One merchant'],
  ['people', 'People ledger'],
  ['sheet-person', 'Person sheet (D-110)'],
  ['transactions', 'Transactions'],
  ['sheet-transaction', 'Transaction sheet'],
  ['sheet-transaction-category', 'Transaction sheet, category'],
  ['sheet-transaction-label', 'Transaction sheet, label'],
  ['todo', 'To-do'],
  ['labels', 'Labels'],
  ['label-detail', 'A label'],
  ['sheet-speed', 'Speed sheet'],
  ['sheet-unsaved', 'Not saved sheet'],
  ['state-empty', 'No data: Home'],
  ['state-empty-todo', 'No data: To-do'],
  ['state-empty-labels', 'No data: Labels'],
  ['state-empty-transactions', 'No data: Transactions'],
  ['state-empty-people', 'No data: People'],
  ['state-error', 'Error'],
  ['state-waking', 'Server waking'],
  ['state-stale', 'Totals being updated'],
]
const MODES = [['light', 'Light'], ['dark', 'Dark'], ['text200', '200 % text']]

const img = (dir, file, alt) => {
  const path = dir && join(dir, file)
  if (!path || !existsSync(path)) return '<p class="none">not captured</p>'
  return `<img loading="lazy" alt="${alt}" src="data:image/jpeg;base64,${readFileSync(path).toString('base64')}">`
}
const report = (dir) => (dir && existsSync(join(dir, 'report.json')) ? JSON.parse(readFileSync(join(dir, 'report.json'), 'utf8')) : {})
const after = report(AFTER)
const before = report(BEFORE)
const findings = (r) => (r ? [r.sideways && 'scrolls sideways', r.outside.length && `${r.outside.length} past the edge`, r.clipped.length && `${r.clipped.length} squeezed`].filter(Boolean).join(', ') || 'none' : '–')

const sections = SCREENS.map(([key, title]) => {
  const cells = MODES.map(([mode, label]) => `
      <figure><figcaption>After · ${label}<br><small>${findings(after[`${key}-${mode}`])}</small></figcaption>${img(AFTER, `${key}-${mode}.jpg`, `${title}, after, ${label}`)}</figure>`).join('')
  const old = ['light', 'text200'].map((mode) => `
      <figure class="before"><figcaption>Before · ${mode === 'light' ? 'Light' : '200 % text'}<br><small>${findings(before[`${key}-${mode}`])}</small></figcaption>${img(BEFORE, `${key}-${mode}.jpg`, `${title}, before, ${mode}`)}</figure>`).join('')
  return `
  <section id="${key}">
    <h2>${title}</h2>
    <div class="row">${cells}${old}
    </div>
  </section>`
}).join('')

const count = (r) => Object.values(r).filter((x) => x.sideways || x.outside.length || x.clipped.length).length
const html = `<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flash screens, 4H review</title>
<style>
  :root { --bg: #f6f6f4; --ink: #1b1c1e; --muted: #5c6066; --line: #e2e2de; --card: #fff; }
  @media (prefers-color-scheme: dark) { :root { --bg: #111214; --ink: #e7e7e4; --muted: #a3a6ab; --line: #2a2c2f; --card: #18191b; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header, section { padding: 16px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 0 0 8px; }
  p { margin: 0 0 8px; color: var(--muted); max-width: 70ch; }
  nav a { color: inherit; margin-right: 12px; }
  .row { display: flex; gap: 12px; overflow-x: auto; align-items: flex-start; padding-bottom: 8px; }
  figure { margin: 0; flex: none; width: 240px; }
  figure.before { opacity: 0.85; }
  figcaption { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  img { width: 240px; height: auto; border: 1px solid var(--line); border-radius: 8px; display: block; background: var(--card); }
  .none { width: 240px; border: 1px dashed var(--line); border-radius: 8px; padding: 24px 8px; text-align: center; }
  small { color: var(--muted); }
</style>
</head>
<body>
<header>
  <h1>Flash: every screen and sheet, 4H review</h1>
  <p>Demo build with FAKE data, 360 px wide, light, dark and 200 % text (the root font size doubled). Each row shows the screen after 4H in all three, then before 4H (light and 200 % text). Under each picture: the automatic check, counting elements past the screen edge, text squeezed to less than half its width, and sideways scrolling.</p>
  <p>Shots with a finding: after ${count(after)} of ${Object.keys(after).length}; before ${count(before)} of ${Object.keys(before).length}. Background screens under a sheet are counted too.</p>
  <nav>${SCREENS.map(([key, title]) => `<a href="#${key}">${title}</a>`).join(' ')}</nav>
</header>${sections}
</body>
</html>
`
writeFileSync(OUT, html)
console.log(`wrote ${OUT} (${(html.length / 1024 / 1024).toFixed(1)} MB)`)
