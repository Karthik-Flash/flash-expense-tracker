# Mobile

Placeholder. A Capacitor Android shell around the `frontend/` PWA comes in a
later phase (see [docs/PLAN.md](../docs/PLAN.md), Phase 6).

When it arrives, note that the root `.gitignore` ignores `*.xml` to keep SMS
backups out of git. Android projects need their XML files, so add a negation
such as `!mobile/android/**/*.xml` at that time.
