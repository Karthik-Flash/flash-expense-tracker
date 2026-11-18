import { readFileSync } from 'node:fs'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

import { buildId, pwaOptions } from './src/pwa.ts'

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

// https://vite.dev/config/
export default defineConfig({
  define: {
    // Vercel sets VERCEL_GIT_COMMIT_SHA at build time (D-087).
    __VERSION_LINE__: JSON.stringify(`Version ${version} · build ${buildId(process.env.VERCEL_GIT_COMMIT_SHA)}`),
  },
  plugins: [react(), tailwindcss(), VitePWA(pwaOptions)],
})
