package ru.iskra.core

import java.time.Duration
import java.time.LocalDateTime

private val WORD_NUMBERS = mapOf(
    "один" to 1, "одну" to 1, "одна" to 1, "два" to 2, "две" to 2, "три" to 3, "четыре" to 4,
    "пять" to 5, "шесть" to 6, "семь" to 7, "восемь" to 8, "девять" to 9, "десять" to 10,
    "пятнадцать" to 15, "двадцать" to 20, "тридцать" to 30, "сорок" to 40, "пятьдесят" to 50,
)

internal fun parseNumber(token: String?): Double? {
    if (token == null) return null
    return token.replace(',', '.').replace(Regex("[\\s\\u00a0]"), "").toDoubleOrNull()
        ?: WORD_NUMBERS[token]?.toDouble()
}

data class When(val at: LocalDateTime, val rest: String)

private val HALF_HOUR = Regex("через\\s+(полчаса|пол часа)")
private val RELATIVE = Regex("через\\s+(?:(\\S+)\\s+)?(секунд\\S*|минут\\S*|час\\S*|дн\\S*|день)")
private val ABSOLUTE = Regex("(завтра\\s+)?в\\s+(\\d{1,2})(?:[:.](\\d{2}))?(?:\\s*(утра|дня|вечера|ночи))?")

/** Длительность для таймера: «на 5 минут», «на полчаса», «на 90 секунд». */
fun parseDuration(text: String): Duration? {
    if (text.contains("полчаса") || text.contains("пол часа")) return Duration.ofMinutes(30)
    val m = Regex("(?:на\\s+)?(?:(\\S+)\\s+)?(секунд\\S*|минут\\S*|час\\S*)").find(text) ?: return null
    val n = m.groupValues[1].ifEmpty { null }?.let { parseNumber(it) } ?: 1.0
    val unit = m.groupValues[2]
    val seconds = when {
        unit.startsWith("секунд") -> n
        unit.startsWith("минут") -> n * 60
        else -> n * 3600
    }
    return Duration.ofSeconds(seconds.toLong()).takeIf { !it.isZero }
}

/** Разбирает «через 10 минут», «через час», «в 18:30», «завтра в 9», «в 7 вечера». */
fun parseWhen(text: String, now: LocalDateTime): When? {
    HALF_HOUR.find(text)?.let { return When(now.plusMinutes(30), text.replace(it.value, "")) }

    RELATIVE.find(text)?.let { m ->
        val n = m.groupValues[1].ifEmpty { null }?.let { parseNumber(it) } ?: 1.0
        val unit = m.groupValues[2]
        val seconds = when {
            unit.startsWith("секунд") -> n
            unit.startsWith("минут") -> n * 60
            unit.startsWith("час") -> n * 3600
            else -> n * 86400
        }
        return When(now.plusSeconds(seconds.toLong()), text.replace(m.value, ""))
    }

    ABSOLUTE.find(text)?.let { m ->
        var h = m.groupValues[2].toInt()
        val min = m.groupValues[3].ifEmpty { "0" }.toInt()
        val part = m.groupValues[4]
        if (part == "вечера" || (part == "дня" && h < 12)) h = if (h == 12) 12 else h + 12
        if (part == "ночи" && h == 12) h = 0
        if (h > 23 || min > 59) return null
        var at = now.withHour(h).withMinute(min).withSecond(0).withNano(0)
        if (m.groupValues[1].isNotEmpty()) at = at.plusDays(1)
        else if (!at.isAfter(now)) at = at.plusDays(1)
        return When(at, text.replace(m.value, ""))
    }
    return null
}

/** «в 7 утра», «на 6:30» — время для будильника. */
fun parseClock(text: String): Pair<Int, Int>? {
    val m = Regex("(?:в|на)\\s+(\\d{1,2})(?:[:.](\\d{2}))?(?:\\s*(утра|дня|вечера|ночи))?").find(text) ?: return null
    var h = m.groupValues[1].toInt()
    val min = m.groupValues[2].ifEmpty { "0" }.toInt()
    val part = m.groupValues[3]
    if (part == "вечера" || (part == "дня" && h < 12)) h = if (h == 12) 12 else h + 12
    if (h > 23 || min > 59) return null
    return h to min
}
