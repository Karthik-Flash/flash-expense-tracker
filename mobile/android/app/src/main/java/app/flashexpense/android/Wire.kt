package app.flashexpense.android

import java.time.Instant
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * One bank SMS as the queue holds it: the inbox row's _id (or "live-<n>" for a live copy),
 * address, body and date (ms, UTC). [origin]: "inbox" or "live" (5B-2, D-139); [notify]: a new
 * payment from it may be announced (live, or an inbox row read soon after it came, D-142).
 */
data class InboxRow(
    val msgId: String,
    val sender: String,
    val body: String,
    val receivedMs: Long,
    val origin: String = "inbox",
    val notify: Boolean = false,
)

/** A payment the server made from an upload (the answer's new_transactions, D-141). */
data class NewPayment(
    val deviceMsgId: String,
    val id: Long,
    val direction: String,
    val amountPaise: Long,
    val name: String?,
    val categoryName: String?,
    val role: String?,
    val paidBackQuestion: Boolean,
)

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

    /** POST /api/v1/ingest/sms body ("origin" is additive: the server reads "inbox" without it). */
    fun batchJson(rows: List<InboxRow>): String = rows.joinToString(",", "{\"messages\":[", "]}") {
        "{\"sender\":${quote(it.sender)},\"body\":${quote(it.body)}," +
            "\"received_at_utc\":${quote(isoUtc(it.receivedMs))},\"device_msg_id\":${quote(it.msgId)}," +
            "\"origin\":${quote(it.origin)}}"
    }

    const val MAX_BODY_BYTES = 2048 // the server's limits (app/api/devices.py Sms)
    const val MAX_SENDER = 64
    const val GRACE_MS = 2 * 60_000L // a live SMS whose inbox row has not come by then is sent itself
    const val NOTIFY_MS = 2 * 60 * 60_000L // an inbox row older than this at queueing never notifies

    /** What the server would refuse as malformed (a 422 for the whole batch): never queued. */
    fun sendable(sender: String, body: String): Boolean =
        sender.isNotEmpty() && sender.length <= MAX_SENDER && body.isNotEmpty() &&
            body.toByteArray(Charsets.UTF_8).size <= MAX_BODY_BYTES

    /**
     * Whitespace as Python's str.isspace() knows it: the server's app/pipeline/dedupe.py lists
     * the same characters, and both pass backend/tests/fixtures/body_normalise.json.
     */
    private const val WHITESPACE =
        " \t\n\r\u000b\u000c\u001c\u001d\u001e\u001f\u0085       " +
            "          　"
    /** The body for comparing two copies of one SMS: NFC, whitespace runs one space, trimmed. */
    fun normalBody(body: String): String {
        val text = java.text.Normalizer.normalize(body, java.text.Normalizer.Form.NFC)
        val out = StringBuilder(text.length)
        var inRun = false
        for (c in text) {
            if (c in WHITESPACE) {
                if (!inRun) out.append(' ')
                inRun = true
            } else {
                out.append(c)
                inRun = false
            }
        }
        return out.toString().trim(' ')
    }

    /** May a payment from this queue row be announced? Live, or a recent inbox row (D-142). */
    fun mayNotify(row: InboxRow, nowMs: Long): Boolean =
        row.notify && (row.origin == "live" || nowMs - row.receivedMs <= NOTIFY_MS)

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

    /** The answer to an upload, as the queue acts on it (5B-2: what is kept, retried, dropped). */
    enum class Outcome(val code: String) {
        STORED("ok"), // every row sent has its final answer (stored, duplicate, refused): clear them
        REVOKED("revoked"), // the device was revoked on the server: keep the queue, "disconnected"
        SIGNED_OUT("unauthorised"), // the token is unknown: keep the queue, "disconnected"
        OFFLINE("offline"), // no answer at all (no network, a timeout): retry with backoff
        SERVER("server_error"), // 5xx, 408, 429: retry with backoff
        INVALID("invalid"), // 413 or 422: one row is malformed; send one by one, drop that one
        REJECTED("rejected"), // another 4xx: keep the rows, retry with backoff
    }

    fun outcome(status: Int, detail: String?): Outcome = when {
        status == 200 -> Outcome.STORED
        status == 401 && detail == "device_revoked" -> Outcome.REVOKED
        status == 401 || status == 403 -> Outcome.SIGNED_OUT
        status <= 0 -> Outcome.OFFLINE
        status >= 500 || status == 408 || status == 429 -> Outcome.SERVER
        status == 413 || status == 422 -> Outcome.INVALID
        else -> Outcome.REJECTED
    }

    /** What the run does with a batch after an answer. */
    enum class Next { CLEAR, SPLIT, DROP_ONE, STOP, RETRY }

    /** A row leaves the queue only with a final answer, or when the server refused it on its own. */
    fun next(outcome: Outcome, batchSize: Int): Next = when (outcome) {
        Outcome.STORED -> Next.CLEAR
        Outcome.INVALID -> if (batchSize > 1) Next.SPLIT else Next.DROP_ONE
        Outcome.REVOKED, Outcome.SIGNED_OUT -> Next.STOP
        else -> Next.RETRY
    }

    /** The answer's new_transactions (D-141); an older server has none. */
    fun newPayments(json: String?): List<NewPayment> {
        val root = json?.let { runCatching { MiniJson.parse(it) }.getOrNull() } as? Map<*, *> ?: return emptyList()
        val items = root["new_transactions"] as? List<*> ?: return emptyList()
        return items.mapNotNull { item ->
            val m = item as? Map<*, *> ?: return@mapNotNull null
            NewPayment(
                deviceMsgId = m["device_msg_id"] as? String ?: return@mapNotNull null,
                id = (m["id"] as? Number)?.toLong() ?: return@mapNotNull null,
                direction = m["direction"] as? String ?: return@mapNotNull null,
                amountPaise = (m["amount_paise"] as? Number)?.toLong() ?: return@mapNotNull null,
                name = m["display_name"] as? String,
                categoryName = m["category_name"] as? String,
                role = m["role"] as? String,
                paidBackQuestion = m["paid_back_question"] == true,
            )
        }
    }

    /** "₹1,23,456" or "₹1,234.50": Indian grouping, paise only when not zero. */
    fun rupees(paise: Long): String {
        val whole = paise / 100
        val rest = (paise % 100).toInt()
        val digits = whole.toString()
        val grouped = if (digits.length <= 3) digits else {
            val head = digits.dropLast(3)
            head.reversed().chunked(2).joinToString(",").reversed() + "," + digits.takeLast(3)
        }
        return "₹" + grouped + if (rest == 0) "" else ".%02d".format(rest)
    }

    /** The notification's text (D-142). */
    fun notificationText(p: NewPayment): String {
        val name = p.name?.takeIf { it.isNotBlank() }
        return if (p.direction == "debit") {
            "Paid ${rupees(p.amountPaise)}" + (name?.let { " to $it" } ?: "") +
                (p.categoryName?.let { " · $it" } ?: "")
        } else {
            "Received ${rupees(p.amountPaise)}" + (name?.let { " from $it" } ?: "") +
                if (p.paidBackQuestion) " · Paid back?" else ""
        }
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

/**
 * A small JSON reader for the ingest answer (objects, arrays, strings, numbers, true, false,
 * null): Android's org.json is not there in JVM unit tests, and no package is added for this.
 */
object MiniJson {
    fun parse(text: String): Any? = Reader(text).run { value().also { space(); require(at == s.length) { "trailing text" } } }

    private class Reader(val s: String) {
        var at = 0

        fun space() {
            while (at < s.length && s[at] in " \t\r\n") at++
        }

        fun value(): Any? {
            space()
            require(at < s.length) { "end of text" }
            return when (val c = s[at]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> word("true", true)
                'f' -> word("false", false)
                'n' -> word("null", null)
                else -> if (c == '-' || c.isDigit()) num() else error("unexpected character")
            }
        }

        private fun word(w: String, v: Any?): Any? {
            require(s.startsWith(w, at)) { "bad word" }
            at += w.length
            return v
        }

        private fun num(): Number {
            val start = at
            while (at < s.length && (s[at].isDigit() || s[at] in "+-.eE")) at++
            val t = s.substring(start, at)
            return if (t.any { it in ".eE" }) t.toDouble() else t.toLong()
        }

        private fun str(): String {
            at++ // the opening quote
            val out = StringBuilder()
            while (true) {
                require(at < s.length) { "open string" }
                val c = s[at++]
                when (c) {
                    '"' -> return out.toString()
                    '\\' -> {
                        val e = s[at++]
                        when (e) {
                            'n' -> out.append('\n')
                            't' -> out.append('\t')
                            'r' -> out.append('\r')
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000c')
                            'u' -> {
                                out.append(s.substring(at, at + 4).toInt(16).toChar())
                                at += 4
                            }
                            else -> out.append(e) // \" \\ \/
                        }
                    }
                    else -> out.append(c)
                }
            }
        }

        private fun arr(): List<Any?> {
            at++
            val out = ArrayList<Any?>()
            space()
            if (s[at] == ']') return out.also { at++ }
            while (true) {
                out.add(value())
                space()
                when (s[at++]) {
                    ',' -> continue
                    ']' -> return out
                    else -> error("bad array")
                }
            }
        }

        private fun obj(): Map<String, Any?> {
            at++
            val out = LinkedHashMap<String, Any?>()
            space()
            if (s[at] == '}') return out.also { at++ }
            while (true) {
                space()
                val key = str()
                space()
                require(s[at++] == ':') { "bad object" }
                out[key] = value()
                space()
                when (s[at++]) {
                    ',' -> continue
                    '}' -> return out
                    else -> error("bad object")
                }
            }
        }
    }
}