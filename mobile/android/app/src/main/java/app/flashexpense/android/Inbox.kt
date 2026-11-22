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

    /** A page of bank rows, oldest first (Wire.page): with a date after [afterMs], or (5B-2,
     *  D-142) an _id above [afterId], so a row the SMS app stored late, with an older date, is
     *  still read. [afterId] null: the first scan, by date only. Returns the rows and their
     *  highest _id. */
    fun page(afterMs: Long, afterId: Long?): Pair<List<InboxRow>, Long?> {
        val projection = arrayOf(Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE)
        val (where, args) = if (afterId == null) {
            "${Telephony.Sms.DATE} > ? AND $likeClause" to arrayOf(afterMs.toString(), *likeArgs.toTypedArray())
        } else {
            "(${Telephony.Sms.DATE} > ? OR ${Telephony.Sms._ID} > ?) AND $likeClause" to
                arrayOf(afterMs.toString(), afterId.toString(), *likeArgs.toTypedArray())
        }
        val cursor = context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            where,
            args,
            "${Telephony.Sms.DATE} ASC, ${Telephony.Sms._ID} ASC",
        ) ?: return emptyList<InboxRow>() to null
        var maxId: Long? = null
        val rows = cursor.use { c ->
            val all = generateSequence {
                if (c.moveToNext()) {
                    val id = c.getLong(0)
                    maxId = maxOf(maxId ?: id, id)
                    InboxRow(id.toString(), c.getString(1) ?: "", c.getString(2) ?: "", c.getLong(3))
                } else {
                    null
                }
            }.filter { senders.accepts(it.sender, it.body) && Wire.sendable(it.sender, it.body) }
            Wire.page(all)
        }
        return rows to maxId // every row read counts: a non-bank row needs no second look
    }

    /** Is a live message in the inbox: the same sender core and body (after Wire.normalBody,
     *  5B-2), date within 10 minutes? The SMS app may store the address or the line breaks a
     *  little differently from the broadcast. */
    fun holds(sender: String, body: String, aroundMs: Long): Boolean {
        val core = SenderRules.parseSender(sender).first
        val cursor = context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY),
            "${Telephony.Sms.ADDRESS} LIKE ? AND ${Telephony.Sms.DATE} BETWEEN ? AND ?",
            arrayOf("%$core%", (aroundMs - Wire.MATCH_MS).toString(), (aroundMs + Wire.MATCH_MS).toString()),
            null,
        ) ?: return false
        val want = Wire.normalBody(body)
        return cursor.use { c ->
            generateSequence { if (c.moveToNext()) (c.getString(0) ?: "") to (c.getString(1) ?: "") else null }
                .any { (address, text) -> SenderRules.parseSender(address).first == core && Wire.normalBody(text) == want }
        }
    }
}
