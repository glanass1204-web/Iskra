package ru.iskra.core

import ru.iskra.core.DeviceAction.OpenSettings.Panel
import ru.iskra.core.DeviceAction.Volume.Change
import java.text.NumberFormat
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val RU = Locale.forLanguageTag("ru-RU")
private val TIME = DateTimeFormatter.ofPattern("HH:mm", RU)
private val DATE = DateTimeFormatter.ofPattern("EEEE, d MMMM", RU)

fun normalize(s: String) = s.lowercase(RU).replace('ё', 'е').trim().trimEnd('!', '?', '.', ',').trim()

fun formatMoney(amount: Double): String =
    NumberFormat.getNumberInstance(RU).apply { maximumFractionDigits = 2 }.format(amount).replace(' ', ' ') + " ₽"

private fun cleanTail(s: String) =
    s.replace(Regex("^\\s*(что|чтобы|о том,? что|про)\\s+"), "").replace(Regex("\\s+"), " ").trim()

const val HELP = """Вот что я умею:
• «Запомни, что …», «Что ты помнишь?», «Забудь …»
• «Задача …», «Мои задачи», «Готово 2»
• «Напомни через 15 минут …», «Напомни завтра в 9 …»
• «Позвони маме», «Напиши смс 8999… текст» — только с подтверждением
• «Будильник на 7 утра», «Таймер на 5 минут»
• «Включи фонарик», «Громче», «Без звука», «Открой Телеграм», «Настройки Wi‑Fi»
• «Маршрут до …», «Заряд батареи», «Который час?»
• «Найди …», «Что такое …», «Следи за …» — нужен интернет
• «Доход 5000 проект Сайт», «Расход 300», «Баланс», «Идеи заработка»
Без интернета работает всё, кроме поиска и свободного разговора."""

const val IDEAS = """С чего можно начать (выберем вместе и распишем план):
1. Фриланс: тексты, переводы, монтаж коротких видео, карточки для маркетплейсов.
2. Ведение соцсетей для местного бизнеса — кафе, салоны, мастерские.
3. Перепродажа и ремонт техники: телефоны, аксессуары, мелкая электроника.
4. Цифровые продукты: шаблоны, гайды, мини-курсы по тому, в чём ты силён.
5. Подработка через сервисы доставки — быстрый старт, но меньше масштаба.
Скажи «доход 1000 проект …», и я начну вести учёт по каждому проекту."""

/**
 * Локальный «мозг» Искры: понимает команды на русском без интернета.
 * Меняет данные в [store] и возвращает ответ; действия с телефоном
 * выполняет приложение, предварительно спросив подтверждение.
 */
class Brain(
    private val store: Store,
    private val zone: ZoneId = ZoneId.systemDefault(),
    private val clock: () -> LocalDateTime = { LocalDateTime.now(zone) },
) {
    private fun epochMillis(t: LocalDateTime) = t.atZone(zone).toInstant().toEpochMilli()

    fun handle(raw: String): Reply {
        val t = normalize(raw)
        val data = store.value
        val name = data.settings.name.ifBlank { "дружище" }
        val now = clock()
        val nowMs = epochMillis(now)
        var m: MatchResult?

        if (t.isEmpty()) return Reply("Я тебя слушаю.")

        if (Regex("^(привет|здравствуй|хай|добр(ое|ый) \\S+)").containsMatchIn(t)) return Reply("Привет, $name! Я Искра. Чем займёмся?")
        if (Regex("(как тебя зовут|кто ты)").containsMatchIn(t)) {
            return Reply("Я Искра — твой персональный помощник. Работаю и без интернета, а важные действия выполняю только после твоего подтверждения.")
        }
        if (Regex("(что ты умеешь|помощь|команды|справка)").containsMatchIn(t)) return Reply(HELP)
        if (Regex("(спасибо|благодарю)").containsMatchIn(t)) return Reply("Всегда пожалуйста, $name!")

        // Память
        Regex("^(?:запомни|запиши себе)[,:]?\\s+(.+)").find(t)?.let {
            val text = cleanTail(it.groupValues[1])
            store.update { d -> d.copy(memory = d.memory + Fact(text = text, at = nowMs)) }
            return Reply("Запомнила: «$text».")
        }
        Regex("^меня зовут\\s+(.+)$", RegexOption.IGNORE_CASE).find(raw.trim().trimEnd('.', '!'))?.let {
            val newName = it.groupValues[1].trim()
            store.update { d -> d.copy(settings = d.settings.copy(name = newName)) }
            return Reply("Приятно познакомиться, $newName! Буду так к тебе обращаться.")
        }
        if (Regex("(что ты (обо мне )?(помнишь|знаешь)|моя память)").containsMatchIn(t)) {
            if (data.memory.isEmpty()) return Reply("Пока ничего не запомнила. Скажи «запомни, что …».")
            return Reply("Вот что я помню:\n" + data.memory.mapIndexed { i, f -> "${i + 1}. ${f.text}" }.joinToString("\n"))
        }
        Regex("^забудь\\s+(.+)").find(t)?.let {
            val q = cleanTail(it.groupValues[1])
            val hits = data.memory.filter { f -> normalize(f.text).contains(q) }
            if (hits.isEmpty()) return Reply("Не нашла в памяти ничего про «$q».")
            return Reply("Готово, забыла.", DeviceAction.Forget(hits.map { h -> h.id }.toSet(), hits.map { h -> h.text }))
        }

        // Будильник и таймер — раньше напоминаний
        if (Regex("^(поставь |заведи )?будильник").containsMatchIn(t)) {
            val (h, min) = parseClock(t) ?: return Reply("На какое время поставить будильник? Например: «будильник на 7:30».")
            return Reply("Ставлю будильник на %02d:%02d.".format(h, min), DeviceAction.SetAlarm(h, min, "Искра"))
        }
        if (Regex("^(поставь |заведи |засеки )?таймер").containsMatchIn(t)) {
            val d = parseDuration(t) ?: return Reply("На сколько поставить таймер? Например: «таймер на 5 минут».")
            return Reply("Запускаю таймер.", DeviceAction.SetTimer(d.seconds, "Искра"))
        }

        // Напоминания
        Regex("^напомни(?:\\s+мне)?\\s+(.+)").find(t)?.let {
            val w = parseWhen(it.groupValues[1], now)
                ?: return Reply("Когда напомнить? Например: «напомни через 20 минут позвонить маме» или «напомни в 18:30 …».")
            val text = cleanTail(w.rest).ifEmpty { "то, о чём ты просил" }
            store.update { d -> d.copy(reminders = d.reminders + Reminder(text = text, due = epochMillis(w.at))) }
            val day = when (w.at.toLocalDate()) {
                now.toLocalDate() -> "сегодня"
                now.toLocalDate().plusDays(1) -> "завтра"
                else -> w.at.format(DATE)
            }
            return Reply("Напомню $day в ${w.at.format(TIME)}: «$text».")
        }
        if (Regex("^(напоминания|мои напоминания|какие напоминания)").containsMatchIn(t)) {
            val list = data.pendingReminders
            if (list.isEmpty()) return Reply("Активных напоминаний нет.")
            return Reply(list.joinToString("\n") { r ->
                "• " + java.time.Instant.ofEpochMilli(r.due).atZone(zone).format(TIME) + " — " + r.text
            })
        }

        // Задачи
        m = Regex("^(?:добавь\\s+)?задач[аиу]\\s*[:\\-]?\\s+(.+)").find(t) ?: Regex("^(?:добавь в список|надо|нужно)\\s+(.+)").find(t)
        if (m != null) {
            val text = cleanTail(m.groupValues[1])
            store.update { d -> d.copy(tasks = d.tasks + Task(text = text, at = nowMs)) }
            return Reply("Добавила задачу: «$text».")
        }
        if (Regex("^(мои задачи|список задач|задачи|что (мне )?(нужно|надо) сделать)$").matches(t)) {
            val open = data.openTasks
            if (open.isEmpty()) return Reply("Открытых задач нет. Отличная работа!")
            return Reply("Открытые задачи:\n" + open.mapIndexed { i, x -> "${i + 1}. ${x.text}" }.joinToString("\n"))
        }
        Regex("^(?:готово|выполнил[а]?|сделал[а]?)(?:\\s+задачу)?\\s+(.+)").find(t)?.let {
            val open = data.openTasks
            val arg = it.groupValues[1]
            val task = parseNumber(arg)?.toInt()?.let { n -> open.getOrNull(n - 1) }
                ?: open.firstOrNull { x -> normalize(x.text).contains(arg) }
                ?: return Reply("Не нашла такую задачу. Скажи «мои задачи», чтобы увидеть номера.")
            store.update { d -> d.copy(tasks = d.tasks.map { x -> if (x.id == task.id) x.copy(done = true) else x }) }
            return Reply("Отметила как выполненную: «${task.text}». 🔥")
        }

        // Время
        if (Regex("(который час|сколько времени|^время)$").containsMatchIn(t)) return Reply("Сейчас ${now.format(TIME)}.")
        if (Regex("(какое сегодня число|какой сегодня день|^дата)$").containsMatchIn(t)) return Reply("Сегодня ${now.format(DATE)}.")

        // Телефон
        if (Regex("(заряд|батаре)").containsMatchIn(t)) return Reply("", DeviceAction.Battery)
        if (Regex("^(вибрац|провибрируй)").containsMatchIn(t)) return Reply("Бзз-бзз!", DeviceAction.Vibrate)
        if (Regex("(включи|зажги)\\s+(фонарик|фонарь|свет)").containsMatchIn(t)) return Reply("Фонарик включён.", DeviceAction.Flashlight(true))
        if (Regex("(выключи|погаси)\\s+(фонарик|фонарь|свет)").containsMatchIn(t)) return Reply("Фонарик выключен.", DeviceAction.Flashlight(false))
        if (Regex("^(громче|сделай громче|прибавь звук)").containsMatchIn(t)) return Reply("Сделала громче.", DeviceAction.Volume(Change.UP))
        if (Regex("^(тише|сделай тише|убавь звук)").containsMatchIn(t)) return Reply("Сделала тише.", DeviceAction.Volume(Change.DOWN))
        if (Regex("^(без звука|выключи звук|беззвучн)").containsMatchIn(t)) return Reply("Включила режим вибрации.", DeviceAction.Volume(Change.MUTE))
        if (Regex("^(максимальная громкость|на полную)").containsMatchIn(t)) return Reply("Громкость на максимум.", DeviceAction.Volume(Change.MAX))
        if (Regex("(камер|сфотографир|сделай фото)").containsMatchIn(t)) return Reply("Открываю камеру.", DeviceAction.Camera)

        Regex("(?:настройки|включи|выключи|открой)\\s+(wi-?fi|вай-?фай|вайфай|блютуз|bluetooth|интернет|мобильн\\S* интернет|громкост\\S*|батаре\\S*|настройки)").find(t)?.let {
            val w = it.groupValues[1]
            val panel = when {
                Regex("wi-?fi|вай-?фай|вайфай").containsMatchIn(w) -> Panel.WIFI
                Regex("блютуз|bluetooth").containsMatchIn(w) -> Panel.BLUETOOTH
                w.contains("интернет") -> Panel.INTERNET
                w.startsWith("громкост") -> Panel.VOLUME
                w.startsWith("батаре") -> Panel.BATTERY
                else -> Panel.MAIN
            }
            return Reply("Открываю настройки — Android разрешает переключать это только тебе.", DeviceAction.OpenSettings(panel))
        }

        Regex("^(?:позвони|набери|вызов|звони)\\s+(?:на\\s+)?(.+)").find(t)?.let {
            val who = it.groupValues[1].trim()
            val digits = who.filter { c -> c.isDigit() || c == '+' }
            val target = if (digits.length >= 5 && who.none { c -> c.isLetter() }) digits else who
            return Reply("Звоню: $target.", DeviceAction.Call(target))
        }
        Regex("^(?:напиши|отправь)\\s+(?:смс|сообщение|эсэмэску)\\s+(?:на\\s+)?(\\+?\\d[\\d()\\-]{4,}|\\S+)\\s+(.+)", RegexOption.IGNORE_CASE)
            .find(raw.trim())?.let {
                val whoRaw = it.groupValues[1]
                val who = if (whoRaw.any { c -> c.isLetter() }) normalize(whoRaw) else whoRaw.filter { c -> c.isDigit() || c == '+' }
                val body = it.groupValues[2].trim()
                return Reply("СМС отправлено.", DeviceAction.SendSms(who, body))
            }
        Regex("^(?:маршрут|проложи маршрут|как доехать|как дойти|открой карту|навигация)\\s+(?:до\\s+|к\\s+|в\\s+)?(.+)").find(t)?.let {
            return Reply("Открываю маршрут: ${it.groupValues[1]}.", DeviceAction.Navigate(it.groupValues[1]))
        }
        Regex("^(?:открой|запусти|включи)\\s+(?:приложение\\s+)?(.+)").find(t)?.let {
            return Reply("Открываю ${it.groupValues[1]}.", DeviceAction.OpenApp(it.groupValues[1]))
        }

        // Заработок
        Regex("^(доход|заработал[а]?|получил[а]?|расход|потратил[а]?)\\s+(\\d+(?:[\\s\\u00a0]\\d{3})*(?:[.,]\\d+)?)(?:\\s*(?:руб\\S*|₽|р))?(?:\\s+(?:на|за|проект|по проекту)\\s+(.+))?")
            .find(t)?.let {
                val income = Regex("^(доход|заработал|получил)").containsMatchIn(it.groupValues[1])
                val amount = parseNumber(it.groupValues[2]) ?: return Reply("Не поняла сумму.")
                val projectLower = it.groupValues[3]
                // Название проекта берём из исходной фразы, чтобы сохранить регистр.
                val project = if (projectLower.isEmpty()) "Общее"
                else raw.trim().trimEnd('.', '!').takeLast(projectLower.length).trim()
                val kind = if (income) EntryKind.INCOME else EntryKind.EXPENSE
                store.update { d -> d.copy(ledger = d.ledger + Entry(kind = kind, amount = amount, project = project, at = nowMs)) }
                return Reply("${if (income) "Доход" else "Расход"} ${formatMoney(amount)} записан в «$project».")
            }
        if (Regex("^(баланс|сколько (я )?заработал|итоги|проекты)").containsMatchIn(t)) {
            if (data.ledger.isEmpty()) return Reply("Записей пока нет. Скажи, например: «доход 3000 проект Видео».")
            val byProject = data.ledger.groupBy { e -> e.project }
                .mapValues { (_, es) -> es.sumOf { e -> if (e.kind == EntryKind.INCOME) e.amount else -e.amount } }
            return Reply("Итого: ${formatMoney(byProject.values.sum())}\n" +
                byProject.entries.joinToString("\n") { (p, v) -> "• $p: ${formatMoney(v)}" })
        }
        if (Regex("(идеи|как) (для )?заработ").containsMatchIn(t)) return Reply(IDEAS)

        // Мониторинг
        Regex("^(?:следи за|мониторь|отслеживай)\\s+(.+)").find(t)?.let {
            val q = it.groupValues[1].trim()
            store.update { d -> d.copy(watches = d.watches + Watch(query = q)) }
            return Reply("Добавила в мониторинг: «$q». Буду проверять, когда есть сеть, и пришлю уведомление, если что-то изменится.")
        }
        if (Regex("^(проверь мониторинг|что нового)").containsMatchIn(t)) {
            return Reply("Проверяю мониторинг…", online = OnlineRequest.CheckWatches)
        }

        // Поиск и свободные вопросы
        Regex("^(?:найди|поищи|загугли|что такое|кто такой|кто такая)\\s+(.+)").find(t)?.let {
            return Reply("Ищу…", online = OnlineRequest.Ask(raw.trim(), it.groupValues[1]))
        }
        return Reply("", online = OnlineRequest.Ask(raw.trim()))
    }
}
