// The Android debug APK (5A, D-125). From frontend\:
//
//   npm run android:apk      web app (vite build --mode android) -> npx cap sync android -> Gradle
//   npm run android:web      only the web app, into dist-android/
//   npm run android:sync     only npx cap sync android
//
// The version name is package.json's, the version code is the commit count (a newer APK always
// installs over an older one), the build id is the commit. Prints the APK path and size.
import { spawnSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const FRONTEND = resolve(import.meta.dirname, '..')
const ANDROID = resolve(FRONTEND, '..', 'mobile', 'android')
const step = process.argv[2] ?? 'apk'
const windows = process.platform === 'win32'

/** One command line through the shell (npx and gradlew are scripts on Windows). */
function run(line, options = {}) {
  const result = spawnSync(line, { stdio: 'inherit', shell: true, ...options })
  if (result.status !== 0) {
    console.error(`failed: ${line}`)
    process.exit(result.status ?? 1)
  }
}

const git = (...args) => spawnSync('git', args, { encoding: 'utf8' }).stdout.trim()
const sha = git('rev-parse', '--short=7', 'HEAD')
const code = git('rev-list', '--count', 'HEAD')
const { version } = JSON.parse(readFileSync(join(FRONTEND, 'package.json'), 'utf8'))

if (step === 'web' || step === 'apk') {
  run(`"${process.execPath}" node_modules/vite/bin/vite.js build --mode android --outDir dist-android --emptyOutDir`, {
    cwd: FRONTEND,
    env: { ...process.env, FLASH_BUILD_SHA: sha },
  })
}
if (step === 'sync' || step === 'apk') run('npx cap sync android', { cwd: FRONTEND })
if (step === 'apk') {
  // The full path: cmd.exe may not look in the current folder. Quoted: cmd splits at "=".
  const gradlew = join(ANDROID, windows ? 'gradlew.bat' : 'gradlew')
  run(`"${gradlew}" assembleDebug "-PflashVersionCode=${code}" "-PflashVersionName=${version}" --console=plain`, { cwd: ANDROID })
  const apk = join(ANDROID, 'app', 'build', 'outputs', 'apk', 'debug', 'app-debug.apk')
  const mb = (statSync(apk).size / 1024 / 1024).toFixed(1)
  console.log(`\nAPK: ${apk}\n     ${mb} MB, versionName ${version}, versionCode ${code}, build ${sha}`)
}
