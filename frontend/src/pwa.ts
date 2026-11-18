import type { VitePWAOptions } from 'vite-plugin-pwa'

/**
 * The PWA plugin options, kept apart from vite.config.ts so a test can read them.
 *
 * - Updates wait for the owner (D-085): registerType "prompt"; the update bar asks.
 * - The service worker precaches the app shell only (D-086). No runtimeCaching:
 *   API and Supabase requests always go to the network. Offline data is 4B.
 */
export const pwaOptions: Partial<VitePWAOptions> = {
  registerType: 'prompt',
  includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
  manifest: {
    // id equals the id browsers already computed from start_url, so installs are not duplicated.
    id: '/',
    name: 'Flash Expense Tracker',
    short_name: 'Flash',
    description: 'Personal expense tracker',
    // The light page colour (index.css --color-bg): the splash shows what the first paint shows.
    theme_color: '#f6f6f4',
    background_color: '#f6f6f4',
    display: 'standalone',
    start_url: '/',
    scope: '/',
    // The $ mark on the dark tile (docs/ui-spec.md, "Logo").
    icons: [
      { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
      { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
      { src: 'maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  },
  workbox: {
    navigateFallback: 'index.html',
    cleanupOutdatedCaches: true,
  },
}

/** The build id shown in the app (D-087): the commit's first 7 characters, "dev" without one. */
export function buildId(sha: string | undefined): string {
  const s = sha?.trim()
  return s ? s.slice(0, 7) : 'dev'
}
