interface ImportMetaEnv {
  /** The API, e.g. https://flash-api.onrender.com (no trailing /api/v1). */
  readonly VITE_API_URL?: string
  /** https://<project ref>.supabase.co */
  readonly VITE_SUPABASE_URL?: string
  /** The project's publishable key (sb_publishable_...), safe in the browser. */
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string
  /** "1": the demo adapter, local dev only. */
  readonly VITE_DEMO?: string
  /** "1": test hooks for the speed check only (scripts/perf-check.mjs, D-153). */
  readonly VITE_TEST_HOOKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** "Version 0.1.0 · build 1a2b3c4", set in vite.config.ts (D-087). */
declare const __VERSION_LINE__: string
/** The Android versionCode ("214"), empty on the web (premium F). */
declare const __VERSION_CODE__: string
