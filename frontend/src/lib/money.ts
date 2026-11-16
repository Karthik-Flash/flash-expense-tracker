// Money is integer paise everywhere (D-001). These only format it for display.

const MINUS = '−'

/** 1234567 -> "12,34,567": Indian grouping (last three digits, then pairs). */
export function groupIndian(whole: number): string {
  const digits = String(whole)
  if (digits.length <= 3) return digits
  const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+$)/g, ',')
  return `${head},${digits.slice(-3)}`
}

/** Overviews: whole rupees, rounded half away from zero. 12345650 -> "₹1,23,457". */
export function rupees(paise: number): string {
  const sign = paise < 0 ? MINUS : ''
  return `${sign}₹${groupIndian(Math.round(Math.abs(paise) / 100))}`
}

/** Transaction detail: rupees and paise. 12345678 -> "₹1,23,456.78". */
export function rupeesExact(paise: number): string {
  const sign = paise < 0 ? MINUS : ''
  const abs = Math.abs(paise)
  const rest = String(abs % 100).padStart(2, '0')
  return `${sign}₹${groupIndian(Math.floor(abs / 100))}.${rest}`
}

/** Money in is shown with a plus: "+₹450". */
export function moneyIn(paise: number, exact = false): string {
  return `+${exact ? rupeesExact(paise) : rupees(paise)}`
}

/** Share of a whole as "37%", "<1%" for a small part, "" when there is no whole. */
export function percentOf(part: number, whole: number): string {
  if (whole <= 0) return ''
  const share = (part / whole) * 100
  if (part > 0 && share < 1) return '<1%'
  return `${Math.round(share)}%`
}
