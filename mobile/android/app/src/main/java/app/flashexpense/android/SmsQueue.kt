package app.flashexpense.android

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * The on-device queue (D-124), bank messages only:
 * - `ready`: inbox rows to upload, one per inbox _id, with the inbox's exact date;
 * - `awaiting`: live messages from the SMS_RECEIVED broadcast whose inbox row was not seen yet.
 * A row leaves `ready` only when the server has answered for it.
 */
class SmsQueue(context: Context) : SQLiteOpenHelper(context, "flash_queue.db", null, 1) {
    data class Awaiting(val id: Long, val sender: String, val body: String, val hintMs: Long)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE ready (msg_id TEXT PRIMARY KEY, sender TEXT NOT NULL, body TEXT NOT NULL, " +
                "received_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE TABLE awaiting (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, " +
                "body TEXT NOT NULL, hint_ms INTEGER NOT NULL)",
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    /** Adds inbox rows; one already queued is left as it is. All or nothing. */
    fun addReady(rows: List<InboxRow>) {
        if (rows.isEmpty()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (r in rows) {
                val values = ContentValues().apply {
                    put("msg_id", r.msgId)
                    put("sender", r.sender)
                    put("body", r.body)
                    put("received_ms", r.receivedMs)
                }
                db.insertWithOnConflict("ready", null, values, SQLiteDatabase.CONFLICT_IGNORE)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun addAwaiting(sender: String, body: String, hintMs: Long) {
        val values = ContentValues().apply {
            put("sender", sender)
            put("body", body)
            put("hint_ms", hintMs)
        }
        writableDatabase.insert("awaiting", null, values)
    }

    fun awaiting(): List<Awaiting> =
        readableDatabase.rawQuery("SELECT id, sender, body, hint_ms FROM awaiting ORDER BY id", null).use { c ->
            generateSequence { if (c.moveToNext()) Awaiting(c.getLong(0), c.getString(1), c.getString(2), c.getLong(3)) else null }
                .toList()
        }

    fun dropAwaiting(ids: List<Long>) {
        if (ids.isEmpty()) return
        writableDatabase.delete("awaiting", "id IN (${ids.joinToString(",")})", null)
    }

    /** The oldest ready rows, at most [limit]. */
    fun nextBatch(limit: Int = Wire.BATCH): List<InboxRow> =
        readableDatabase.rawQuery(
            "SELECT msg_id, sender, body, received_ms FROM ready ORDER BY received_ms, msg_id LIMIT $limit",
            null,
        ).use { c ->
            generateSequence { if (c.moveToNext()) InboxRow(c.getString(0), c.getString(1), c.getString(2), c.getLong(3)) else null }
                .toList()
        }

    /** Rows the server answered for. */
    fun remove(rows: List<InboxRow>) {
        if (rows.isEmpty()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (r in rows) db.delete("ready", "msg_id = ?", arrayOf(r.msgId))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun counts(): Pair<Int, Int> = readableDatabase.rawQuery(
        "SELECT (SELECT COUNT(*) FROM ready), (SELECT COUNT(*) FROM awaiting)",
        null,
    ).use { c -> if (c.moveToFirst()) c.getInt(0) to c.getInt(1) else 0 to 0 }

    /** Sign-out: nothing of the owner's stays on the phone. */
    fun clear() {
        writableDatabase.execSQL("DELETE FROM ready")
        writableDatabase.execSQL("DELETE FROM awaiting")
    }
}
