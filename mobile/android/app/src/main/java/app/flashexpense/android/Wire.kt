package app.flashexpense.android

import java.time.Instant
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** One bank SMS as the inbox holds it: the row's _id, address, body and date (ms, UTC). */
data class InboxRow(val msgId: String, val sender: String, val body: String, val receivedMs: Long)

/**
 * The pure parts of the phone's upload (D-124), testable on the JVM: the request body, what an
 * answer means, how the inbox is paged, and the token's AES-GCM sealing. No Android classes.
 */
object Wire {
    const val BATCH = 500 // the server's limit per upload
    const val OVERLAP_MS = 10 * 60_000L // each run rescans the last 10 minutes before the cursor
    const val AWAIT_MS = 24 * 60 * 60_000L // a live SMS not in the inbox after this is dropped
    const val MATCH_MS = 10 * 60_000L // a live SMS and its inbox row: within 10 minutes

    /** JSON string literal: quotes, backslashes and control characters escaped. */
    fun quote(text: String): String = buildString(text.length + 2) {
        append('"')
        for (c in text) {
            when {
                c == '"' -> append("\\\"")
                c == '\\' -> append("\\\\")
                c == '\n' -> append("\\n")
                c == '\r' -> append("\\r")
                c == '\t' -> append("\\t")
                c < ' ' || c == ' ' || c == ' ' -> append("\\u%04x".format(c.code))
                else -> append(c)
            }
        }
        append('"')
    }

    /** The inbox row's date as the server's received_at_utc: UTC ISO with milliseconds. */
    fun isoUtc(ms: Long): String = Instant.ofEpochMilli(ms).toString()

    /** POST /api/v1/ingest/sms body. */
    fun batchJson(rows: List<InboxRow>): String = rows.joinToString(",", "{\"messages\":[", "]}") {
        "{\"sender\":${quote(it.sender)},\"body\":${quote(it.body)}," +
            "\"received_at_utc\":${quote(isoUtc(it.receivedMs))},\"device_msg_id\":${quote(it.msgId)}}"
    }

    /** Where a run starts reading the inbox: a little before the cursor, never before 0. */
    fun scanFrom(cursorMs: Long): Long = maxOf(0L, cursorMs - OVERLAP_MS)

    /**
     * One page of inbox rows (oldest first): up to [limit] rows, extended so that rows with the
     * same date are never split between two pages (the next page reads "date > last date").
     */
    fun page(rows: Sequence<InboxRow>, limit: Int = BATCH): List<InboxRow> {
        val out = ArrayList<InboxRow>()
        for (row in rows) {
            if (out.size >= limit && row.receivedMs != out.last().receivedMs) break
            out.add(row)
        }
        return out
    }

    fun expired(hintMs: Long, nowMs: Long): Boolean = nowMs - hintMs > AWAIT_MS

    /** The answer to an upload, as the queue acts on it. */
    enum class Outcome(val code: String) {
        STORED("ok"), // every row sent has its final answer: clear them
        REVOKED("revoked"), // the device was revoked on the server: stop
        SIGNED_OUT("unauthorised"), // the token is unknown: stop until the owner connects again
        OFFLINE("offline"), // no answer at all: retry later
        SERVER("server_error"), // 5xx, 408, 429: retry with backoff
        REJECTED("rejected"), // another 4xx: keep the rows, retry with backoff
    }

    fun outcome(status: Int, detail: String?): Outcome = when {
        status == 200 -> Outcome.STORED
        status == 401 && detail == "device_revoked" -> Outcome.REVOKED
        status == 401 || status == 403 -> Outcome.SIGNED_OUT
        status <= 0 -> Outcome.OFFLINE
        status >= 500 || status == 408 || status == 429 -> Outcome.SERVER
        else -> Outcome.REJECTED
    }

    /** The server's {"detail": "..."} when it is a plain string, else null. */
    fun detail(json: String?): String? =
        json?.let { Regex("\"detail\"\\s*:\\s*\"([^\"\\\\]*)\"").find(it)?.groupValues?.get(1) }

    /** How many of an answer's messages were new: counts.stored. */
    fun storedCount(json: String?): Int =
        json?.let { Regex("\"stored\"\\s*:\\s*(\\d+)").find(it)?.groupValues?.get(1)?.toInt() } ?: 0
}

/** AES-256-GCM, 12-byte IV first. The key lives in the Android Keystore on the phone. */
object Gcm {
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val IV_BYTES = 12

    fun seal(key: SecretKey, plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key) // the provider picks a fresh random IV
        val iv = cipher.iv
        require(iv.size == IV_BYTES) { "unexpected IV size" }
        return iv + cipher.doFinal(plain)
    }

    fun open(key: SecretKey, sealed: ByteArray): ByteArray {
        require(sealed.size > IV_BYTES) { "too short" }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed, 0, IV_BYTES))
        return cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
    }
}
