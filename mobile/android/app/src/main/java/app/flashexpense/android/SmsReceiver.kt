package app.flashexpense.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * Live SMS (D-124): the system's SMS_RECEIVED broadcast (only the system may send it:
 * BROADCAST_SMS in the manifest). Bank messages become "awaiting" queue rows and start the
 * upload; every other message is dropped here, unread beyond its sender and never stored.
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val store = Store(context)
        if (!store.connected || store.revoked || store.cursorMs == null) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val senders = BankSenders.load(context)
        val now = System.currentTimeMillis()
        val queue = SmsQueue(context)
        var queued = 0
        // A long SMS arrives in parts from one address: the inbox row holds them joined.
        for ((address, pieces) in parts.filterNotNull().groupBy { it.originatingAddress ?: "" }) {
            if (senders.bankOf(address) == null) continue
            val body = pieces.joinToString("") { it.messageBody ?: "" }
            if (!senders.accepts(address, body)) continue
            queue.addAwaiting(address, body, now)
            queued++
        }
        if (queued > 0) Work.upload(context)
    }
}
