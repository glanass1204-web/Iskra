package ru.iskra.assistant

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings
import android.telephony.SmsManager
import androidx.core.content.ContextCompat
import ru.iskra.core.DeviceAction
import ru.iskra.core.DeviceAction.OpenSettings.Panel
import ru.iskra.core.DeviceAction.Volume.Change
import ru.iskra.core.normalize

/** Запрос разрешений Android; реализует экран, на котором сейчас пользователь. */
fun interface PermissionGate {
    suspend fun request(vararg permissions: String): Boolean
}

/** Действие, готовое к выполнению: например, имя «мама» уже превращено в номер. */
data class Prepared(val action: DeviceAction, val confirm: String?, val number: String? = null)

/** Выполняет команды Искры на телефоне. */
class PhoneActions(private val context: Context) {

    private fun granted(p: String) = ContextCompat.checkSelfPermission(context, p) == PackageManager.PERMISSION_GRANTED

    /** Подготовка: находит контакт и формирует текст подтверждения. Возвращает текст ошибки, если не вышло. */
    suspend fun prepare(action: DeviceAction, gate: PermissionGate): Result<Prepared> {
        val who = when (action) {
            is DeviceAction.Call -> action.who
            is DeviceAction.SendSms -> action.who
            else -> return Result.success(Prepared(action, action.confirm))
        }
        val number = if (who.any { it.isLetter() }) {
            if (!granted(Manifest.permission.READ_CONTACTS) && !gate.request(Manifest.permission.READ_CONTACTS)) {
                return Result.failure(Exception("Чтобы звонить по имени, разреши доступ к контактам. Или назови номер."))
            }
            val contact = findContact(who) ?: return Result.failure(Exception("Не нашла «$who» в контактах."))
            "${contact.first} (${contact.second})" to contact.second
        } else {
            who to who
        }
        val confirm = when (action) {
            is DeviceAction.SendSms -> "Отправить СМС: ${number.first}?\n«${action.body}»"
            else -> "Позвонить: ${number.first}?"
        }
        return Result.success(Prepared(action, confirm, number.second))
    }

    /** Выполняет действие. Возвращает текст ответа, если он отличается от заготовленного. */
    suspend fun execute(p: Prepared, gate: PermissionGate): String? = when (val a = p.action) {
        is DeviceAction.Call -> {
            val uri = Uri.parse("tel:" + Uri.encode(p.number))
            if (granted(Manifest.permission.CALL_PHONE) || gate.request(Manifest.permission.CALL_PHONE)) {
                start(Intent(Intent.ACTION_CALL, uri))
            } else {
                start(Intent(Intent.ACTION_DIAL, uri))
                "Разрешения на звонки нет — открыла набор номера, нажми «Вызов» сам."
            }
        }
        is DeviceAction.SendSms -> {
            if (granted(Manifest.permission.SEND_SMS) || gate.request(Manifest.permission.SEND_SMS)) {
                sendSms(p.number!!, a.body)
            } else {
                start(Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + p.number)).putExtra("sms_body", a.body))
                "Разрешения на СМС нет — открыла сообщения с готовым текстом."
            }
        }
        is DeviceAction.Navigate -> start(Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(a.place))))
        is DeviceAction.SetAlarm -> start(
            Intent(AlarmClock.ACTION_SET_ALARM)
                .putExtra(AlarmClock.EXTRA_HOUR, a.hour)
                .putExtra(AlarmClock.EXTRA_MINUTES, a.minute)
                .putExtra(AlarmClock.EXTRA_MESSAGE, a.label)
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true),
        )
        is DeviceAction.SetTimer -> start(
            Intent(AlarmClock.ACTION_SET_TIMER)
                .putExtra(AlarmClock.EXTRA_LENGTH, a.seconds.toInt())
                .putExtra(AlarmClock.EXTRA_MESSAGE, a.label)
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true),
        )
        is DeviceAction.Flashlight -> torch(a.on)
        is DeviceAction.OpenApp -> openApp(a.name)
        is DeviceAction.Volume -> volume(a.change)
        is DeviceAction.OpenSettings -> start(settingsIntent(a.panel))
        DeviceAction.Camera -> start(Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA))
        DeviceAction.Battery -> battery()
        DeviceAction.Vibrate -> {
            context.getSystemService(Vibrator::class.java)
                ?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 120, 80, 120), -1))
            null
        }
        // Удаление из памяти выполняет экран чата, а не телефон.
        is DeviceAction.Forget -> null
    }

    private fun start(intent: Intent): String? = try {
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        null
    } catch (e: ActivityNotFoundException) {
        "На телефоне нет приложения, которое это умеет."
    } catch (e: SecurityException) {
        "Android не разрешил это действие."
    }

    private fun sendSms(number: String, body: String): String? = try {
        val sms = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION") SmsManager.getDefault()
        }
        sms.sendMultipartTextMessage(number, null, sms.divideMessage(body), null, null)
        null
    } catch (e: Exception) {
        "Не получилось отправить СМС: ${e.message ?: "ошибка оператора"}."
    }

    private fun findContact(name: String): Pair<String, String>? {
        val query = normalize(name)
        // Русские падежи: «маме» → «мам», «Саше» → «саш».
        val stems = listOf(query, query.dropLast(1), query.dropLast(2)).filter { it.length >= 2 }.distinct()
        val contacts = mutableListOf<Pair<String, String>>()
        context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER),
            null, null, null,
        )?.use { c ->
            while (c.moveToNext()) contacts += (c.getString(0) ?: continue) to (c.getString(1) ?: continue)
        }
        for (stem in stems) {
            contacts.firstOrNull { normalize(it.first) == stem }?.let { return it }
            contacts.firstOrNull { normalize(it.first).split(' ').any { w -> w.startsWith(stem) } }?.let { return it }
        }
        return null
    }

    private fun torch(on: Boolean): String? = try {
        val cm = context.getSystemService(CameraManager::class.java)
        val id = cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
        if (id == null) "У этого телефона нет вспышки." else { cm.setTorchMode(id, on); null }
    } catch (e: Exception) {
        "Фонарик сейчас занят — возможно, открыта камера."
    }

    private fun volume(change: Change): String? {
        val am = context.getSystemService(AudioManager::class.java)
        return try {
            when (change) {
                Change.UP -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                Change.DOWN -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
                Change.MAX -> am.setStreamVolume(
                    AudioManager.STREAM_MUSIC, am.getStreamMaxVolume(AudioManager.STREAM_MUSIC), AudioManager.FLAG_SHOW_UI,
                )
                // Полная тишина требует доступа к «Не беспокоить», поэтому включаем вибрацию.
                Change.MUTE -> am.ringerMode = AudioManager.RINGER_MODE_VIBRATE
            }
            null
        } catch (e: SecurityException) {
            "Android не дал изменить звук — открой шторку и переключи режим сам."
        }
    }

    private fun settingsIntent(panel: Panel): Intent = when {
        panel == Panel.WIFI && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> Intent(Settings.Panel.ACTION_WIFI)
        panel == Panel.INTERNET && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> Intent(Settings.Panel.ACTION_INTERNET_CONNECTIVITY)
        panel == Panel.VOLUME && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> Intent(Settings.Panel.ACTION_VOLUME)
        panel == Panel.WIFI -> Intent(Settings.ACTION_WIFI_SETTINGS)
        panel == Panel.BLUETOOTH -> Intent(Settings.ACTION_BLUETOOTH_SETTINGS)
        panel == Panel.BATTERY -> Intent(Intent.ACTION_POWER_USAGE_SUMMARY)
        else -> Intent(Settings.ACTION_SETTINGS)
    }

    private fun battery(): String {
        val bm = context.getSystemService(BatteryManager::class.java)
        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        return "Заряд $level%" + if (bm.isCharging) ", заряжается." else "."
    }

    private fun openApp(spoken: String): String? {
        val name = normalize(spoken)
        val wanted = (listOf(name) + (APP_ALIASES[name] ?: emptyList())).map { it.lowercase() }
        val pm = context.packageManager
        val launchers = pm.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0,
        )
        val match = launchers.firstOrNull { ri ->
            val label = normalize(ri.loadLabel(pm).toString())
            wanted.any { label == it }
        } ?: launchers.firstOrNull { ri ->
            val label = normalize(ri.loadLabel(pm).toString())
            wanted.any { label.contains(it) || ri.activityInfo.packageName.contains(it.replace(" ", "")) }
        } ?: return "Не нашла приложение «$spoken»."
        return start(pm.getLaunchIntentForPackage(match.activityInfo.packageName) ?: return "Не получилось открыть «$spoken».")
    }

    companion object {
        /** Как приложения называют вслух → как они подписаны на телефоне. */
        private val APP_ALIASES = mapOf(
            "телеграм" to listOf("telegram"), "телеграмм" to listOf("telegram"), "телегу" to listOf("telegram"),
            "ватсап" to listOf("whatsapp"), "вотсап" to listOf("whatsapp"), "вацап" to listOf("whatsapp"),
            "ютуб" to listOf("youtube"), "вк" to listOf("vk", "вконтакте"), "вконтакте" to listOf("vk"),
            "инстаграм" to listOf("instagram"), "хром" to listOf("chrome"), "браузер" to listOf("internet", "chrome", "интернет"),
            "карты" to listOf("maps", "карты"), "яндекс" to listOf("yandex", "яндекс"), "камеру" to listOf("камера", "camera"),
            "галерею" to listOf("галерея", "gallery"), "калькулятор" to listOf("calculator"), "почту" to listOf("gmail", "почта", "email"),
            "настройки" to listOf("settings"), "музыку" to listOf("music", "музыка"), "сбер" to listOf("сбербанк", "sber"),
            "госуслуги" to listOf("госуслуги", "gosuslugi"), "тикток" to listOf("tiktok"), "плей маркет" to listOf("play маркет", "play store"),
        )
    }
}
