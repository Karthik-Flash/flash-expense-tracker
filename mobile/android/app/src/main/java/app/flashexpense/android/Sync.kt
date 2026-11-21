package app.flashexpense.android

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

/**
 * One upload run (D-124): scan the inbox from the cursor into the queue, settle the live
 * messages waiting for their inbox row, then send the queue in batches of 500. History,
 * live messages and the 6-hourly catch-up are all this run; only the cursor differs.
 */
object Sync {
    private const val TAG = "FlashSms" // counts and codes only, never a message
    private val lock = Any()

    enum class Result { DONE, RETRY }

    fun run(context: Context): Result = synchronized(lock) {
        val store = Store(context)
        val token = store.token()
        if (store.revoked || token == null || store.apiUrl == null) return Result.DONE
        val queue = SmsQueue(context)
        val senders = BankSenders.load(context)
        if (canRead(context) && store.cursorMs != null) {
            scan(context, store, queue, senders)
            settleAwaiting(context, queue, senders, store)
        }
        var stored = 0
        try {
            while (true) {
                val batch = queue.nextBatch()
                if (batch.isEmpty()) break
                val (status, body) = post("${store.apiUrl}/api/v1/ingest/sms", token, Wire.batchJson(batch))
                val outcome = Wire.outcome(status, Wire.detail(body))
                store.noteAttempt(outcome.code, System.currentTimeMillis())
                Log.i(TAG, "upload ${batch.size}: ${outcome.code}")
                when (outcome) {
                    Wire.Outcome.STORED -> {
                        queue.remove(batch)
                        stored += Wire.storedCount(body)
                        store.noteUpload(stored, System.currentTimeMillis())
                    }
                    Wire.Outcome.REVOKED, Wire.Outcome.SIGNED_OUT -> {
                        store.revoked = true // stop until the owner connects again
                        return Result.DONE
                    }
                    else -> return Result.RETRY
                }
            }
        } finally {
            if (stored > 0) Events.uploaded(stored)
        }
        // A live message whose inbox row is not there yet: run again (backoff) to settle it.
        return if (queue.counts().second > 0) Result.RETRY else Result.DONE
    }

    fun canRead(context: Context): Boolean =
        context.checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED

    /** Inbox rows after the cursor into the queue, page by page; the cursor moves after each. */
    private fun scan(context: Context, store: Store, queue: SmsQueue, senders: BankSenders) {
        val inbox = Inbox(context, senders)
        var after = Wire.scanFrom(store.cursorMs ?: return)
        while (true) {
            val page = inbox.page(after)
            if (page.isEmpty()) return
            queue.addReady(page)
            after = page.last().receivedMs
            store.cursorMs = maxOf(store.cursorMs ?: 0L, after)
        }
    }

    /** A live message is settled when its inbox row exists (the scan queued it), or dropped
     *  after 24 h (it left the inbox; a laptop export would not have it either). */
    private fun settleAwaiting(context: Context, queue: SmsQueue, senders: BankSenders, store: Store) {
        val inbox = Inbox(context, senders)
        val now = System.currentTimeMillis()
        val waiting = queue.awaiting()
        val settled = waiting.filter { inbox.holds(it.sender, it.body, it.hintMs) }
        val expired = waiting.filter { it !in settled && Wire.expired(it.hintMs, now) }
        queue.dropAwaiting((settled + expired).map { it.id })
        store.noteDropped(expired.size)
    }

    /** (status, body); status 0 when the server could not be reached. */
    private fun post(url: String, token: String, json: String): Pair<Int, String?> = try {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 30_000
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
    override fun doWork(): Result = when (Sync.run(applicationContext)) {
        Sync.Result.DONE -> Result.success()
        Sync.Result.RETRY -> Result.retry()
    }
}

/** Unique work: one upload queued at a time, and the 6-hourly catch-up (network required). */
object Work {
    private const val UPLOAD = "flash-upload"
    private const val CATCH_UP = "flash-catch-up"
    private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** [now]: the owner asked (history, Sync now): replace a run waiting out a backoff. */
    fun upload(context: Context, now: Boolean = false) {
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(network)
            .setInitialDelay(if (now) 0 else 10, TimeUnit.SECONDS) // the SMS app writes the inbox row first
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        val policy = if (now) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP
        WorkManager.getInstance(context).enqueueUniqueWork(UPLOAD, policy, request)
    }

    fun catchUp(context: Context) {
        val request = PeriodicWorkRequestBuilder<UploadWorker>(6, TimeUnit.HOURS)
            .setConstraints(network)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(CATCH_UP, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).apply {
            cancelUniqueWork(UPLOAD)
            cancelUniqueWork(CATCH_UP)
        }
    }
}

/** Tells the open app that an upload stored something, so it refreshes (3.6). */
object Events {
    @Volatile
    var listener: ((Int) -> Unit)? = null

    fun uploaded(stored: Int) {
        listener?.invoke(stored)
    }
}

fun BankSenders.Companion.load(context: Context): BankSenders =
    BankSenders.parse(context.assets.open("bank_senders.json").bufferedReader(Charsets.UTF_8).use { it.readText() })
