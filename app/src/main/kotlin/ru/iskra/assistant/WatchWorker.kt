package ru.iskra.assistant

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/** Раз в несколько часов, когда есть сеть, проверяет темы мониторинга. */
class WatchWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext.iskra
        if (app.store.value.watches.isEmpty()) return Result.success()
        val (_, changed) = app.online.checkWatches()
        if (changed.isNotEmpty() && canNotify()) {
            val text = "Есть новое: " + changed.joinToString(", ")
            val n = NotificationCompat.Builder(applicationContext, IskraApp.CHANNEL_WATCH)
                .setSmallIcon(R.drawable.ic_spark)
                .setContentTitle("Искра: мониторинг")
                .setContentText(text)
                .setAutoCancel(true)
                .build()
            NotificationManagerCompat.from(applicationContext).notify(NOTIFICATION_ID, n)
        }
        return Result.success()
    }

    private fun canNotify() = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    companion object {
        private const val NOTIFICATION_ID = 4242

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<WatchWorker>(6, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork("watch", ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
