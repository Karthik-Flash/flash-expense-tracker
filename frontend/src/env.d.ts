interface ImportMetaEnv {
  /** The API, e.g. https://flash-api.onrender.com (no trailing /api/v1). */
  readonly VITE_API_URL?: string
  /** https://<project ref>.supabase.co */
  readonly VITE_SUPABASE_URL?: string
  /** The project's publishable key (sb_publishable_...), safe in the browser. */
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string
  /** "1": the demo adapter, local dev only. */
  readonly VITE_DEMO?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
