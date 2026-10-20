package ru.iskra.core

import com.anthropic.client.AnthropicClient
import com.anthropic.client.okhttp.AnthropicOkHttpClient
import com.anthropic.errors.AnthropicIoException
import com.anthropic.errors.AnthropicServiceException
import com.anthropic.errors.PermissionDeniedException
import com.anthropic.errors.RateLimitException
import com.anthropic.errors.UnauthorizedException
import com.anthropic.models.beta.messages.BetaMessageParam
import com.anthropic.models.beta.messages.BetaOutputConfig
import com.anthropic.models.beta.messages.BetaStopReason
import com.anthropic.models.beta.messages.BetaWebSearchTool20260209
import com.anthropic.models.beta.messages.MessageCreateParams
import java.time.Duration

data class Answer(val text: String, val link: String? = null)

/**
 * «Умный» режим: вопросы, которые не распознал локальный мозг, уходят в Claude
 * с веб-поиском. Разговор только дописывается; когда он становится длинным,
 * начинаем новый с актуальной памятью.
 */
class ClaudeAssistant(private val clientFactory: (String) -> AnthropicClient = ::defaultClient) {
    private var client: AnthropicClient? = null
    private var clientKey: String? = null
    private var system: String? = null
    private val messages = mutableListOf<BetaMessageParam>()

    @Synchronized
    fun reset() {
        system = null
        messages.clear()
    }

    @Synchronized
    /** Ответ Claude или null, если до сервиса не достучаться (например, без VPN). */
    fun ask(question: String, data: IskraData): String? {
        val key = data.settings.apiKey
        if (client == null || clientKey != key) {
            client = clientFactory(key)
            clientKey = key
            reset()
        }
        if (system == null || messages.size >= MAX_MESSAGES) {
            reset()
            system = buildSystem(data)
        }
        val checkpoint = messages.size
        messages += BetaMessageParam.builder().role(BetaMessageParam.Role.USER).content(question).build()

        try {
            // Веб-поиск может поставить ход на паузу (pause_turn) — продолжаем.
            repeat(4) {
                val params = MessageCreateParams.builder()
                    .model(MODEL)
                    .maxTokens(4096L)
                    .addBeta("server-side-fallback-2026-07-01")
                    .fallbacksDefault()
                    .outputConfig(BetaOutputConfig.builder().effort(BetaOutputConfig.Effort.LOW).build())
                    .system(system!!)
                    .addTool(BetaWebSearchTool20260209.builder().maxUses(3L).build())
                    .messages(messages.toList())
                    .build()
                val response = client!!.beta().messages().create(params)
                val stop = response.stopReason().orElse(null)
                if (stop == BetaStopReason.REFUSAL) {
                    rollback(checkpoint)
                    return "С этим вопросом я помочь не смогу. Давай попробуем что-нибудь другое."
                }
                messages += response.toParam()
                if (stop != BetaStopReason.PAUSE_TURN) {
                    val text = response.content().mapNotNull { b -> b.text().orElse(null)?.text() }.joinToString("").trim()
                    return text.ifEmpty { "Готово." }
                }
            }
            return "Поиск занял слишком много шагов. Попробуй спросить точнее."
        } catch (e: UnauthorizedException) {
            reset(); return "Ключ Claude не подошёл. Проверь его в настройках."
        } catch (e: PermissionDeniedException) {
            // Так Anthropic отвечает и на запросы из недоступных регионов.
            reset(); return null
        } catch (e: RateLimitException) {
            rollback(checkpoint); return "Слишком много запросов. Подожди минутку и спроси снова."
        } catch (e: AnthropicServiceException) {
            rollback(checkpoint); return "Claude ответил ошибкой (${e.statusCode()}). Попробуй позже."
        } catch (e: AnthropicIoException) {
            rollback(checkpoint); return null
        }
    }

    private fun rollback(size: Int) {
        // Неудавшийся ход убираем целиком; если он частично записан — начинаем заново.
        if (messages.size == size + 1) messages.removeAt(size) else reset()
    }

    companion object {
        const val MODEL = "claude-opus-5-5"
        private const val MAX_MESSAGES = 40

        fun defaultClient(key: String): AnthropicClient = AnthropicOkHttpClient.builder()
            .apiKey(key)
            .timeout(Duration.ofSeconds(90))
            .build()

        fun buildSystem(data: IskraData): String {
            val facts = data.memory.joinToString("\n") { "- ${it.text}" }.ifEmpty { "- (пока пусто)" }
            val tasks = data.openTasks.joinToString("\n") { "- ${it.text}" }.ifEmpty { "- (нет)" }
            return """Ты — Искра, персональный голосовой ИИ-помощник пользователя на его телефоне Samsung Galaxy.
Обращайся к пользователю «${data.settings.name.ifBlank { "дружище" }}», на «ты», тепло и по-дружески.
Отвечай по-русски, коротко и по делу: ответ будет зачитан вслух, поэтому без таблиц, markdown и длинных списков.
Если нужны свежие данные (новости, курсы, погода, цены), пользуйся веб-поиском.
Действия на телефоне выполняет приложение по командам. Если пользователь хочет позвонить, написать СМС,
поставить будильник или напоминание, подскажи точную команду, например «Позвони маме» или «Напомни через 10 минут …».
Помогай с заработком и проектами честно: без схем быстрого обогащения, с реальными шагами.

Что ты помнишь о пользователе:
$facts

Его открытые задачи:
$tasks"""
        }
    }
}

/** Отвечает на вопросы, которым нужен интернет. */
class OnlineHelper(
    private val store: Store,
    private val claude: ClaudeAssistant = ClaudeAssistant(),
    private val knowledge: Knowledge = Knowledge(),
) {
    fun resetConversation() = claude.reset()

    fun answer(req: OnlineRequest.Ask): Answer {
        val data = store.value
        if (data.settings.apiKey.isNotBlank()) {
            // Из России Claude доступен только через VPN; если связи нет — ищем сами.
            claude.ask(req.question, data)?.let { return Answer(it) }
        }
        return knowledge.answer(req.question, req.searchHint, data.settings)
    }

    /** Проверяет все запросы мониторинга. Возвращает сводку и список изменившихся тем. */
    fun checkWatches(now: Long = System.currentTimeMillis()): Pair<String, List<String>> {
        val watches = store.value.watches
        if (watches.isEmpty()) return "В мониторинге пока ничего нет. Скажи «следи за …»." to emptyList()
        val changed = mutableListOf<String>()
        val lines = watches.map { w ->
            val fresh = knowledge.answer(w.query, w.query, store.value.settings).text
            val isNew = w.last.isNotEmpty() && fresh != w.last
            if (isNew) changed += w.query
            store.update { d -> d.copy(watches = d.watches.map { x -> if (x.id == w.id) x.copy(last = fresh, checkedAt = now) else x }) }
            "• ${w.query}: " + if (isNew) "есть обновления" else if (w.last.isEmpty()) "запомнила текущее состояние" else "без изменений"
        }
        return lines.joinToString("\n") to changed
    }
}
