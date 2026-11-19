import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DEMO } from './api/index.ts'
import { settleAuth, startAuth } from './auth.ts'
import { bootPath, noteBootError, startWatchdog } from './boot.ts'
import { ErrorBoundary } from './crash.ts'
import { settleData } from './data/store.ts'
import { startNavigation } from './state.tsx'

// Errors before the first screen are kept for the Speed sheet (D-095).
const early = (message: string) => bootPath() || noteBootError(message)
window.addEventListener('error', (e) => early(e.message || 'Script error'))
window.addEventListener('unhandledrejection', (e) => early(e.reason instanceof Error ? e.reason.message : String(e.reason)))

startNavigation()
if (!DEMO) startAuth()
// Nothing on screen after 3 s: draw from what the device has (D-095).
startWatchdog(() => {
  settleAuth()
  settleData()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
// index.html shows "Flash could not start" when this line never runs (D-095).
;(window as { flashStarted?: boolean }).flashStarted = true
