// The top-level error boundary (D-095): an exception anywhere shows a plain screen with
// Reload and Copy details, never a blank one. The error is kept on the device (boot.ts).
// createElement, not JSX, so the node tests can load it.

import { Component, createElement as h, type ErrorInfo, type ReactNode } from 'react'

import { markPainted, noteBootError } from './boot.ts'

type Props = { children: ReactNode }
type State = { error: Error | null; details: string }

const button = 'min-h-11 rounded-lg border px-3 text-sm font-medium'

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, details: '' }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    const e = error instanceof Error ? error : new Error(String(error))
    return { error: e, details: `${e.name}: ${e.message}\n${e.stack ?? ''}`.trim() }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const e = error instanceof Error ? error : new Error(String(error))
    noteBootError(`${e.name}: ${e.message}`)
    markPainted('error screen')
    if (info.componentStack) this.setState((s) => ({ details: `${s.details}\n${info.componentStack}`.trim() }))
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    const copy = () => void navigator.clipboard?.writeText(this.state.details).catch(() => {})
    return h(
      'main',
      { className: 'mx-auto flex min-h-dvh w-full max-w-[480px] flex-col justify-center px-6 py-8', role: 'alert' },
      h('h1', { className: 'text-xl font-semibold' }, 'Something went wrong'),
      h('p', { className: 'mt-2 text-sm text-muted' }, 'Your data on this phone is safe. Reload to start the app again.'),
      h(
        'div',
        { className: 'mt-6 flex flex-wrap gap-2' },
        h('button', { type: 'button', className: `${button} border-accent bg-accent text-on-accent`, onClick: () => location.reload() }, 'Reload'),
        h('button', { type: 'button', className: `${button} border-line bg-surface text-ink`, onClick: copy }, 'Copy details'),
      ),
      h('pre', { className: 'mt-6 max-h-48 overflow-auto text-xs whitespace-pre-wrap text-muted' }, this.state.error.message),
    )
  }
}
