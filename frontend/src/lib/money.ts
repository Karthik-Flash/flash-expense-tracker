// Money is integer paise everywhere (D-001). This only formats it for display, in one place
// (D-113): Indian digit grouping always; totals in whole rupees; a transaction's own amount
// with paise only when they are not zero.

const MINUS = '−'

/** 1234567 -> "12,34,567": Indian grouping (last three digits, then pairs). */
export function groupIndian(whole: number): string {
  const digits = String(whole)
  if (digits.length <= 3) return digits
  const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+$)/g, ',')
  return `${head},${digits.slice(-3)}`
}

/**
 * The one money formatter.
 * - Totals (`exact` false): whole rupees, rounded half away from zero. 12345650 -> "₹1,23,457".
 * - A transaction (`exact` true): paise only when not zero. 45000 -> "₹450", 12345678 -> "₹1,23,456.78".
 * - `credit`: money in, with a plus: "+₹450".
 */
export function rupees(paise: number, exact = false, credit = false): string {
  const sign = paise < 0 ? MINUS : credit ? '+' : ''
  const abs = Math.abs(paise)
  if (!exact) return `${sign}₹${groupIndian(Math.round(abs / 100))}`
  const rest = abs % 100
  return `${sign}₹${groupIndian(Math.floor(abs / 100))}${rest ? `.${String(rest).padStart(2, '0')}` : ''}`
}

/** Share of a whole as "37%", "<1%" for a small part, "" when there is no whole. */
export function percentOf(part: number, whole: number): string {
  if (whole <= 0) return ''
  const share = (part / whole) * 100
  if (part > 0 && share < 1) return '<1%'
  return `${Math.round(share)}%`
}
