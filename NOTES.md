# Notes

Running progress log. Newest session on top. Update it at the end of every
session. Commits that change only this file can go straight to `main`;
everything else goes through a branch.

## Current status

- **Phase:** 0 (scaffold and walking skeleton) is done locally.
- **Next:** push to GitHub, confirm CI is green, then the planner refines
  Phase 1 (data model and idempotent ingestion) in `docs/PLAN.md`.
- **Waiting on the user:** GitHub CLI install and login, then the repo push.
  After that, run `scripts/redact_sms.py` on a real backup to make the sample
  for Phase 2.

## 2026-11-12: Session 1, Phase 0 scaffold

### Done

- Python 3.12.12 installed with `uv`; venv at `backend/.venv`; direct deps
  pinned in `backend/requirements.txt` and `requirements-dev.txt`.
- Backend: FastAPI `GET /health` returns `{"status": "ok", "version": "0.1.0"}`.
  CORS origins come from `CORS_ORIGINS`. SQLAlchemy engine and Alembic are
  wired to settings (no models yet). 1 pytest test passes. Ruff is clean.
- Frontend: Vite 8, React 19, TypeScript 7, Tailwind 4, vite-plugin-pwa 2
  (manifest name "Flash", placeholder bolt icons). One screen shows backend
  status. It retries every 5 s for about 2 minutes ("Server is waking up"),
  then shows "Server unreachable" with a Retry button.
- Checked in a real browser (headless Edge): "Backend online · v0.1.0" with
  the backend up, and "Server is waking up ... (attempt 3/24)" with it down.
- `scripts/redact_sms.py` (stdlib only) with 5 tests on synthetic messages.
- CI: `.github/workflows/ci.yml` runs on push to `main` and on every PR.
- `infra/render.yaml` (free plan, Singapore) and `infra/README.md` (Vercel,
  Render, Supabase, cron-job.org).
- `.claude/settings.json` denies agent reads of `data/raw/`.

### Git: what we ran

```bash
git init -b main
git add .gitignore .gitattributes .editorconfig README.md CLAUDE.md docs ...
git commit -m "chore: repo hygiene, editor config and project docs"

# One branch per piece of work, merged with an explicit merge commit
git checkout -b feat/backend-skeleton     # create and switch to a new branch
git add backend ruff.toml
git commit -m "feat(backend): FastAPI walking skeleton with /health and CORS"
git checkout main                         # back to main
git merge --no-ff feat/backend-skeleton   # --no-ff keeps the branch visible in history
git branch -d feat/backend-skeleton       # delete the merged branch

# Same loop for: feat/frontend-skeleton, feat/redact-sms-script, chore/ci-and-infra
git log --oneline --graph --all           # see the result
```

### Git cheat sheet for the daily loop

```bash
git status                               # what changed
git switch main && git pull              # start from an up-to-date main
git switch -c feat/short-name            # new branch (same as checkout -b)
git add -p                               # stage changes piece by piece
git commit -m "feat(scope): what and why"
git push -u origin feat/short-name       # then open a PR, wait for CI
git switch main && git merge --no-ff feat/short-name && git push
git branch -d feat/short-name && git push origin --delete feat/short-name
git log --oneline --graph -15            # recent history
git restore <file>                       # discard unstaged changes to a file
git stash / git stash pop                # park work, switch branches, resume
```

### Open items for the planner

1. Phase 1 schema: confirm the dedupe key recipe (for example
   `sha256(sender | normalized body | received_at)`) before the first migration.
2. Supabase keep-alive needs a DB-touching route (`/health/db`) in Phase 1.
3. Starlette warns that `httpx` with `TestClient` is deprecated and suggests
   `httpx2`. Verify that package before switching. Tests pass as they are.
4. P2P payee names are not masked by `redact_sms.py`. Decide whether the
   sample needs name masking before it is shared further.
5. Replace the placeholder PWA icons before launch.
