package app.flashexpense.android

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.util.UUID
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * The phone's own state (private preferences, never backed up): this install's device id, the
 * API address, the device token sealed with a Keystore key, the inbox cursor and the status the
 * app shows. Codes and counts only; never a message.
 */
class Store(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("flash", Context.MODE_PRIVATE)

    /** One id per install, kept across sign-outs, so connecting again replaces the old token. */
    val deviceId: String
        get() = prefs.getString(DEVICE_ID, null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString(DEVICE_ID, it).apply()
        }

    var apiUrl: String?
        get() = prefs.getString(API_URL, null)
        set(value) = prefs.edit().putString(API_URL, value).apply()

    /** A token that still opens (the Keystore key can be lost on a reset) and an API address. */
    val connected: Boolean get() = apiUrl != null && token() != null

    /** The login that connected this phone: another login on this phone disconnects it first. */
    val user: String? get() = prefs.getString(USER, null)

    var revoked: Boolean
        get() = prefs.getBoolean(REVOKED, false)
        set(value) = prefs.edit().putBoolean(REVOKED, value).apply()

    /** The inbox date (ms) of the newest row queued; null: no scan chosen yet. */
    var cursorMs: Long?
        get() = if (prefs.contains(CURSOR)) prefs.getLong(CURSOR, 0) else null
        set(value) = prefs.edit().apply { if (value == null) remove(CURSOR) else putLong(CURSOR, value) }.apply()

    var historyFromMs: Long?
        get() = if (prefs.contains(HISTORY)) prefs.getLong(HISTORY, 0) else null
        set(value) = prefs.edit().apply { if (value == null) remove(HISTORY) else putLong(HISTORY, value) }.apply()

    /** 5B-2 (D-142): the highest inbox _id queued. A new inbox row always gets a higher _id, so
     *  a row stored late with an older date is still found; null until the first scan. */
    var lastId: Long?
        get() = if (prefs.contains(LAST_ID)) prefs.getLong(LAST_ID, 0) else null
        set(value) = prefs.edit().apply { if (value == null) remove(LAST_ID) else putLong(LAST_ID, value) }.apply()

    /** A history scan or a reconnect is reading old messages: none of them notifies. */
    var quietScan: Boolean
        get() = prefs.getBoolean(QUIET, false)
        set(value) = prefs.edit().putBoolean(QUIET, value).apply()

    /** When the newest bank SMS was seen on this phone (live, or in a scan). */
    var lastSmsSeenMs: Long?
        get() = if (prefs.contains(SMS_SEEN)) prefs.getLong(SMS_SEEN, 0) else null
        set(value) = prefs.edit().apply { if (value == null) remove(SMS_SEEN) else putLong(SMS_SEEN, value) }.apply()

    /** Signed out with the cursor kept (5B-2): the same login signs in and carries on. */
    val signedOut: Boolean get() = prefs.getBoolean(SIGNED_OUT, false)

    fun token(): String? = prefs.getString(TOKEN, null)?.let {
        try {
            String(Gcm.open(key(), Base64.decode(it, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (e: Exception) {
            null // the key is gone (a restore, a reset): connect again
        }
    }

    fun saveToken(token: String, url: String, user: String) {
        val sealed = Base64.encodeToString(Gcm.seal(key(), token.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
        prefs.edit().putString(TOKEN, sealed).putString(API_URL, url).putString(USER, user)
            .putBoolean(REVOKED, false).putBoolean(SIGNED_OUT, false).apply()
    }

    /** Sign-out (5B-2, D-143): the token goes, the login, the cursor and the queue stay, so the
     *  same login signing in again reconnects without a new scan. Another login wipes all. */
    fun signOut() {
        prefs.edit().remove(TOKEN).putBoolean(SIGNED_OUT, true).putBoolean(REVOKED, false).apply()
    }

    /** Another login (or a full reset): everything but the device id. The Keystore key goes too. */
    fun wipe() {
        val id = deviceId
        prefs.edit().clear().putString(DEVICE_ID, id).apply()
        try {
            KeyStore.getInstance(KEYSTORE).apply { load(null) }.deleteEntry(KEY_ALIAS)
        } catch (e: Exception) {
            // nothing to delete
        }
    }

    // --- status for the app (D-124): times in ms, results as short codes --------------------

    fun noteAttempt(result: String, nowMs: Long) {
        prefs.edit().putLong(ATTEMPT_AT, nowMs).putString(ATTEMPT_RESULT, result)
            .putString(LAST_ERROR, if (result == Wire.Outcome.STORED.code) "" else result).apply()
    }

    fun noteUpload(stored: Int, nowMs: Long) {
        prefs.edit().putLong(UPLOAD_AT, nowMs).putInt(UPLOAD_STORED, stored).apply()
    }

    fun noteDropped(n: Int) {
        if (n > 0) prefs.edit().putInt(DROPPED, prefs.getInt(DROPPED, 0) + n).apply()
    }

    fun lastAttempt(): Pair<Long, String>? =
        if (prefs.contains(ATTEMPT_AT)) prefs.getLong(ATTEMPT_AT, 0) to (prefs.getString(ATTEMPT_RESULT, "") ?: "") else null

    fun lastUpload(): Pair<Long, Int>? =
        if (prefs.contains(UPLOAD_AT)) prefs.getLong(UPLOAD_AT, 0) to prefs.getInt(UPLOAD_STORED, 0) else null

    val lastError: String get() = prefs.getString(LAST_ERROR, "") ?: ""
    val dropped: Int get() = prefs.getInt(DROPPED, 0)

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "flash-device-token"
        const val DEVICE_ID = "device_id"
        const val API_URL = "api_url"
        const val TOKEN = "token_sealed"
        const val USER = "user"
        const val REVOKED = "revoked"
        const val CURSOR = "cursor_ms"
        const val HISTORY = "history_from_ms"
        const val ATTEMPT_AT = "attempt_at"
        const val ATTEMPT_RESULT = "attempt_result"
        const val LAST_ERROR = "last_error"
        const val UPLOAD_AT = "upload_at"
        const val UPLOAD_STORED = "upload_stored"
        const val DROPPED = "dropped_not_in_inbox"
        const val LAST_ID = "last_inbox_id"
        const val QUIET = "quiet_scan"
        const val SMS_SEEN = "last_sms_seen_ms"
        const val SIGNED_OUT = "signed_out"
    }
}
