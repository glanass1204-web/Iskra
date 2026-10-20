package ru.iskra.assistant

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import ru.iskra.core.Brain
import ru.iskra.core.OnlineHelper
import ru.iskra.core.Store
import java.io.File

class IskraApp : Application() {
    val store by lazy { Store(File(filesDir, "iskra.json")) }
    val brain by lazy { Brain(store) }
    val online by lazy { OnlineHelper(store) }
    val reminders by lazy { ReminderScheduler(this) }

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_REMINDERS, "Напоминания", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Напоминания, которые ты просил поставить"
                enableVibration(true)
            },
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_WATCH, "Мониторинг", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Изменения по темам, за которыми следит Искра"
            },
        )
        reminders.sync()
        WatchWorker.schedule(this)
    }

    companion object {
        const val CHANNEL_REMINDERS = "reminders"
        const val CHANNEL_WATCH = "watch"
    }
}

val Context.iskra: IskraApp get() = applicationContext as IskraApp
