// Pull-to-refresh on touch screens (5B-1, D-135), no package: a finger that starts at the
// top of the page and moves down. The indicator follows at half speed, up to a limit; past
// the trigger, letting go refreshes. Pure, so it is tested in Node; PullToRefresh (ui.tsx)
// wires it to touch events.

export const PULL_MAX_PX = 80
export const PULL_TRIGGER_PX = 56

/** How far the indicator has moved for a finger `dy` px below where it started. */
export function pullDistance(dy: number): number {
  return dy <= 0 ? 0 : Math.min(PULL_MAX_PX, dy / 2)
}

export type PullState = 'idle' | 'pulling' | 'ready'

/** idle (no pull), pulling (not far enough yet) or ready (letting go refreshes). */
export function pullState(dy: number): PullState {
  const d = pullDistance(dy)
  if (d === 0) return 'idle'
  return d >= PULL_TRIGGER_PX ? 'ready' : 'pulling'
}

/** A pull may start only at the very top of the page, never inside a sheet (it scrolls on its
 *  own) or a field. */
export function canStart(scrollY: number, insideSheetOrField: boolean): boolean {
  return scrollY <= 0 && !insideSheetOrField
}
