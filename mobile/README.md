# Mobile

The Android app (5A, D-122 to D-125): a Capacitor 8.6.2 shell around the
`frontend/` web app, plus a Kotlin plugin that reads bank SMS on the phone and
uploads them. Design: [docs/design/phase-5a-android.md](../docs/design/phase-5a-android.md).

| Path | What |
| ---- | ---- |
| `android/` | The Gradle project (Gradle 9.9.2, Android Gradle Plugin 9.5.1, JDK 25 runs it) |
| `android/app/src/main/java/app/flashexpense/android/` | `MainActivity`, `FlashSmsPlugin` (the web app's door), `SmsReceiver` (live SMS), `Sync` (scan, queue, upload, WorkManager), `SmsQueue` (SQLite), `Inbox` (Telephony provider), `Store` (preferences, Keystore-sealed token), `SenderRules` and `Wire` (pure, JVM-tested) |
| `android/app/src/test/` | JVM unit tests: sender filter on the server's fixtures, wire format, pages and cursor, answers, AES-GCM |
| `android/app/src/androidTest/` | On a phone or emulator only: the SQLite queue and the Keystore |

The capacitor config lives in `frontend/capacitor.config.json`; the bank sender
list is the server's `backend/app/engine/shared/bank_senders.json`, packed into
the APK at build time. The root `.gitignore` ignores `*.xml` (SMS backups)
except under `mobile/`.

```powershell
cd frontend
npm run android:apk        # web app -> npx cap sync android -> gradlew assembleDebug; prints the APK path
cd ..\mobile\android
.\gradlew.bat testDebugUnitTest            # Kotlin unit tests (JVM)
.\gradlew.bat assembleDebugAndroidTest     # compiles the on-device tests
```

The APK needs the Supabase sign-in settings at build time
(`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend/.env` or the
environment, the same values as on Vercel); the build stops without them.
