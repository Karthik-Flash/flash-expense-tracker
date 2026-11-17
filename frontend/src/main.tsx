import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DEMO } from './api/index.ts'
import { startAuth } from './auth.ts'
import { startNavigation } from './state.tsx'

startNavigation()
if (!DEMO) startAuth()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
