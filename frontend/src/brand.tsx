// The brand, drawn as paths (no font): the $ mark, and the wordmark FLA$H with the mark as its
// S. Original geometry: three bars joined by half circles, with two stubs. docs/ui-spec.md.

/** The $ mark in a 24-unit box. Also the app icon (public/, scripts in docs/ui-spec.md). */
export const MARK_PATH = 'M16.6 6.4H9.8A2.8 2.8 0 0 0 9.8 12H14.2A2.8 2.8 0 0 1 14.2 17.6H7.4M12 2.6V6.4M12 17.6V21.4'
const LETTERS = 'M1.7 24V4H11M1.7 13.6H9.4M16 4V24H25M28.4 24L34.7 4L41 24M30.7 17.2H38.7M62 4V24M73 4V24M62 14H73'
const DOLLAR = 'M56.4 6.2H48.5A3.9 3.9 0 0 0 48.5 14H53.3A3.9 3.9 0 0 1 53.3 21.8H45.4M50.9 1.4V6.2M50.9 21.8V26.6'

export function Mark({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.9" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={MARK_PATH} />
    </svg>
  )
}

/** FLA$H, slanted for speed: letters in the text colour, the $ in the accent. */
export function Wordmark({ height = 24, className = '' }: { height?: number; className?: string }) {
  return (
    <svg height={height} viewBox="0 -1 82 30" fill="none" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" className={className} role="img" aria-label="Flash">
      <g transform="translate(5 0) skewX(-10)">
        <path d={LETTERS} stroke="currentColor" />
        <path d={DOLLAR} stroke="var(--color-accent)" />
      </g>
    </svg>
  )
}
