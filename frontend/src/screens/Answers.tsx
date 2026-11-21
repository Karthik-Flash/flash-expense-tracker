import { useState } from 'react'

import type { PartyKind } from '../api/types.ts'
import { Button } from '../ui.tsx'

export type AnswerKey = 'friend' | 'family' | 'self' | 'income' | 'investment' | 'ignore'

const NAME: Record<AnswerKey, string> = {
  friend: 'Friend',
  family: 'Family',
  self: "It's me",
  income: 'Income',
  investment: 'Investments',
  ignore: 'Ignore',
}
const pressable =
  'min-h-11 flex-1 basis-20 rounded-lg border border-line bg-surface px-2 text-sm aria-pressed:border-accent aria-pressed:font-medium'

/** Friend, Family, It's me, and More… (Income, Investments, Ignore) (D-117, D-118). When the
 *  app thinks the person may be the owner or an investment (`warn`), Friend and Family ask
 *  once: "This looks like your own account. Count it as Friend anyway?" */
export function AnswerButtons({ label, current, warn, onAnswer }: {
  label: string
  current?: AnswerKey
  warn?: PartyKind
  onAnswer: (answer: AnswerKey) => void
}) {
  const [more, setMore] = useState(current === 'income' || current === 'investment' || current === 'ignore')
  const [confirm, setConfirm] = useState<AnswerKey | null>(null)
  if (confirm) {
    const what = warn === 'self' ? 'your own account' : 'an investment'
    return (
      <div className="rounded-lg border border-line px-3 py-2 text-sm" role="group" aria-label={label}>
        <p>
          This looks like {what}. Count it as {NAME[confirm]} anyway?
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            className="flex-1"
            onClick={() => {
              onAnswer(confirm)
              setConfirm(null)
            }}
          >
            Yes, {NAME[confirm]}
          </Button>
          <Button className="flex-1" kind="primary" onClick={() => setConfirm(null)}>Cancel</Button>
        </div>
      </div>
    )
  }
  const tap = (a: AnswerKey) => ((a === 'friend' || a === 'family') && warn ? setConfirm(a) : onAnswer(a))
  const button = (a: AnswerKey) => (
    <button key={a} type="button" aria-pressed={current === a} className={pressable} onClick={() => tap(a)}>
      {NAME[a]}
    </button>
  )
  return (
    <div className="space-y-2" role="group" aria-label={label}>
      <div className="flex flex-wrap gap-2">
        {(['friend', 'family', 'self'] as const).map(button)}
        {!more && (
          <button type="button" className={pressable} aria-expanded={false} onClick={() => setMore(true)}>
            More…
          </button>
        )}
      </div>
      {more && <div className="flex flex-wrap gap-2">{(['income', 'investment', 'ignore'] as const).map(button)}</div>}
    </div>
  )
}
