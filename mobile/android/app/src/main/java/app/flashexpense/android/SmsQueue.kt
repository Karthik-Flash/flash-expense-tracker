package app.flashexpense.android

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * The on-device queue (D-124; 5B-2, D-142), bank messages only:
 * - `ready`: messages to upload, one per inbox _id (or "live-<n>" for a live copy), with the
 *   inbox's exact date, how it came (origin) and whether a new payment from it may notify;
 * - `awaiting`: live messages from the SMS_RECEIVED broadcast whose inbox row was not seen yet;
 * - `seen`: rows already uploaded, for 3 days, so a rescan of the overlap never sends them again;
 * - `events`: the last 100 events for the status screen (codes and counts, never a message).
 * A row leaves `ready` only when the server has answered for it, or refused it on its own.
 */
class SmsQueue(context: Context) : SQLiteOpenHelper(context, "flash_queue.db", null, 2) {
    data class Awaiting(val id: Long, val sender: String, val body: String, val hintMs: Long)
    data class Event(val atMs: Long, val type: String, val detail: String)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE ready (msg_id TEXT PRIMARY KEY, sender TEXT NOT NULL, body TEXT NOT NULL, " +
                "received_ms INTEGER NOT NULL, origin TEXT NOT NULL DEFAULT 'inbox', notify INTEGER NOT NULL DEFAULT 0)",
        )
        db.execSQL(
            "CREATE TABLE awaiting (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, " +
                "body TEXT NOT NULL, hint_ms INTEGER NOT NULL)",
        )
        createV2(db)
    }

    private fun createV2(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS seen (msg_id TEXT PRIMARY KEY, received_ms INTEGER NOT NULL)")
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at_ms INTEGER NOT NULL, " +
                "type TEXT NOT NULL, detail TEXT NOT NULL)",
        )
    }

    /** The 5A queue (version 1) keeps its rows: they get the new columns' defaults. */
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE ready ADD COLUMN origin TEXT NOT NULL DEFAULT 'inbox'")
            db.execSQL("ALTER TABLE ready ADD COLUMN notify INTEGER NOT NULL DEFAULT 0")
            createV2(db)
        }
    }

    /** Adds rows; one already queued, or uploaded in the last days (`seen`), is left out. */
    fun addReady(rows: List<InboxRow>): Int {
        if (rows.isEmpty()) return 0
        val db = writableDatabase
        var added = 0
        db.beginTransaction()
        try {
            for (r in rows) {
                val seen = db.rawQuery("SELECT 1 FROM seen WHERE msg_id = ?", arrayOf(r.msgId)).use { it.moveToFirst() }
                if (seen) continue
                val values = ContentValues().apply {
                    put("msg_id", r.msgId)
                    put("sender", r.sender)
                    put("body", r.body)
                    put("received_ms", r.receivedMs)
                    put("origin", r.origin)
                    put("notify", if (r.notify) 1 else 0)
                }
                if (db.insertWithOnConflict("ready", null, values, SQLiteDatabase.CONFLICT_IGNORE) != -1L) added++
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        return added
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

    /** A live message whose inbox row did not come in time: it is sent itself (origin live). */
    fun promote(a: Awaiting) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val values = ContentValues().apply {
                put("msg_id", "live-${a.id}")
                put("sender", a.sender)
                put("body", a.body)
                put("received_ms", a.hintMs)
                put("origin", "live")
                put("notify", 1)
            }
            db.insertWithOnConflict("ready", null, values, SQLiteDatabase.CONFLICT_IGNORE)
            db.delete("awaiting", "id = ?", arrayOf(a.id.toString()))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    /** The oldest ready rows, at most [limit]. */
    fun nextBatch(limit: Int = Wire.BATCH): List<InboxRow> =
        readableDatabase.rawQuery(
            "SELECT msg_id, sender, body, received_ms, origin, notify FROM ready ORDER BY received_ms, msg_id LIMIT $limit",
            null,
        ).use { c ->
            generateSequence {
                if (c.moveToNext()) {
                    InboxRow(c.getString(0), c.getString(1), c.getString(2), c.getLong(3), c.getString(4), c.getInt(5) == 1)
                } else {
                    null
                }
            }.toList()
        }

    /** Rows the server answered for: out of `ready`, into `seen` (kept 3 days). */
    fun remove(rows: List<InboxRow>, nowMs: Long = System.currentTimeMillis()) {
        if (rows.isEmpty()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (r in rows) {
                db.delete("ready", "msg_id = ?", arrayOf(r.msgId))
                db.insertWithOnConflict(
                    "seen", null,
                    ContentValues().apply { put("msg_id", r.msgId); put("received_ms", r.receivedMs) },
                    SQLiteDatabase.CONFLICT_REPLACE,
                )
            }
            db.delete("seen", "received_ms < ?", arrayOf((nowMs - SEEN_MS).toString()))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun counts(): Pair<Int, Int> = readableDatabase.rawQuery(
        "SELECT (SELECT COUNT(*) FROM ready), (SELECT COUNT(*) FROM awaiting)",
        null,
    ).use { c -> if (c.moveToFirst()) c.getInt(0) to c.getInt(1) else 0 to 0 }

    /** One event for the status screen: a type and counts, codes or a class name only. */
    fun log(type: String, detail: String = "", nowMs: Long = System.currentTimeMillis()) {
        val db = writableDatabase
        db.insert("events", null, ContentValues().apply { put("at_ms", nowMs); put("type", type); put("detail", detail.take(120)) })
        db.execSQL("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT $EVENTS)")
    }

    fun events(): List<Event> =
        readableDatabase.rawQuery("SELECT at_ms, type, detail FROM events ORDER BY id DESC LIMIT $EVENTS", null).use { c ->
            generateSequence { if (c.moveToNext()) Event(c.getLong(0), c.getString(1), c.getString(2)) else null }.toList()
        }

    /** Another login on this phone: nothing of the earlier owner's stays. */
    fun clear() {
        writableDatabase.execSQL("DELETE FROM ready")
        writableDatabase.execSQL("DELETE FROM awaiting")
        writableDatabase.execSQL("DELETE FROM seen")
        writableDatabase.execSQL("DELETE FROM events")
    }

    private companion object {
        const val SEEN_MS = 3 * 24 * 60 * 60_000L
        const val EVENTS = 100
    }
}
