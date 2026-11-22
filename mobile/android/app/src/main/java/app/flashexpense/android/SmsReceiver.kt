package app.flashexpense.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * Live SMS (D-124; 5B-2, D-142): the system's SMS_RECEIVED broadcast (only the system may send
 * it: BROADCAST_SMS in the manifest). Bank messages become "awaiting" queue rows and start an
 * upload at once (expedited, replacing a run that waits out a backoff); every other message is
 * dropped here, unread beyond its sender and never stored. A phone that is disconnected or
 * signed out still queues: Reconnect sends what came meanwhile. Quick work only (a small
 * SQLite insert); the upload runs in WorkManager.
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val store = Store(context)
        if (store.user == null || store.cursorMs == null) return // Bank SMS was never set up
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val senders = BankSenders.load(context)
        val now = System.currentTimeMillis()
        val queue = SmsQueue(context)
        val cores = mutableListOf<String>()
        // A long SMS arrives in parts from one address: the inbox row holds them joined.
        for ((address, pieces) in parts.filterNotNull().groupBy { it.originatingAddress ?: "" }) {
            if (senders.bankOf(address) == null) continue
            val body = pieces.joinToString("") { it.messageBody ?: "" }
            if (!senders.accepts(address, body) || !Wire.sendable(address, body)) continue
            queue.addAwaiting(address, body, now)
            cores += SenderRules.parseSender(address).first
        }
        if (cores.isEmpty()) return
        store.lastSmsSeenMs = now
        queue.log("sms_live", cores.joinToString(",")) // bank sender codes only
        Work.upload(context, "live")
    }
}
