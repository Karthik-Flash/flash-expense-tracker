# 5B-2: the phone just works

Real-phone facts (Samsung A55, Android 15): with the app closed a Rs 1 UPI payment never
reached the server; with the app open, new payments appeared only after sign-out, sign-in
and a new 12-month Bank SMS setup. Goal: a new bank SMS shows in the app and on the web by
itself; the owner never signs out, reconnects or rescans to make it happen. Decisions
D-139 to D-144.

## Android documentation checked (developer.android.com, 23 Nov 2026)

| Topic | What it says, as used here |
| ----- | -------------------------- |
| SMS_RECEIVED to manifest receivers (Implicit broadcast exceptions; Telephony.Sms.Intents) | `SMS_RECEIVED_ACTION` is exempt from the Android 8 ban on manifest receivers for implicit broadcasts; it needs RECEIVE_SMS. Kept: the manifest receiver with `BROADCAST_SMS`. |
| The stopped state (Android 15 behaviour changes, all apps) | A force-stopped app stays stopped until the user opens it: no broadcasts, its pending intents and jobs are cancelled; on leaving the state it gets BOOT_COMPLETED. So the app's start and resume now start an upload and the catch-up again; the status screen and NOTES say not to force-stop or deep-sleep Flash. |
| WorkManager expedited work and backoff (Define work requests; OutOfQuotaPolicy; WorkRequest) | `setExpedited(RUN_AS_NON_EXPEDITED_WORK_REQUEST)` falls back to normal work when the quota is spent; quotas do not apply in the foreground; before Android 12 expedited work runs as a foreground service (needs getForegroundInfo), so it is used on 12+ only. Backoff at least 10 s (MIN_BACKOFF_MILLIS), default 30 s, exponential, capped by WorkManager. |
| App standby buckets (App Standby Buckets; UsageStatsManager) | `getAppStandbyBucket()` (API 28) needs no permission; rare delays jobs, restricted blocks network for jobs. Shown in plain words on the status screen. |
| POST_NOTIFICATIONS (Notification runtime permission) | A runtime permission from Android 13; new installs start with notifications off; a channel is required. Asked in Bank SMS setup and on the status screen; denied, everything else works. |
| FileProvider sharing (Sharing a file; FileProvider) | A content URI from `<cache-path>`, `ACTION_SEND` with `FLAG_GRANT_READ_URI_PERMISSION` only, no broad paths. For the 5F export (Run 2). |

Not requested: `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` (Play policy). The status screen opens
App info (Battery, Unrestricted) and Samsung's Background usage limits instead.

## Part 1.0: why a new bank SMS did not appear (file:line at `3acf8ef`)

The path: SMS -> `SmsReceiver` (awaiting row) -> `Work.upload` -> `UploadWorker` -> `Sync.run`
(inbox scan from the cursor, settle the awaiting row, POST `/api/v1/ingest/sms`) ->
`Events.uploaded` -> the open app refreshes; the web sees it at its next snapshot.

1. **A new SMS waited behind a run in backoff.** `SmsReceiver.kt:31` called
   `Work.upload(context)`, and `Sync.kt:144` used `ExistingWorkPolicy.KEEP` unless the owner
   asked (`now`). Any earlier attempt waiting out an exponential backoff (`Sync.kt:142`, from
   30 s, doubling, up to WorkManager's cap of hours) kept its slot, so the new SMS went
   nowhere until that retry. This is the most likely cause of "with the app closed, never
   reached the server".
2. **Opening the app did not upload either.** `FlashSmsPlugin.kt:32` (`load()`) also used KEEP,
   and nothing ran on resume. Only `startHistory` and Sync now used REPLACE
   (`FlashSmsPlugin.kt:94`, `:100`): that is why sign-out, sign-in and the 12-month setup
   "fixed" it (the new setup's `startHistory` forced a run).
3. **Retries that never ended.** `Sync.kt:69` returned RETRY while any live (awaiting) row was
   not settled, for up to 24 hours (`Wire.kt:18`). Settling needed the inbox row with the
   exact same address and whitespace-only equal body (`Inbox.kt:38`, `:42`): an SMS app that
   stores the address or line breaks differently kept the run in growing backoff, which
   then blocked new SMS by item 1.
4. **Normal, delayed work.** Live uploads were not expedited and waited 10 s first
   (`Sync.kt:141`); in Doze such work waits for a maintenance window.
5. **A reconnect sent nothing.** `connect()` (`FlashSmsPlugin.kt:65-75`) saved the token and
   scheduled the catch-up, but started no upload; and the receiver dropped every SMS while
   disconnected (`SmsReceiver.kt:17`: `!store.connected || store.revoked`). Those were
   recovered only by a later scan.
6. **Sign-out wiped the place.** `signOutPhone` (`sms.ts:95-110`) called `disconnect`, which
   cleared the queue, the cursor and the status (`FlashSmsPlugin.kt:78-84`,
   `Store.kt:64-73`); signing in again meant the whole Bank SMS setup, period choice included.
7. **One malformed message could stop the queue.** Any 4xx but 401/403 was REJECTED and the
   same batch was retried for ever (`Wire.kt:75-82`, `Sync.kt:62`): a body over 2 KB or an
   odd sender (a 422 for the whole batch) blocked every later message.
8. **The cursor could skip a late row.** The scan read `DATE > cursor - 10 min`
   (`Inbox.kt:21`, `Wire.kt:48`); a row the SMS app stored late with an older date (a
   multipart reassembly, a clock correction) was never read. `date` (receive time) is the
   right field (it is what SMS Backup & Restore exports), but alone it is not enough.
9. **The catch-up was 6-hourly** (`Sync.kt:149`) with KEEP: a missed SMS could wait hours.
   It survives a reboot and `adb install -r` (WorkManager reschedules), but not a force-stop
   on Android 15 until the app is opened (item above).
10. **Upload timeouts**: connect 30 s, read 90 s (`Sync.kt:105-106`): fine for a sleeping
    Render (about 50 s), but 30 s to connect only delayed the retry when offline.
11. **Keystore and background**: the token key has no user-authentication requirement
    (`Store.kt:99-111`), so background work can open it after the first unlock; before it
    the app (not direct-boot aware) does not run, and the scan catches up later. Not a cause.
12. **Session expiry in the app**: a snapshot 401 went straight to "Sign in to sync" with no
    token refresh and retry (`http.ts:88-89`); the only sign was a small link in the
    freshness line (`ui.tsx`), easy to miss: stale data looked current.

## What changed (Run 1)

- **Three idempotent paths** into one run (`Sync.kt`): the live receiver (expedited on
  Android 12+, normal work when out of quota), the app's start and resume plus the hourly
  catch-up (network required), and Sync now (incremental, never a 12-month read). Every
  trigger replaces a run waiting out a backoff; a run in progress finishes first and the new
  one follows (APPEND_OR_REPLACE).
- **Upload**: connect 15 s, read 90 s. Retry with backoff on no network, timeouts, 5xx, 408,
  429 and other 4xx. 413 and 422 send one by one and drop only the row the server refused.
  401 and 403 keep the queue and say "Phone disconnected" with Reconnect. Rows the server
  would refuse (`Wire.sendable`) are never queued.
- **Cursor**: the inbox date and the highest `_id` (`Store.lastId`); a page is written to the
  queue before either moves; a `seen` table (3 days) keeps the overlap from being re-sent.
- **Two copies of one SMS**: a live SMS whose inbox row has not come after 2 minutes is
  sent itself (origin live); the server joins it with the inbox copy (D-139). The inbox
  match uses the sender core and `Wire.normalBody`, the server's rule, both tested on
  `backend/tests/fixtures/body_normalise.json`.
- **Reconnect** keeps the cursor and the queue and sends what came meanwhile, quietly; sign-out
  keeps them for the same login, which reconnects by itself at its next sign-in (D-143).
  Scan history again is behind a confirmation.
- **Cheap refresh**: the snapshot's ETag comes from a per-owner data version (D-140); a 304
  is 9 statements and never builds the snapshot.
- **Notifications** for new payments (D-141, D-142) and the **status screen** with the event
  log and Copy diagnostics (D-142).

## Load after 5B-2

Measured on FAKE data: a 304 is 9 small statements (the login, the freshness check, the
version, the account block), a few kilobytes from the database at most; a full snapshot (704
transactions) is about 2 MB of database reads, now only when something changed. With 60 s
polling while the app is open (30 minutes a day): about 30 polls a day, nearly all 304s,
under 1 MB a day; full builds only after a write or an upload, say 10 a day, about 20 MB a
day, about 0.6 GB a month for the owner (was about 1.8 GB estimated in 5B-1). Uploads add one
recompute per new payment batch. Within Supabase's 5 GB and Render's free hours.
