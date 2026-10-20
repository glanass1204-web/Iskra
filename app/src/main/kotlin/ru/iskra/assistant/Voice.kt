package ru.iskra.assistant

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

/**
 * Голос Искры: распознавание речи и озвучка на русском.
 * Если на телефоне скачан офлайн-пакет русского языка, оба работают без интернета.
 * Все методы вызываются из главного потока.
 */
class Voice(private val context: Context) : TextToSpeech.OnInitListener {
    private val russian = Locale.forLanguageTag("ru-RU")
    private val tts = TextToSpeech(context, this)
    private var ttsReady = false
    private var recognizer: SpeechRecognizer? = null

    private val _listening = MutableStateFlow(false)
    val listening: StateFlow<Boolean> = _listening.asStateFlow()

    private val _partial = MutableStateFlow("")
    val partial: StateFlow<String> = _partial.asStateFlow()

    val canListen get() = SpeechRecognizer.isRecognitionAvailable(context)

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            ttsReady = tts.setLanguage(russian) >= TextToSpeech.LANG_AVAILABLE
        }
    }

    fun speak(text: String) {
        if (!ttsReady || text.isBlank()) return
        tts.speak(text.replace(Regex("[•🔥«»]"), ""), TextToSpeech.QUEUE_FLUSH, null, "iskra")
    }

    fun stopSpeaking() {
        tts.stop()
    }

    /** Слушает одну фразу; [onText] получает распознанный текст, [onError] — понятное объяснение. */
    fun listen(offline: Boolean, onText: (String) -> Unit, onError: (String) -> Unit) {
        stopSpeaking()
        recognizer?.destroy()
        val onDevice = offline && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            SpeechRecognizer.isOnDeviceRecognitionAvailable(context)
        val rec = if (onDevice) SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        else SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = rec

        rec.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { _listening.value = true }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() { _listening.value = false }
            override fun onEvent(eventType: Int, params: Bundle?) {}

            override fun onPartialResults(partialResults: Bundle?) {
                partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { _partial.value = it }
            }

            override fun onResults(results: Bundle?) {
                _listening.value = false
                _partial.value = ""
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (text.isNullOrBlank()) onError("Ничего не услышала. Нажми на микрофон и говори.") else onText(text)
            }

            override fun onError(error: Int) {
                _listening.value = false
                _partial.value = ""
                onError(
                    when (error) {
                        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Ничего не услышала. Нажми на микрофон и говори."
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Разреши Искре доступ к микрофону."
                        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER ->
                            "Для голоса без сети скачай русский офлайн-пакет: Настройки → Общие настройки → Голосовой ввод."
                        13 /* ERROR_LANGUAGE_NOT_SUPPORTED */, 12 /* ERROR_LANGUAGE_UNAVAILABLE */ ->
                            "Русский язык для распознавания не скачан. Скачай его в настройках голосового ввода."
                        else -> "Не получилось распознать речь (код $error). Попробуй ещё раз."
                    },
                )
            }
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, offline)
        rec.startListening(intent)
        _listening.value = true
    }

    fun stopListening() {
        recognizer?.stopListening()
        _listening.value = false
    }

    fun release() {
        recognizer?.destroy()
        recognizer = null
        tts.shutdown()
    }
}
