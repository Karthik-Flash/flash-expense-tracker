// The colour rules of docs/ui-spec.md (D-113), read from index.css: every text colour meets
// WCAG AA (4.5:1) on the backgrounds it sits on; every category colour has 3:1 against the
// surface and its own tile; every two category colours are at least 10 apart (CIEDE2000),
// so neighbouring ring segments and list rows read apart. Both themes.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const css = readFileSync(new URL('./index.css', import.meta.url), 'utf8')
const tokens = (text: string) => Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/g)].map((m) => [m[1], m[2]]))
const dark = [...css.matchAll(/@media \(prefers-color-scheme: dark\) \{/g)].map((m) => m.index)
const rootAt = css.indexOf(':root {\n  color-scheme')
const THEMES = {
  light: { ...tokens(css.slice(css.indexOf('@theme'), dark[0])), ...tokens(css.slice(rootAt, dark[1])) },
  dark: { ...tokens(css.slice(dark[0], rootAt)), ...tokens(css.slice(dark[1], css.indexOf('html,'))) },
}
const TINT = { light: 0.13, dark: 0.2 }

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
const linear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const luminance = (hex: string) => {
  const [r, g, b] = rgb(hex).map(linear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const mix = (fg: string, bg: string, share: number) => {
  const [a, b] = [fg, bg].map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)))
  return `#${a.map((x, i) => Math.round(x * share + b[i] * (1 - share)).toString(16).padStart(2, '0')).join('')}`
}

function lab(hex: string): [number, number, number] {
  const [r, g, b] = rgb(hex).map(linear)
  const f = (v: number) => (v > 0.008856 ? Math.cbrt(v) : 7.787 * v + 16 / 116)
  const x = f((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047)
  const y = f(0.2126 * r + 0.7152 * g + 0.0722 * b)
  const z = f((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)]
}

/** CIEDE2000 colour difference. */
function deltaE(c1: string, c2: string): number {
  const rad = Math.PI / 180
  const [L1, a1, b1] = lab(c1)
  const [L2, a2, b2] = lab(c2)
  const Cb = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
  const [a1p, a2p] = [a1 * (1 + G), a2 * (1 + G)]
  const [C1, C2] = [Math.hypot(a1p, b1), Math.hypot(a2p, b2)]
  const h1 = ((Math.atan2(b1, a1p) / rad) % 360 + 360) % 360
  const h2 = ((Math.atan2(b2, a2p) / rad) % 360 + 360) % 360
  let dh = C1 * C2 === 0 ? 0 : h2 - h1
  if (dh > 180) dh -= 360
  else if (dh < -180) dh += 360
  const dH = 2 * Math.sqrt(C1 * C2) * Math.sin((dh / 2) * rad)
  const Lb = (L1 + L2) / 2
  const Cp = (C1 + C2) / 2
  const hb = C1 * C2 === 0 ? h1 + h2 : Math.abs(h1 - h2) <= 180 ? (h1 + h2) / 2 : (h1 + h2 + 360) / 2
  const T = 1 - 0.17 * Math.cos((hb - 30) * rad) + 0.24 * Math.cos(2 * hb * rad) + 0.32 * Math.cos((3 * hb + 6) * rad) - 0.2 * Math.cos((4 * hb - 63) * rad)
  const SL = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2)
  const SC = 1 + 0.045 * Cp
  const SH = 1 + 0.015 * Cp * T
  const RT = -2 * Math.sqrt(Cp ** 7 / (Cp ** 7 + 25 ** 7)) * Math.sin(60 * Math.exp(-(((hb - 275) / 25) ** 2)) * rad)
  const [dL, dC] = [(L2 - L1) / SL, (C2 - C1) / SC]
  return Math.sqrt(dL ** 2 + dC ** 2 + (dH / SH) ** 2 + RT * dC * (dH / SH))
}

test('colour difference: the same colour is 0, black and white are far apart', () => {
  assert.equal(deltaE('#123456', '#123456'), 0)
  assert.ok(deltaE('#000000', '#ffffff') > 99)
})

for (const [name, t] of Object.entries(THEMES)) {
  test(`${name}: text colours meet WCAG AA on every background`, () => {
    for (const fg of ['ink', 'muted', 'accent', 'positive', 'danger']) {
      for (const bg of ['bg', 'surface', 'press', 'banner']) {
        const c = contrast(t[`color-${fg}`], t[`color-${bg}`])
        assert.ok(c >= 4.5, `${fg} on ${bg}: ${c.toFixed(2)}`)
      }
    }
    assert.ok(contrast(t['color-on-accent'], t['color-accent']) >= 4.5)
  })

  test(`${name}: category colours read on the surface and apart from each other`, () => {
    const cats = Object.entries(t).filter(([k]) => k.startsWith('cat-'))
    assert.equal(cats.length, 20)
    for (const [k, v] of cats) {
      assert.ok(contrast(v, t['color-surface']) >= 3, `${k} on surface`)
      assert.ok(contrast(v, mix(v, t['color-surface'], TINT[name as keyof typeof TINT])) >= 3, `${k} on its tile`)
    }
    for (const [i, [k1, v1]] of cats.entries()) {
      for (const [k2, v2] of cats.slice(i + 1)) {
        const d = deltaE(v1, v2)
        assert.ok(d >= 10, `${k1} / ${k2}: ${d.toFixed(1)}`)
      }
    }
  })
}
