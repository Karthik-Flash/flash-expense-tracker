# Flash Expense Tracker

Flash turns the SMS alerts Indian banks send for every card payment, UPI transfer and ATM
withdrawal into a clear monthly picture: how much you spent, how much friends paid you
back, where it went, and what still needs your decision. It is built for students and
people in their first job, who split bills constantly. There is no manual entry and no bank
login: the Android app reads only bank SMS on the phone and uploads them; a Python engine
on the server works out what each payment is.

| Home | Transactions | To-do | Home, dark |
| --- | --- | --- | --- |
| <img src="docs/images/demo-home-light.jpg" width="180" alt="Home: Net, Spent and Paid back for the month, spending by category"> | <img src="docs/images/demo-transactions-light.jpg" width="180" alt="Transactions grouped by day with filters"> | <img src="docs/images/demo-todo-light.jpg" width="180" alt="To-do: questions only the owner can answer"> | <img src="docs/images/demo-home-chart-dark.jpg" width="180" alt="Home in dark mode with the category ring chart"> |

Demo data only (made-up names and amounts).

## Key features

- **Reads bank SMS on the phone**, at once and in the background, and uploads only bank
  messages; a notification for each new payment.
- **Works out every payment**: spending, refunds, friends paying you back, income,
  transfers between your own accounts, duplicate messages. HDFC and SBI have their own
  parsers; other banks are read carefully by a generic one.
- **Categories on their own** from Indian brands, chains and keywords; your answers and
  rules ("All payments to <name>") always win.
- **Insights**: monthly bars, categories over time, top places and people, Excel or CSV
  export.
- **Offline first**: the app opens from its copy on the phone; every answer is saved on the
  phone and sent once.
- **Several users** by invite; each sees only their own data.

## Privacy promise

- **Only your banks' SMS** leave the phone. Never one-time passwords, promotions or personal
  messages.
- **Stored**: those bank SMS, what Flash reads from them, your answers and your email, on
  servers in Singapore. Nobody else can see your data; the admin sees counts only.
- **No lending, no ads, no credit scoring.** Nothing is shared or sold.
- **Delete everything** from the app at any time.

Full text: [docs/privacy.md](docs/privacy.md).

## Architecture

```mermaid
flowchart LR
  Phone["Android app<br/>Kotlin SMS plugin + web app"] -- "bank SMS (device token)" --> API
  Phone -- "snapshot, answers" --> API
  Web["Website (Vercel)"] --> API
  API["FastAPI on Render"] --> Engine["Engine: parse, merchant,<br/>reconcile, categorise"]
  API --> DB[("Supabase Postgres + Auth")]
  CI["GitHub Actions CI"] -- "green: deploy + migrate" --> API
  CI -. "push: build" .-> Web
```

How it all works, file by file: [Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md).

## Repository map

| Folder | What it holds |
| --- | --- |
| `backend/` | FastAPI app, the engine, owner CLI, Alembic migrations, pytest |
| `frontend/` | React + Vite + TypeScript app: the website and the Android app's screens |
| `mobile/` | The Capacitor Android project and the Kotlin SMS plugin |
| `scripts/` | Redaction, surveys, database backup and the weekly backup task |
| `infra/` | Render service reference (`render.yaml`) and hosting guide |
| `docs/` | Decisions, API, data model, engine, privacy, operations, UI spec, design notes |
| `data/` | Ignored by git; only its README is tracked |

## Developer quick start (Windows, PowerShell)

Prerequisites (pinned in the repo): Python 3.12 (`PYTHON_VERSION` 3.12.12 on Render), Node 24
(CI), Docker Desktop for Postgres 17, and for the APK Android Studio's bundled JDK 25 and the
Android SDK (compile/target SDK 36, minimum 26), Gradle 9.9.2 and AGP 9.5.1 (wrapper),
Capacitor 8.6.2.

**Backend** (from `backend\`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env            # local SQLite by default
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000   # http://localhost:8000/health
.\.venv\Scripts\python.exe -m pytest -q                                    # SQLite
docker run -d --rm --name flash-pg-test -e POSTGRES_USER=flash -e POSTGRES_PASSWORD=flash-ci -e POSTGRES_DB=flash_test -p 15432:5432 postgres:17
$env:TEST_DATABASE_URL = 'postgresql+psycopg://flash:flash-ci@127.0.0.1:15432/flash_test'
.\.venv\Scripts\python.exe -m pytest -q                                    # Postgres 17
```

Lint (from the repo root): `backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .`

**Frontend** (from `frontend\`):

```powershell
npm ci
Copy-Item .env.example .env
npm run dev        # http://localhost:5173; VITE_DEMO=1 in .env runs on demo data
npm run lint; npm run typecheck; npm test; npm run build
```

**Debug APK** (from `frontend\`, with the Supabase sign-in values in `frontend\.env`):

```powershell
$env:JAVA_HOME = 'D:\Applications2\AndroidStudio\jbr'   # Android Studio's JDK
npm run android:apk                                     # prints the APK path and versionCode
adb install -r ..\mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

Kotlin tests: from `mobile\android\`, `.\gradlew.bat testDebugUnitTest`.

## Deployment

- **Vercel** builds and serves `frontend/` on every push to `main`.
- **Render** (free web service, Singapore) waits for CI to pass, then runs
  `pip install -r requirements.txt && alembic upgrade head` and starts
  `uvicorn app.main:app` (`infra/render.yaml`). A failed migration keeps the old version
  serving.
- **Supabase** holds Postgres and Auth (free plan); a daily cron-job.org call keeps it from
  pausing.
- **CI** (`.github/workflows/ci.yml`): ruff and pytest on SQLite, migrations and pytest on
  Postgres 17, frontend lint, typecheck, tests and build.

Owner commands, deploy steps, backups and the phone test plan: [docs/operations.md](docs/operations.md).

## Status

Phase 5 (the Android app, several users, insights) is done and deployed. Phase 6, the Play
Store, is next. See [Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md),
[docs/DECISIONS.md](docs/DECISIONS.md), [docs/privacy.md](docs/privacy.md) and
[CHANGELOG.md](CHANGELOG.md). Rules for contributors and Claude Code: [CLAUDE.md](CLAUDE.md).

## Licence

MIT; see [LICENSE](LICENSE).
