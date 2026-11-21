# Phase 5A: Flash on Android, bank SMS read on the phone

Design for step 5A (22 Nov 2026). Goal: the owner's phone reads bank SMS by itself, in the
background, and the server classifies them as it does for a laptop import. Decisions
D-122 to D-127. The Play Store is Phase 6; the package id is fixed now:
`app.flashexpense.android`.

## Pieces

```
SMS arrives -> SmsReceiver (bank sender?) -> queue row "awaiting inbox" -> UploadWorker
                                                                              |
inbox (Telephony provider) -- scan since cursor, bank senders only --> queue "ready"
                                                                              |
           POST /api/v1/ingest/sms (device token) <-- batches of 500 ---------+
                     |
   store.ingest() as import-sms: raw_messages (content_hash), parse, transactions,
   recompute mark -> the next snapshot read recomputes -> the app shows it
```

## Shell (D-125)

- Capacitor 8.6.2 (`@capacitor/core`, `@capacitor/android`, `@capacitor/cli`, exact pins in
  `frontend/package.json`). Config `frontend/capacitor.config.json`: appId
  `app.flashexpense.android`, appName "Flash", web assets from `frontend/dist-android`, the
  Android project in `mobile/android` (the only folder where XML is tracked).
- Web assets are bundled in the APK; no `server.url`. The WebView origin is
  `https://localhost` (Capacitor's default scheme), so the API must allow it in
  `CORS_ORIGINS`. Native HTTP from Kotlin is not subject to CORS.
- `vite build --mode android` writes `dist-android/` with the public API URL; Supabase settings
  come from `frontend/.env` as for every build. In the native app the service worker is never
  registered (the update bar is not mounted): a new version comes as a new APK. The Vercel PWA
  is unchanged.
- Build: Gradle 9.9.2 and Android Gradle Plugin 9.5.1 (the template's Gradle 8.14.3 cannot run
  on JDK 25; Gradle runs on Java 25 from 9.1.0); AGP 9 compiles Kotlin itself. compileSdk and
  targetSdk 36, minSdk 24. Debug build signed with the standard debug key.
- Icons: an adaptive icon (vector C2 mark on the dark tile) and the 192 px PWA icon for older
  launchers; the Android 12+ splash shows the same mark on the page colour.
- Updates: `npm run android:apk` (frontend) builds the web app, runs `npx cap sync android`
  and `gradlew assembleDebug`, and prints the APK path; the owner installs it over the old one
  with `adb install -r`. The version code is the commit count, so a newer APK always installs.

## Server (D-122, D-123, D-126)

- Migration `0014`: `devices` (owner_id, device_id, name, token_hash, created_at,
  last_seen_at, revoked_at). RLS on, no policies.
- `POST /api/v1/devices` (login token) `{device_id, name}`: makes a random 256-bit token
  (`secrets.token_urlsafe(32)`), stores only its SHA-256, returns it once. The same
  `device_id` again gives a new token and the old one stops working, so a lost answer is
  repaired by asking again. Not through the outbox: the answer is a secret, a stored replay
  would have to keep it, and it is useless offline. `GET` lists (never a hash); `DELETE
  /api/v1/devices/{device_id}` revokes, through the outbox like every owner write.
- The device token is ingest-only: it is not a login token, so every other route answers 401;
  only `POST /api/v1/ingest/sms` accepts it (and no login token).
- Ingest: at most 500 messages of `{sender, body (2 KB), received_at_utc, device_msg_id}`.
  Each sender must be a bank: the sender list `backend/app/engine/shared/bank_senders.json` is
  read by `senders.py` and packed into the APK (one list, D-123), minus the registered
  non-banks (PhonePe). OTP and promotional messages are refused as import-sms skips them. A
  bank message goes through the same `store.ingest()` as import-sms, source `live_sms`: the
  same content hash (sender core, body, receive time in ms), so a laptop import and a phone
  upload of one SMS are one raw message. Answer per message: `stored`, `duplicate`,
  `refused_not_bank`, `refused_filtered`. A new message sets the recompute mark (D-106); the
  next read recomputes.
- The phone sends the inbox row's `date` as `received_at_utc`: it is what SMS Backup &
  Restore exports, so the hashes agree (bodies keep their line breaks: 124 of 288 sample
  messages have one).
- Statement rows (D-126): an SMS that merges into a transaction first read from the bank
  statement keeps that transaction's id (owner categories, labels, roles and checks stay).
- CORS: `https://localhost` joins the allowed origins when listed in `CORS_ORIGINS`.

## Phone (D-124)

Kotlin in `mobile/android/app/src/main/java/app/flashexpense/android/`, platform APIs and
WorkManager 2.12.0 only.

- **Plugin `FlashSms`** (Capacitor): `status`, `requestSms`, `openAppInfo`,
  `connect({token, apiUrl, user})`, `disconnect`, `startHistory({sinceMs})`,
  `syncNow`, and the event `uploaded`.
- **Permissions**: READ_SMS and RECEIVE_SMS, asked from the Bank SMS sheet. When Android
  refuses (denied for good, or "Restricted setting" on Android 15+ for a sideloaded app), the
  sheet shows the steps: App info > ⋮ > Allow restricted settings, then Permissions > SMS >
  Allow, with a button to App info.
- **Bank filter** (`BankSenders.kt`): the same sender rules as `senders.parse_sender` (tested
  on `backend/tests/fixtures/sender_ids.json`) and the same OTP rule (`otp_cases.json`). The
  inbox query asks the provider only for addresses containing a bank sender core, so other
  SMS never reach the app; each row is checked again before it is kept.
- **History and catch-up are one scan**: from a cursor (the inbox `date` of the last row
  queued, minus 10 minutes of overlap) to now, oldest first, 500 rows at a time; each chunk
  is written to the queue before the cursor moves, so a killed scan resumes. The first run
  sets the cursor: the newest message the server has (from the snapshot) minus a day, or
  3, 6 or 12 months back, as the owner picks. A repeat upload is harmless (`duplicate`).
- **Live**: a manifest receiver for `SMS_RECEIVED` (permission `BROADCAST_SMS`) keeps only
  bank messages, writes them to the queue as "awaiting inbox" and enqueues the unique upload
  work (network required, exponential backoff, 10 s delay). The upload run scans the inbox
  first; an awaiting row whose inbox row exists is done (the scan queued it with the exact
  `date`); one not in the inbox yet makes the run retry; after 24 h it is dropped (the
  message left the inbox, and a laptop export would not have it either).
- **Queue** (`SQLiteOpenHelper`, `flash_queue.db`): ready rows unique by the inbox `_id`. A
  200 answer clears every row sent (each status is final). 401 `device_revoked` stops uploads
  and says so; 5xx, timeouts and no network retry with backoff.
- **Catch-up**: periodic work every 6 h (network required) runs the same upload.
- **Token** (`TokenStore.kt`): AES-256-GCM, key in the Android Keystore (alias
  `flash-device-token`), ciphertext in private preferences; no backup (`allowBackup=false`).
  Sign-out revokes the device on the server (best effort) and wipes the token, queue, cursor
  and status. Another login on the phone disconnects it first (the phone keeps the login
  that connected it).
- **Status** for the app: permission, connected or revoked, queued count, last upload (time,
  stored, result), last error code, battery optimisation. Shown in the Bank SMS sheet and at
  the top of the Speed sheet, with a hint to set battery use to Unrestricted (App info >
  Battery) and a button that opens App info.
- **Refresh**: after an upload that stored something, the plugin emits `uploaded`; the open
  app refreshes its snapshot, so new payments appear within seconds.

## Privacy

Only bank messages leave the phone. Other SMS are never read into the app (provider query),
never queued, never logged. Logs show counts and codes only. The server logs method, route
template, status and time, never a body.

## Failure handling

| Case | What happens |
| ---- | ------------ |
| No network | Work waits for the network constraint; queue kept |
| Server asleep or 5xx | Retry with exponential backoff (from 30 s) |
| Device revoked | Uploads stop; status "revoked"; the sheet offers Connect again |
| Permission removed | Scans stop; status shows it; the receiver gets nothing |
| App killed during a scan | The cursor moves only after rows are in the queue |
| Same SMS twice (receiver and scan, or laptop and phone) | One raw message (content hash) |

## Owner install and update

1. `cd frontend; npm run android:apk` prints the APK path.
2. USB debugging on, then `adb install -r <apk>`. The same command updates.
3. First run: sign in, open Bank SMS (Home or Speed sheet), allow SMS (restricted settings if
   asked), pick the history period, set battery to Unrestricted.
