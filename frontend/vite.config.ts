import { readFileSync } from 'node:fs'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

import { buildId, pwaOptions } from './src/pwa.ts'

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

/** The API the Android app talks to (public; docs/HANDOFF.md, "Live URLs"). */
const ANDROID_API_URL = 'https://flash-expense-tracker.onrender.com'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // The Android app (5A, D-125): `vite build --mode android` bundles the web app into the APK.
  // It always talks to the live API; the Supabase settings come from frontend/.env as for
  // every build, and the build stops when they are missing (an APK that cannot sign in).
  const android = mode === 'android'
  if (android) {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    for (const name of ['VITE_SUPABASE_URL', 'VITE_SUPABASE_PUBLISHABLE_KEY']) {
      if (!env[name]) throw new Error(`${name} is missing (frontend/.env): the Android app could not sign in`)
    }
  }
  // Vercel sets VERCEL_GIT_COMMIT_SHA at build time (D-087); scripts/android.mjs sets FLASH_BUILD_SHA.
  const sha = process.env.VERCEL_GIT_COMMIT_SHA ?? process.env.FLASH_BUILD_SHA
  return {
    define: {
      __VERSION_LINE__: JSON.stringify(`Version ${version} · build ${buildId(sha)}`),
      ...(android ? { 'import.meta.env.VITE_API_URL': JSON.stringify(ANDROID_API_URL) } : {}),
    },
    plugins: [react(), tailwindcss(), VitePWA(pwaOptions)],
  }
})
