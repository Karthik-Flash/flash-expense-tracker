package app.flashexpense.android

import android.Manifest
import android.app.usage.UsageStatsManager
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import java.time.Instant

/**
 * The web app's door to bank SMS on this phone (frontend/src/native/sms.ts). The device token
 * passes through once (connect) and is sealed at once; nothing here returns it or a message.
 * 5B-2 (D-142, D-143): uploads start on the app's start and resume; Reconnect keeps the cursor;
 * sign-out keeps the cursor and the queue for the same login; notifications open a payment.
 */
@CapacitorPlugin(
    name = "FlashSms",
    permissions = [
        Permission(alias = "sms", strings = [Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS]),
        Permission(alias = "notifications", strings = [Manifest.permission.POST_NOTIFICATIONS]),
    ],
)
class FlashSmsPlugin : Plugin() {
    /** A notification tap that started the app (cold start), until the web app asks for it. */
    private var pendingOpen: JSObject? = null

    override fun load() {
        Events.listener = { stored -> notifyListeners("uploaded", JSObject().put("stored", stored)) }
        Notify.channel(context)
        pendingOpen = openOf(activity?.intent)
        if (Store(context).cursorMs != null) {
            Work.catchUp(context)
            Work.upload(context, "start")
        }
    }

    override fun handleOnResume() {
        if (Store(context).cursorMs != null) Work.upload(context, "resume")
    }

    /** A notification tap while the app runs (warm start, singleTask). */
    override fun handleOnNewIntent(intent: Intent) {
        openOf(intent)?.let { notifyListeners("open", it, true) }
    }

    override fun handleOnDestroy() {
        Events.listener = null
    }

    private fun openOf(intent: Intent?): JSObject? {
        val txn = intent?.getLongExtra(Notify.EXTRA_TXN, -1L) ?: -1L
        if (txn <= 0) return null
        intent?.removeExtra(Notify.EXTRA_TXN) // a later resume does not open it again
        return JSObject().put("txnId", txn).put("act", intent?.getStringExtra(Notify.EXTRA_ACT) ?: "sheet")
    }

    /** The payment a notification opened the app at (cold start), once. */
    @PluginMethod
    fun takeOpen(call: PluginCall) {
        val open = pendingOpen
        pendingOpen = null
        call.resolve(JSObject().put("open", open))
    }

    @PluginMethod
    fun status(call: PluginCall) = call.resolve(statusObject())

    @PluginMethod
    fun requestSms(call: PluginCall) {
        if (getPermissionState("sms") == PermissionState.GRANTED) return call.resolve(statusObject())
        requestPermissionForAlias("sms", call, "smsAnswered")
    }

    @PermissionCallback
    private fun smsAnswered(call: PluginCall) {
        if (getPermissionState("sms") == PermissionState.GRANTED && Store(context).connected) Work.upload(context, "permission")
        call.resolve(statusObject().put("asked", true))
    }

    /** Android 13+: the "Payments" notifications (D-142). Earlier versions need no question. */
    @PluginMethod
    fun requestNotifications(call: PluginCall) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || getPermissionState("notifications") == PermissionState.GRANTED) {
            return call.resolve(statusObject())
        }
        requestPermissionForAlias("notifications", call, "notificationsAnswered")
    }

    @PermissionCallback
    private fun notificationsAnswered(call: PluginCall) = call.resolve(statusObject())

    /** App info: Permissions, Battery (Unrestricted), and ⋮ > Allow restricted settings. */
    @PluginMethod
    fun openAppInfo(call: PluginCall) {
        start(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)))
        call.resolve()
    }

    /** Samsung's "Never auto sleeping apps" (Device care > Battery > Background usage limits),
     *  else Android's battery optimisation list. Opened, never requested (Play policy). */
    @PluginMethod
    fun openSleepingApps(call: PluginCall) {
        val samsung = listOf(
            ComponentName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity"),
            ComponentName("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        )
        val opened = (if (Build.MANUFACTURER.equals("samsung", true)) samsung else emptyList()).any { start(Intent().setComponent(it)) } ||
            start(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) ||
            start(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)))
        call.resolve(JSObject().put("opened", opened))
    }

    private fun start(intent: Intent): Boolean = try {
        activity.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (e: ActivityNotFoundException) {
        false
    } catch (e: SecurityException) {
        false
    }

    /** The token from POST /api/v1/devices, and the API address. Sealed, then forgotten here.
     *  A reconnect keeps the cursor and the queue: what came meanwhile is sent, quietly. */
    @PluginMethod
    fun connect(call: PluginCall) {
        val token = call.getString("token")
        val apiUrl = call.getString("apiUrl")?.trimEnd('/')
        val user = call.getString("user")
        if (token.isNullOrBlank() || user.isNullOrBlank() || apiUrl.isNullOrBlank() || !apiUrl.startsWith("https://")) {
            return call.reject("token, user and an https apiUrl are needed")
        }
        val store = Store(context)
        val earlier = store.user
        if (earlier != null && earlier != user) { // another login: nothing of the earlier one stays
            SmsQueue(context).clear()
            store.wipe()
        }
        store.saveToken(token, apiUrl, user)
        SmsQueue(context).log("connected", if (store.cursorMs != null) "cursor kept" else "new")
        if (store.cursorMs != null) {
            store.quietScan = true // a reconnect: what came meanwhile is sent, not announced
            Work.catchUp(context)
            Work.upload(context, "reconnect")
        }
        call.resolve(statusObject())
    }

    /** keep (sign-out, D-143): the token goes, the cursor, queue and login stay for the same
     *  login. Without keep (another login, a reset): everything goes and uploads stop. */
    @PluginMethod
    fun disconnect(call: PluginCall) {
        val store = Store(context)
        if (call.getBoolean("keep") == true) {
            store.signOut()
            SmsQueue(context).log("signed_out", "cursor kept")
        } else {
            Work.cancel(context)
            SmsQueue(context).clear()
            store.wipe()
        }
        call.resolve(statusObject())
    }

    /** Read the inbox from [sinceMs] (a first run, or "Scan history again"), then keep up. The
     *  messages read now are old: none of them notifies. */
    @PluginMethod
    fun startHistory(call: PluginCall) {
        val since = call.getLong("sinceMs") ?: return call.reject("sinceMs is needed")
        val store = Store(context)
        val cursor = store.cursorMs
        store.cursorMs = if (cursor == null) since else minOf(cursor, since)
        store.historyFromMs = minOf(store.historyFromMs ?: since, since)
        store.quietScan = true
        SmsQueue(context).log("history", "from ${Instant.ofEpochMilli(since)}")
        Work.catchUp(context)
        Work.upload(context, "history")
        call.resolve(statusObject())
    }

    /** Sync now: an incremental scan from the cursor and an upload, at once (never history). */
    @PluginMethod
    fun syncNow(call: PluginCall) {
        SmsQueue(context).log("sync_now")
        Work.upload(context, "sync_now")
        call.resolve(statusObject())
    }

    /** 5F (D-146): an export the app downloaded, written to the cache and offered through the
     *  share sheet (a FileProvider content URI, read permission only). Older exports go. */
    @PluginMethod
    fun shareFile(call: PluginCall) {
        val name = call.getString("name")?.takeIf { Regex("[A-Za-z0-9._-]{1,80}").matches(it) }
            ?: return call.reject("a plain file name is needed")
        val mime = call.getString("mime") ?: "application/octet-stream"
        val data = call.getString("base64") ?: return call.reject("base64 is needed")
        try {
            val folder = java.io.File(context.cacheDir, "exports").apply { mkdirs() }
            folder.listFiles()?.forEach { it.delete() } // only the newest export stays
            val file = java.io.File(folder, name)
            file.writeBytes(android.util.Base64.decode(data, android.util.Base64.DEFAULT))
            val uri = androidx.core.content.FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
            val send = Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            activity.startActivity(Intent.createChooser(send, name).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
            call.resolve(JSObject().put("shared", true))
        } catch (e: Exception) {
            call.reject("could not share the file (${e.javaClass.simpleName})")
        }
    }

    /** "Copy diagnostics": the status and the last 100 events. Codes and counts only. */
    @PluginMethod
    fun diagnostics(call: PluginCall) {
        val s = statusObject()
        val lines = mutableListOf("Flash diagnostics ${Instant.now()}", "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}), ${Build.MANUFACTURER} ${Build.MODEL}")
        for (key in s.keys()) if (key != "events" && key != "deviceId") lines += "$key: ${s.opt(key)}"
        lines += "events (newest first):"
        for (e in SmsQueue(context).events()) lines += "${Instant.ofEpochMilli(e.atMs)} ${e.type} ${e.detail}".trim()
        call.resolve(JSObject().put("text", lines.joinToString("\n")))
    }

    private fun statusObject(): JSObject {
        val store = Store(context)
        val queue = SmsQueue(context)
        val (queued, awaiting) = queue.counts()
        val power = context.getSystemService(PowerManager::class.java)
        val events = JSArray()
        for (e in queue.events().take(20)) events.put(JSObject().put("at", e.atMs).put("type", e.type).put("detail", e.detail))
        return JSObject().apply {
            put("available", true)
            put("deviceId", store.deviceId)
            put("deviceName", "${Build.MANUFACTURER} ${Build.MODEL}".trim().take(60))
            put("permission", state("sms"))
            put("notifications", if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) (if (Notify.allowed(context)) "granted" else "denied") else state("notifications"))
            put("connected", store.connected)
            store.user?.let { put("user", it) }
            put("revoked", store.revoked)
            put("signedOut", store.signedOut)
            put("queued", queued)
            put("awaiting", awaiting)
            put("dropped", store.dropped)
            store.lastUpload()?.let { (at, stored) -> put("lastUpload", JSObject().put("at", at).put("stored", stored)) }
            store.lastAttempt()?.let { (at, result) -> put("lastAttempt", JSObject().put("at", at).put("result", result)) }
            put("lastError", store.lastError)
            store.cursorMs?.let { put("cursorMs", it) }
            store.historyFromMs?.let { put("historyFromMs", it) }
            store.lastSmsSeenMs?.let { put("lastSmsSeenMs", it) }
            put("batteryUnrestricted", power?.isIgnoringBatteryOptimizations(context.packageName) == true)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                context.getSystemService(UsageStatsManager::class.java)?.let { put("standbyBucket", it.appStandbyBucket) }
            }
            put("manufacturer", Build.MANUFACTURER.lowercase())
            put("events", events)
        }
    }

    private fun state(alias: String): String = when (getPermissionState(alias)) {
        PermissionState.GRANTED -> "granted"
        PermissionState.DENIED -> "denied"
        else -> "prompt"
    }
}
