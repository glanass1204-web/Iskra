package ru.iskra.core

/**
 * Действие, которое должен выполнить телефон. Если [confirm] не null,
 * приложение сначала спрашивает подтверждение с этим текстом.
 */
sealed interface DeviceAction {
    val confirm: String? get() = null

    /** Кому звонить: номер или имя из контактов. */
    data class Call(val who: String) : DeviceAction {
        override val confirm get() = "Позвонить: $who?"
    }

    data class SendSms(val who: String, val body: String) : DeviceAction {
        override val confirm get() = "Отправить СМС ($who)?\n«$body»"
    }

    data class Navigate(val place: String) : DeviceAction
    data class SetAlarm(val hour: Int, val minute: Int, val label: String) : DeviceAction
    data class SetTimer(val seconds: Long, val label: String) : DeviceAction
    data class Flashlight(val on: Boolean) : DeviceAction
    data class OpenApp(val name: String) : DeviceAction
    data class Volume(val change: Change) : DeviceAction {
        enum class Change { UP, DOWN, MUTE, MAX }
    }

    data class OpenSettings(val panel: Panel) : DeviceAction {
        enum class Panel { WIFI, BLUETOOTH, INTERNET, VOLUME, BATTERY, MAIN }
    }

    data object Camera : DeviceAction
    data object Battery : DeviceAction
    data object Vibrate : DeviceAction

    /** Удаление личных данных — тоже только с подтверждением. */
    data class Forget(val ids: Set<String>, val preview: List<String>) : DeviceAction {
        override val confirm get() = "Удалить из памяти?\n" + preview.joinToString("\n") { "• $it" }
    }
}

/** Ответ Искры на одну реплику. */
data class Reply(
    val text: String,
    val action: DeviceAction? = null,
    /** Вопрос, на который нужен интернет (поиск или Claude). */
    val online: OnlineRequest? = null,
    val link: String? = null,
)

sealed interface OnlineRequest {
    data class Ask(val question: String, val searchHint: String? = null) : OnlineRequest
    data object CheckWatches : OnlineRequest
}
