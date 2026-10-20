package ru.iskra.assistant

import android.app.Application
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import ru.iskra.core.DeviceAction
import ru.iskra.core.IskraData
import ru.iskra.core.OnlineRequest
import ru.iskra.core.Speaker
import ru.iskra.core.normalize

data class ConfirmRequest(val text: String, val answer: CompletableDeferred<Boolean>)

class AssistantViewModel(app: Application) : AndroidViewModel(app) {
    private val iskra = app as IskraApp
    private val store = iskra.store
    private val phone = PhoneActions(app)
    val voice = Voice(app)

    val data: StateFlow<IskraData> = store.data

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _confirm = MutableStateFlow<ConfirmRequest?>(null)
    val confirm: StateFlow<ConfirmRequest?> = _confirm.asStateFlow()

    private val _online = MutableStateFlow(isOnline())
    val online: StateFlow<Boolean> = _online.asStateFlow()

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(network: android.net.Network, caps: NetworkCapabilities) {
            _online.value = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        }
        override fun onLost(network: android.net.Network) { _online.value = false }
    }

    /** Экран подставляет сюда запрос разрешений. */
    var gate: PermissionGate = PermissionGate { false }

    init {
        if (store.value.chat.isEmpty()) {
            say("Привет, ${store.value.settings.name}! Я Искра 🔥 Нажми на микрофон и скажи, чем помочь. Скажи «что ты умеешь», чтобы увидеть команды.", speak = false)
        }
        app.getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(networkCallback)
    }


    private fun isOnline(): Boolean {
        val cm = getApplication<Application>().getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    fun listen() {
        if (voice.listening.value) {
            voice.stopListening()
            return
        }
        viewModelScope.launch {
            if (!gate.request(android.Manifest.permission.RECORD_AUDIO)) {
                say("Без доступа к микрофону я могу только читать. Разреши его в настройках приложения.")
                return@launch
            }
            if (!voice.canListen) {
                say("На телефоне не найден сервис распознавания речи. Проверь «Голосовой ввод» в настройках.")
                return@launch
            }
            voice.listen(offline = !_online.value, onText = ::submit, onError = { say(it) })
        }
    }

    fun submit(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        // Ответ голосом на открытый вопрос «Подтверди действие».
        _confirm.value?.let { pending ->
            store.addChat(Speaker.ME, clean)
            val t = normalize(clean)
            when {
                Regex("^(да|давай|подтверждаю|выполняй|ок|окей|конечно|верно)").containsMatchIn(t) -> answerConfirm(true)
                Regex("^(нет|отмена|не надо|стоп)").containsMatchIn(t) -> answerConfirm(false)
                else -> say("Скажи «да» или «нет».")
            }
            return
        }
        if (_busy.value) return
        _busy.value = true
        store.addChat(Speaker.ME, clean)
        viewModelScope.launch {
            try {
                respond(clean)
            } catch (e: Exception) {
                say(if (_online.value) "Что-то пошло не так. Попробуй ещё раз." else "Нет сети — эта функция сейчас недоступна.")
            } finally {
                _busy.value = false
            }
        }
    }

    private suspend fun respond(text: String) {
        val memoryBefore = store.value.memory to store.value.settings.name
        val reply = withContext(Dispatchers.IO) { iskra.brain.handle(text) }
        var answer = reply.text
        var link = reply.link

        reply.action?.let { action ->
            answer = runAction(action, answer)
        }

        when (val req = reply.online) {
            null -> {}
            else -> if (!_online.value) {
                answer = if (req is OnlineRequest.Ask && req.searchHint == null) {
                    "Без сети я понимаю только команды — скажи «что ты умеешь». Вопрос можно задать, когда появится интернет."
                } else {
                    "Сейчас нет интернета. Могу записать это в задачи: скажи «задача …»."
                }
            } else {
                if (req is OnlineRequest.Ask && store.value.settings.apiKey.isNotBlank()) say("Секунду, думаю…", speak = false)
                val result = withContext(Dispatchers.IO) {
                    when (req) {
                        is OnlineRequest.Ask -> iskra.online.answer(req).let { it.text to it.link }
                        OnlineRequest.CheckWatches -> iskra.online.checkWatches().first to null
                    }
                }
                answer = result.first
                link = result.second
            }
        }

        if ((store.value.memory to store.value.settings.name) != memoryBefore) iskra.online.resetConversation()
        iskra.reminders.sync()
        if (answer.isNotBlank()) say(answer, link)
    }

    private suspend fun runAction(action: DeviceAction, planned: String): String {
        if (action is DeviceAction.Forget) {
            if (!ask(action.confirm)) return "Хорошо, ничего не удаляю."
            store.update { d -> d.copy(memory = d.memory.filterNot { it.id in action.ids }) }
            return planned
        }
        val prepared = phone.prepare(action, gate).getOrElse { return it.message ?: "Не получилось." }
        if (prepared.confirm != null && !ask(prepared.confirm)) return "Отменила."
        return phone.execute(prepared, gate) ?: planned
    }

    private suspend fun ask(text: String): Boolean {
        val request = ConfirmRequest(text, CompletableDeferred())
        _confirm.value = request
        voice.speak(text.lineSequence().first() + " Подтверди.")
        return request.answer.await()
    }

    fun answerConfirm(yes: Boolean) {
        val pending = _confirm.value ?: return
        _confirm.value = null
        pending.answer.complete(yes)
    }

    private fun say(text: String, link: String? = null, speak: Boolean = true) {
        store.addChat(Speaker.ISKRA, text, link)
        if (speak && store.value.settings.voiceReplies) voice.speak(text)
    }

    // ---------- Настройки и списки ----------

    fun updateSettings(transform: (ru.iskra.core.Settings) -> ru.iskra.core.Settings) {
        store.update { it.copy(settings = transform(it.settings)) }
        iskra.online.resetConversation()
    }

    fun toggleTask(id: String) = store.update { d -> d.copy(tasks = d.tasks.map { if (it.id == id) it.copy(done = !it.done) else it }) }

    fun delete(kind: String, id: String, label: String) {
        viewModelScope.launch {
            if (!ask("Удалить «$label»?")) return@launch
            store.update { d ->
                when (kind) {
                    "task" -> d.copy(tasks = d.tasks.filterNot { it.id == id })
                    "reminder" -> d.copy(reminders = d.reminders.filterNot { it.id == id })
                    "memory" -> d.copy(memory = d.memory.filterNot { it.id == id })
                    "watch" -> d.copy(watches = d.watches.filterNot { it.id == id })
                    "entry" -> d.copy(ledger = d.ledger.filterNot { it.id == id })
                    else -> d
                }
            }
            if (kind == "memory") iskra.online.resetConversation()
        }
    }

    fun wipe() {
        viewModelScope.launch {
            if (!ask("Стереть всю память, задачи, напоминания, записи и ключ? Это нельзя отменить.")) return@launch
            store.wipe()
            iskra.online.resetConversation()
        }
    }

    fun exportJson(): String = store.exportJson()

    override fun onCleared() {
        getApplication<Application>().getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networkCallback)
        voice.release()
    }
}
