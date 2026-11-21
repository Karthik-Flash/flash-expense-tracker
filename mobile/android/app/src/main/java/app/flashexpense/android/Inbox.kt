package app.flashexpense.android

import android.content.Context
import android.provider.Telephony

/**
 * The SMS inbox (Telephony provider), bank senders only. The query itself asks only for
 * addresses holding a bank sender core, so other SMS never reach the app; each row is checked
 * again with the exact rules (BankSenders.accepts) before it is used.
 */
class Inbox(private val context: Context, private val senders: BankSenders) {
    private val likeClause = senders.cores.joinToString(" OR ", "(", ")") { "${Telephony.Sms.ADDRESS} LIKE ?" }
    private val likeArgs = senders.cores.map { "%$it%" }

    /** Bank rows with date > [afterMs], oldest first: one page (Wire.page). */
    fun page(afterMs: Long): List<InboxRow> {
        val projection = arrayOf(Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE)
        val cursor = context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            "${Telephony.Sms.DATE} > ? AND $likeClause",
            arrayOf(afterMs.toString(), *likeArgs.toTypedArray()),
            "${Telephony.Sms.DATE} ASC, ${Telephony.Sms._ID} ASC",
        ) ?: return emptyList()
        return cursor.use { c ->
            val rows = generateSequence {
                if (c.moveToNext()) InboxRow(c.getLong(0).toString(), c.getString(1) ?: "", c.getString(2) ?: "", c.getLong(3)) else null
            }.filter { senders.accepts(it.sender, it.body) }
            Wire.page(rows)
        }
    }

    /** Is a live message in the inbox: same sender and body, date within 10 minutes? */
    fun holds(sender: String, body: String, aroundMs: Long): Boolean {
        val cursor = context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.BODY),
            "${Telephony.Sms.ADDRESS} = ? AND ${Telephony.Sms.DATE} BETWEEN ? AND ?",
            arrayOf(sender, (aroundMs - Wire.MATCH_MS).toString(), (aroundMs + Wire.MATCH_MS).toString()),
            null,
        ) ?: return false
        val want = body.split(Regex("\\s+")).joinToString(" ").trim()
        return cursor.use { c ->
            generateSequence { if (c.moveToNext()) c.getString(0) ?: "" else null }
                .any { it.split(Regex("\\s+")).joinToString(" ").trim() == want }
        }
    }
}
