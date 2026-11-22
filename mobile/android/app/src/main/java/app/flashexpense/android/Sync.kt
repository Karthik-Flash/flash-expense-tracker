package app.flashexpense.android

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

/**
 * One upload run (D-124; 5B-2, D-142): scan the inbox from the cursor into the queue, settle
 * the live messages waiting for their inbox row (or send them themselves after 2 minutes),
 * then send the queue in batches of 500. The live receiver, the app's start and resume, Sync
 * now and the hourly catch-up all start this run; only the trigger differs.
 */
object Sync {
    private const val TAG = "FlashSms" // counts and codes only, never a message
    private val lock = Any()

    enum class Result { DONE, RETRY }

    fun run(context: Context, trigger: String = "work"): Result = synchronized(lock) {
        val store = Store(context)
        val queue = SmsQueue(context)
        val senders = BankSenders.load(context)
        val now = System.currentTimeMillis()
        if (canRead(context) && store.cursorMs != null) {
            try {
                scan(context, store, queue, senders, now)
                settleAwaiting(context, queue, senders, store, now)
            } catch (e: Exception) { // the provider can fail (a locked or busy phone): next run
                queue.log("scan_failed", e.javaClass.simpleName)
            }
        }
        val token = store.token()
        if (store.revoked || token == null || store.apiUrl == null) {
            // Disconnected or signed out: the queue keeps everything for Reconnect (D-143).
            return Result.DONE
        }
        var stored = 0
        var limit = Wire.BATCH
        try {
            while (true) {
                val batch = queue.nextBatch(limit)
                if (batch.isEmpty()) break
                val (status, body) = post("${store.apiUrl}/api/v1/ingest/sms", token, Wire.batchJson(batch))
                val outcome = Wire.outcome(status, Wire.detail(body))
                store.noteAttempt(outcome.code, System.currentTimeMillis())
                queue.log("upload", "$trigger ${batch.size} -> ${if (status > 0) status else outcome.code}")
                Log.i(TAG, "upload ${batch.size}: ${outcome.code}")
                when (Wire.next(outcome, batch.size)) {
                    Wire.Next.CLEAR -> {
                        queue.remove(batch)
                        stored += Wire.storedCount(body)
                        store.noteUpload(stored, System.currentTimeMillis())
                        announce(context, store, queue, batch, Wire.newPayments(body))
                        limit = Wire.BATCH
                    }
                    Wire.Next.SPLIT -> limit = 1 // find the one row the server refuses
                    Wire.Next.DROP_ONE -> {
                        queue.remove(batch) // the server refused this message on its own
                        queue.log("dropped_refused", "1 (http $status)")
                        limit = Wire.BATCH
                    }
                    Wire.Next.STOP -> {
                        store.revoked = true // "Phone disconnected": Reconnect, nothing is lost
                        queue.log("disconnected", "http $status")
                        return Result.DONE
                    }
                    Wire.Next.RETRY -> return Result.RETRY
                }
            }
        } finally {
            if (stored > 0) Events.uploaded(stored)
        }
        // A live message still inside its 2 minutes: run again soon to settle or send it.
        return if (queue.counts().second > 0) Result.RETRY else Result.DONE
    }

    fun canRead(context: Context): Boolean =
        context.checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED

    /** Inbox rows after the cursor into the queue, page by page. The cursor (date and _id)
     *  moves only after a page is written to the queue, so it never passes a row not queued. */
    private fun scan(context: Context, store: Store, queue: SmsQueue, senders: BankSenders, now: Long) {
        val inbox = Inbox(context, senders)
        var after = Wire.scanFrom(store.cursorMs ?: return)
        var afterId = store.lastId
        val quiet = store.quietScan
        var added = 0
        while (true) {
            val (page, maxId) = inbox.page(after, afterId)
            if (maxId == null) break // nothing more to read
            val rows = page.map { it.copy(notify = !quiet && now - it.receivedMs <= Wire.NOTIFY_MS) }
            added += queue.addReady(rows)
            page.lastOrNull()?.let { last ->
                after = maxOf(after, last.receivedMs)
                store.cursorMs = maxOf(store.cursorMs ?: 0L, last.receivedMs)
                store.lastSmsSeenMs = maxOf(store.lastSmsSeenMs ?: 0L, last.receivedMs)
            }
            if (afterId != null && maxId <= afterId && page.isEmpty()) break
            afterId = maxOf(afterId ?: 0L, maxId)
            store.lastId = afterId
            if (page.isEmpty()) break
        }
        if (quiet) store.quietScan = false // the old messages are read; new ones notify again
        if (added > 0) queue.log("scan", "$added new${if (quiet) ", quiet" else ""}")
    }

    /** A live message is settled when its inbox row exists (the scan queued it). One whose
     *  inbox row has not come after 2 minutes is sent itself, origin live: the server knows the
     *  two copies of one SMS apart from two messages (D-139). */
    private fun settleAwaiting(context: Context, queue: SmsQueue, senders: BankSenders, store: Store, now: Long) {
        val inbox = Inbox(context, senders)
        for (a in queue.awaiting()) {
            when {
                inbox.holds(a.sender, a.body, a.hintMs) -> queue.dropAwaiting(listOf(a.id))
                now - a.hintMs >= Wire.GRACE_MS -> {
                    queue.promote(a)
                    queue.log("live_sent_itself", SenderRules.parseSender(a.sender).first)
                }
            }
        }
    }

    /** Notifications for the new payments of an upload (D-142): only those from a live SMS, or
     *  an inbox row read soon after it came, and never during a history scan or a reconnect. */
    private fun announce(context: Context, store: Store, queue: SmsQueue, batch: List<InboxRow>, made: List<NewPayment>) {
        if (made.isEmpty()) return
        val now = System.currentTimeMillis()
        val eligible = batch.filter { Wire.mayNotify(it, now) }.map { it.msgId }.toSet()
        val shown = made.filter { it.deviceMsgId in eligible }
        val posted = Notify.post(context, shown)
        queue.log("new_payments", "${made.size} new, $posted notified")
        store.lastSmsSeenMs = maxOf(store.lastSmsSeenMs ?: 0L, batch.maxOf { it.receivedMs })
    }

    /** (status, body); status 0 when the server could not be reached or did not answer in time. */
    private fun post(url: String, token: String, json: String): Pair<Int, String?> = try {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15_000
            connection.readTimeout = 90_000 // a sleeping free server takes about a minute
            connection.doOutput = true
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/json")
            connection.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            status to stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
        } finally {
            connection.disconnect()
        }
    } catch (e: IOException) {
        0 to null
    }
}

/** The WorkManager entry point for every upload run. */
class UploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val trigger = inputData.getString("trigger") ?: "catch_up"
        return try {
            when (Sync.run(applicationContext, trigger)) {
                Sync.Result.DONE -> Result.success()
                Sync.Result.RETRY -> Result.retry()
            }
        } catch (e: Exception) { // never crash the worker; the next run tries again
            SmsQueue(applicationContext).log("run_failed", e.javaClass.simpleName)
            Result.retry()
        }
    }
}

/**
 * Unique work (5B-2, D-142): one upload at a time, started at once by a new SMS, the app's
 * start or resume and Sync now, even when an earlier run waits out a backoff; and the hourly
 * catch-up (network required). Expedited on Android 12+ (normal work when out of quota).
 */
object Work {
    private const val UPLOAD = "flash-upload"
    private const val CATCH_UP = "flash-catch-up"
    private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun upload(context: Context, trigger: String) {
        val builder = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(network)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .setInputData(androidx.work.workDataOf("trigger" to trigger))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Before Android 12 expedited work runs as a foreground service: not used there.
            builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
        }
        val manager = WorkManager.getInstance(context)
        // A run in progress finishes first (the new one follows it); one waiting out a backoff
        // is replaced, so the new SMS is sent now and never waits behind it.
        val running = try {
            manager.getWorkInfosForUniqueWork(UPLOAD).get(2, TimeUnit.SECONDS).any { it.state == WorkInfo.State.RUNNING }
        } catch (e: Exception) {
            false
        }
        val policy = if (running) ExistingWorkPolicy.APPEND_OR_REPLACE else ExistingWorkPolicy.REPLACE
        manager.enqueueUniqueWork(UPLOAD, policy, builder.build())
    }

    fun catchUp(context: Context) {
        val request = PeriodicWorkRequestBuilder<UploadWorker>(1, TimeUnit.HOURS)
            .setConstraints(network)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        // UPDATE: an install with the 6-hourly catch-up of 5A moves to hourly.
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(CATCH_UP, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).apply {
            cancelUniqueWork(UPLOAD)
            cancelUniqueWork(CATCH_UP)
        }
    }
}

/** Tells the open app that an upload stored something, so it refreshes at once (3.6). */
object Events {
    @Volatile
    var listener: ((Int) -> Unit)? = null

    fun uploaded(stored: Int) {
        listener?.invoke(stored)
    }
}

fun BankSenders.Companion.load(context: Context): BankSenders =
    BankSenders.parse(context.assets.open("bank_senders.json").bufferedReader(Charsets.UTF_8).use { it.readText() })
