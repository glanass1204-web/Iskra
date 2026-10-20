package ru.iskra.core

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.util.UUID

@Serializable
data class Settings(
    val name: String = "дружище",
    val apiKey: String = "",
    val voiceReplies: Boolean = true,
    val autoListen: Boolean = false,
    /** Родной город для погоды, в именительном падеже. */
    val city: String = "",
    /** Движок озвучки (пакет) и голос; пусто — системные по умолчанию. */
    val ttsEngine: String = "",
    val voiceName: String = "",
    val speechRate: Float = 1.0f,
    val pitch: Float = 1.0f,
    val darkTheme: Boolean = false,
    /** Режим «с матом» (18+), только по желанию пользователя. */
    val rudeMode: Boolean = false,
)

@Serializable
data class Fact(val id: String = newId(), val text: String, val at: Long)

@Serializable
data class Task(val id: String = newId(), val text: String, val done: Boolean = false, val at: Long)

@Serializable
data class Reminder(val id: String = newId(), val text: String, val due: Long, val fired: Boolean = false)

@Serializable
data class Watch(val id: String = newId(), val query: String, val last: String = "", val checkedAt: Long = 0)

@Serializable
enum class EntryKind { INCOME, EXPENSE }

@Serializable
data class Entry(val id: String = newId(), val kind: EntryKind, val amount: Double, val project: String, val at: Long)

@Serializable
enum class Speaker { ME, ISKRA }

@Serializable
data class ChatLine(val who: Speaker, val text: String, val at: Long, val link: String? = null)

@Serializable
data class IskraData(
    val settings: Settings = Settings(),
    val memory: List<Fact> = emptyList(),
    val tasks: List<Task> = emptyList(),
    val reminders: List<Reminder> = emptyList(),
    val watches: List<Watch> = emptyList(),
    val ledger: List<Entry> = emptyList(),
    val chat: List<ChatLine> = emptyList(),
) {
    val openTasks get() = tasks.filter { !it.done }
    val pendingReminders get() = reminders.filter { !it.fired }.sortedBy { it.due }
}

fun newId(): String = UUID.randomUUID().toString()

/**
 * Личная память Искры. Хранится одним JSON-файлом в закрытой папке приложения,
 * никуда не отправляется.
 */
class Store(private val file: File?) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val state = MutableStateFlow(load())

    val data: StateFlow<IskraData> = state.asStateFlow()
    val value: IskraData get() = state.value

    private fun load(): IskraData = try {
        if (file != null && file.exists()) json.decodeFromString(IskraData.serializer(), file.readText()) else IskraData()
    } catch (e: Exception) {
        // Повреждённый файл не должен ломать запуск: сохраняем копию и начинаем с чистого листа.
        file?.copyTo(File(file.path + ".broken"), overwrite = true)
        IskraData()
    }

    @Synchronized
    fun update(transform: (IskraData) -> IskraData) {
        val next = transform(state.value)
        state.value = next
        file?.let {
            val tmp = File(it.path + ".tmp")
            tmp.writeText(json.encodeToString(IskraData.serializer(), next))
            tmp.renameTo(it)
        }
    }

    fun addChat(who: Speaker, text: String, link: String? = null, now: Long = System.currentTimeMillis()) = update {
        it.copy(chat = (it.chat + ChatLine(who, text, now, link)).takeLast(300))
    }

    fun wipe() = update { IskraData() }

    fun exportJson(): String = json.encodeToString(
        IskraData.serializer(),
        value.copy(settings = value.settings.copy(apiKey = "")),
    )
}
