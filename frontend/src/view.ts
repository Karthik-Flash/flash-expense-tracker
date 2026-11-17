// Everything the owner sees lives in the URL hash, so a reload or a deep link restores it:
// "#/home/category/people/Rohit%20V?m=2026-11&txn=1042". Pure, so it is tested in Node.

export const TABS = ['home', 'transactions', 'todo', 'labels'] as const
export type Tab = (typeof TABS)[number] | 'dev'

export interface View {
  tab: Tab
  /** Below the tab: ['category', slug], ['category', slug, name], [labelId], ['logos']. */
  path: string[]
  /** "2026-11"; null means the current IST month. */
  month: string | null
  /** Transactions: category filter, label filter, name search. */
  category: string | null
  label: number | null
  q: string
  /** The transaction whose sheet is open. */
  txn: number | null
}

export const HOME: View = { tab: 'home', path: [], month: null, category: null, label: null, q: '', txn: null }

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/
const ID = /^[1-9]\d{0,14}$/

function decode(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

export function parseHash(hash: string): View {
  const rest = hash.replace(/^#\/?/, '')
  const cut = rest.indexOf('?')
  const route = cut < 0 ? rest : rest.slice(0, cut)
  const params = new URLSearchParams(cut < 0 ? '' : rest.slice(cut + 1))
  const [first = '', ...path] = route.split('/').filter(Boolean).map(decode)
  const known = (TABS as readonly string[]).includes(first) || first === 'dev'
  const id = (key: string) => {
    const value = params.get(key) ?? ''
    return ID.test(value) ? Number(value) : null
  }
  const month = params.get('m') ?? ''
  return {
    tab: known ? (first as Tab) : 'home',
    path: known ? path : [],
    month: MONTH.test(month) ? month : null,
    category: params.get('cat') || null,
    label: id('label'),
    q: params.get('q') ?? '',
    txn: id('txn'),
  }
}

export function toHash(view: View): string {
  const route = [view.tab, ...view.path].map(encodeURIComponent).join('/')
  const params = new URLSearchParams()
  if (view.month) params.set('m', view.month)
  if (view.category) params.set('cat', view.category)
  if (view.label !== null) params.set('label', String(view.label))
  if (view.q) params.set('q', view.q)
  if (view.txn !== null) params.set('txn', String(view.txn))
  const query = params.toString()
  return `#/${route}${query ? `?${query}` : ''}`
}

/** The layer under this one: the sheet closes first, then the detail, then the tab's root. */
export function parentOf(view: View): View | null {
  if (view.txn !== null) return { ...view, txn: null }
  if (view.tab === 'dev' || view.path.length === 0) return null
  const keep = view.tab === 'home' && view.path[0] === 'category' && view.path.length > 2 ? 2 : 0
  return { ...view, path: view.path.slice(0, keep) }
}

/** Root first, this view last: the history a deep link gets, so Back steps out layer by layer. */
export function stack(view: View): View[] {
  const out = [view]
  for (let up = parentOf(view); up; up = parentOf(up)) out.unshift(up)
  return out
}
