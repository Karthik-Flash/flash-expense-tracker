// The brand, drawn as paths (no font): logo C2 (4F-A), a flat-topped lightning bolt slanted
// like the wordmark, with the app's $ cut through it at the bolt's centre of area. The
// wordmark FLA$H uses the same bolt, cut the same way, as its S. docs/ui-spec.md (Logo).

import { useId } from 'react'

/** The $ (three bars joined by half circles, two stubs) in a 24-unit box: the cut. */
export const MARK_PATH = 'M16.6 6.4H9.8A2.8 2.8 0 0 0 9.8 12H14.2A2.8 2.8 0 0 1 14.2 17.6H7.4M12 2.6V6.4M12 17.6V21.4'
/** The bolt, already slanted 10 degrees, in a 24-unit box. */
const BOLT_24 = 'M10.94 0.96 L19.43 0.96 L14.31 9.79 L18.96 9.79 L5.4 23.04 L9.78 13.77 L4.57 13.77Z'
const CUT_24 = 'translate(11.87 9.32) scale(0.6455) translate(-12 -12)'
const LETTERS = 'M1.7 24V4H11M1.7 13.6H9.4M16 4V24H25M28.4 24L34.7 4L41 24M30.7 17.2H38.7M62 4V24M73 4V24M62 14H73'
/** The same bolt upright: the wordmark's slant tilts it with the letters. */
const BOLT_WORD = 'M48.67 2.2 L57.75 2.2 L53.94 11.64 L58.92 11.64 L46.92 25.8 L49.84 15.89 L44.28 15.89Z'
const CUT_WORD = 'translate(51.24 11.13) scale(0.6899) translate(-12 -12)'
const CUT_WIDTH = 3.264 // in $ units: the same share of the bolt in the mark and the wordmark

/** The bolt with the $ cut out, in the current colour. Also the app icon (public/). */
export function Mark({ size = 24, className = '' }: { size?: number; className?: string }) {
  const cut = useId()
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} aria-hidden="true">
      <mask id={cut} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
        <rect width="24" height="24" fill="white" />
        <path d={MARK_PATH} transform={CUT_24} fill="none" stroke="black" strokeWidth={CUT_WIDTH} strokeLinecap="round" strokeLinejoin="round" />
      </mask>
      <path d={BOLT_24} fill="currentColor" stroke="currentColor" strokeWidth="0.34" strokeLinejoin="round" mask={`url(#${cut})`} />
    </svg>
  )
}

/** FLA$H, slanted for speed: letters in the text colour, the bolt (its $ cut out) in the accent. */
export function Wordmark({ height = 24, className = '' }: { height?: number; className?: string }) {
  const cut = useId()
  return (
    <svg height={height} viewBox="0 -1 82 30" fill="none" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" className={className} role="img" aria-label="Flash">
      <mask id={cut} maskUnits="userSpaceOnUse" x="38" y="-2" width="28" height="32">
        <rect x="38" y="-2" width="28" height="32" fill="white" />
        <path d={MARK_PATH} transform={CUT_WORD} stroke="black" strokeWidth={CUT_WIDTH} />
      </mask>
      <g transform="translate(5 0) skewX(-10)">
        <path d={LETTERS} stroke="currentColor" />
        <path d={BOLT_WORD} fill="var(--color-accent)" stroke="var(--color-accent)" strokeWidth="0.6" mask={`url(#${cut})`} />
      </g>
    </svg>
  )
}
