package ru.iskra.assistant

import android.Manifest
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import ru.iskra.core.Speaker

/**
 * Ставит системные будильники AlarmManager на каждое напоминание,
 * поэтому они срабатывают, даже если Искра закрыта или телефон перезагружен.
 */
class ReminderScheduler(private val context: Context) {
    private val alarms = context.getSystemService(AlarmManager::class.java)

    fun sync() {
        val now = System.currentTimeMillis()
        for (r in context.iskra.store.value.pendingReminders) {
            if (r.due <= now) {
                fire(context, r.id)
                continue
            }
            val pi = pendingIntent(r.id)
            val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarms.canScheduleExactAlarms()
            if (exact) alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, r.due, pi)
            else alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, r.due, pi)
        }
    }

    private fun pendingIntent(id: String): PendingIntent = PendingIntent.getBroadcast(
        context,
        id.hashCode(),
        Intent(context, ReminderReceiver::class.java).putExtra(EXTRA_ID, id),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    companion object {
        const val EXTRA_ID = "reminder_id"

        fun fire(context: Context, id: String) {
            val store = context.iskra.store
            val reminder = store.value.reminders.firstOrNull { it.id == id && !it.fired } ?: return
            store.update { d -> d.copy(reminders = d.reminders.map { if (it.id == id) it.copy(fired = true) else it }) }
            store.addChat(Speaker.ISKRA, "Напоминаю: ${reminder.text}")

            if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            ) return
            val open = PendingIntent.getActivity(
                context, 0,
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE,
            )
            val notification = NotificationCompat.Builder(context, IskraApp.CHANNEL_REMINDERS)
                .setSmallIcon(R.drawable.ic_spark)
                .setContentTitle("Искра напоминает")
                .setContentText(reminder.text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(reminder.text))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            NotificationManagerCompat.from(context).notify(id.hashCode(), notification)
        }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra(ReminderScheduler.EXTRA_ID) ?: return
        ReminderScheduler.fire(context, id)
    }
}

/** После перезагрузки или обновления заново ставит все будильники. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        context.iskra.reminders.sync()
    }
}
