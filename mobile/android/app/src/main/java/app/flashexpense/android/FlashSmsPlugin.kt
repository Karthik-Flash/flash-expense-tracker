package app.flashexpense.android

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback

/**
 * The web app's door to bank SMS on this phone (frontend/src/native/sms.ts). The device token
 * passes through once (connect) and is sealed at once; nothing here returns it or a message.
 */
@CapacitorPlugin(
    name = "FlashSms",
    permissions = [Permission(alias = "sms", strings = [Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS])],
)
class FlashSmsPlugin : Plugin() {
    override fun load() {
        Events.listener = { stored -> notifyListeners("uploaded", JSObject().put("stored", stored)) }
        val store = Store(context)
        if (store.connected && !store.revoked) {
            Work.catchUp(context)
            Work.upload(context)
        }
    }

    override fun handleOnDestroy() {
        Events.listener = null
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
        if (getPermissionState("sms") == PermissionState.GRANTED && Store(context).connected) Work.upload(context, now = true)
        call.resolve(statusObject().put("asked", true))
    }

    /** App info: Permissions, Battery, and ⋮ > Allow restricted settings live there. */
    @PluginMethod
    fun openAppInfo(call: PluginCall) {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
        activity.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        call.resolve()
    }

    /** The token from POST /api/v1/devices, and the API address. Sealed, then forgotten here. */
    @PluginMethod
    fun connect(call: PluginCall) {
        val token = call.getString("token")
        val apiUrl = call.getString("apiUrl")?.trimEnd('/')
        val user = call.getString("user")
        if (token.isNullOrBlank() || user.isNullOrBlank() || apiUrl.isNullOrBlank() || !apiUrl.startsWith("https://")) {
            return call.reject("token, user and an https apiUrl are needed")
        }
        Store(context).saveToken(token, apiUrl, user)
        Work.catchUp(context)
        call.resolve(statusObject())
    }

    /** Sign-out: no token, no queue, no cursor, no status; uploads stop. */
    @PluginMethod
    fun disconnect(call: PluginCall) {
        Work.cancel(context)
        SmsQueue(context).clear()
        Store(context).wipe()
        call.resolve(statusObject())
    }

    /** Read the inbox from [sinceMs] (a first run, or a longer period), then keep up. */
    @PluginMethod
    fun startHistory(call: PluginCall) {
        val since = call.getLong("sinceMs") ?: return call.reject("sinceMs is needed")
        val store = Store(context)
        val cursor = store.cursorMs
        store.cursorMs = if (cursor == null) since else minOf(cursor, since)
        store.historyFromMs = minOf(store.historyFromMs ?: since, since)
        Work.upload(context, now = true)
        call.resolve(statusObject())
    }

    @PluginMethod
    fun syncNow(call: PluginCall) {
        Work.upload(context, now = true)
        call.resolve(statusObject())
    }

    private fun statusObject(): JSObject {
        val store = Store(context)
        val (queued, awaiting) = SmsQueue(context).counts()
        val permission = when (getPermissionState("sms")) {
            PermissionState.GRANTED -> "granted"
            PermissionState.DENIED -> "denied"
            else -> "prompt"
        }
        val power = context.getSystemService(PowerManager::class.java)
        return JSObject().apply {
            put("available", true)
            put("deviceId", store.deviceId)
            put("deviceName", "${Build.MANUFACTURER} ${Build.MODEL}".trim().take(60))
            put("permission", permission)
            put("connected", store.connected)
            store.user?.let { put("user", it) }
            put("revoked", store.revoked)
            put("queued", queued)
            put("awaiting", awaiting)
            put("dropped", store.dropped)
            store.lastUpload()?.let { (at, stored) -> put("lastUpload", JSObject().put("at", at).put("stored", stored)) }
            store.lastAttempt()?.let { (at, result) -> put("lastAttempt", JSObject().put("at", at).put("result", result)) }
            put("lastError", store.lastError)
            store.cursorMs?.let { put("cursorMs", it) }
            store.historyFromMs?.let { put("historyFromMs", it) }
            put("batteryUnrestricted", power?.isIgnoringBatteryOptimizations(context.packageName) == true)
            put("manufacturer", Build.MANUFACTURER.lowercase())
        }
    }
}
