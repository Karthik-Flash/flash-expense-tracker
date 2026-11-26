package app.flashexpense.android

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Payment notifications (5B-2, D-142), channel "Payments". One per new payment, grouped when
 * there are 3 or more; the lock screen shows only "New payment". A tap (or "Change category")
 * opens the app at that payment's sheet; the app makes every change, through its outbox. Native
 * code never writes anything. Without the permission (Android 13+) nothing is posted.
 */
object Notify {
    const val CHANNEL = "payments"
    const val EXTRA_TXN = "flash_txn"
    const val EXTRA_ACT = "flash_act"
    const val EXTRA_ITEM = "flash_item" // 5G-A: the payment's basics (Wire.openItem), JSON
    private const val GROUP = "flash-payments"
    private const val SUMMARY_ID = 1

    fun allowed(context: Context): Boolean =
        (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            NotificationManagerCompat.from(context).areNotificationsEnabled()

    fun channel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Payments", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "A new payment from your bank SMS"
                },
            )
        }
    }

    /** Posts the payments; returns how many. */
    fun post(context: Context, payments: List<NewPayment>): Int {
        if (payments.isEmpty() || !allowed(context)) return 0
        channel(context)
        val manager = NotificationManagerCompat.from(context)
        val grouped = payments.size >= 3
        return try {
            for (p in payments) {
                val text = Wire.notificationText(p)
                val public = base(context, p).setContentTitle("Flash").setContentText("New payment").build()
                val n = base(context, p)
                    .setContentTitle("Flash")
                    .setContentText(text)
                    .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                    .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                    .setPublicVersion(public)
                    .apply { if (grouped) setGroup(GROUP) }
                    .addAction(0, "Change category", open(context, p, "category"))
                manager.notify(notificationId(p.id), n.build())
            }
            if (grouped) {
                val summary = NotificationCompat.Builder(context, CHANNEL)
                    .setSmallIcon(R.drawable.ic_stat_flash)
                    .setContentTitle("Flash")
                    .setContentText("${payments.size} new payments")
                    .setGroup(GROUP)
                    .setGroupSummary(true)
                    .setAutoCancel(true)
                    .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                    .build()
                manager.notify(SUMMARY_ID, summary)
            }
            payments.size
        } catch (e: SecurityException) { // the permission was taken away just now
            0
        }
    }

    private fun base(context: Context, p: NewPayment): NotificationCompat.Builder =
        NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_flash)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(open(context, p, null))

    /** Opens the app at this payment (cold or warm start); `act` "category": its category list. */
    private fun open(context: Context, p: NewPayment, act: String?): PendingIntent {
        val txnId = p.id
        val intent = Intent(context, MainActivity::class.java)
            .setAction("app.flashexpense.android.OPEN_${txnId}_${act ?: "sheet"}") // one PendingIntent each
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(EXTRA_TXN, txnId)
            .putExtra(EXTRA_ACT, act ?: "sheet")
        Wire.openItem(p)?.let { intent.putExtra(EXTRA_ITEM, it) }
        return PendingIntent.getActivity(context, notificationId(txnId) + if (act == null) 0 else 1, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    /** One notification per payment, the same id when a payment is announced again. */
    fun notificationId(txnId: Long): Int = (txnId % 100_000_000L).toInt() * 2 + 10
}
