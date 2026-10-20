package ru.iskra.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.jsoup.Jsoup
import org.jsoup.parser.Parser
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

/** Загрузка страницы; в тестах подменяется заготовками. */
fun interface Http {
    fun get(url: String): String?
}

object DefaultHttp : Http {
    private const val UA = "Mozilla/5.0 (Linux; Android 15; SM-S948B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"

    override fun get(url: String): String? = try {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 7000
        conn.readTimeout = 9000
        conn.setRequestProperty("User-Agent", UA)
        conn.setRequestProperty("Accept-Language", "ru-RU,ru;q=0.9")
        if (conn.responseCode !in 200..299) {
            null
        } else {
            val charset = conn.contentType?.substringAfter("charset=", "")?.trim()?.ifEmpty { null } ?: "UTF-8"
            conn.inputStream.use { String(it.readBytes(), charset(charset)) }
        }
    } catch (e: Exception) {
        null
    }
}

data class SearchResult(val title: String, val snippet: String, val url: String)

/** Поисковик, который приложение подключает снаружи (Яндекс и Google через встроенный браузер). */
fun interface Searcher {
    fun search(query: String): List<SearchResult>
}

private val RU = Locale.forLanguageTag("ru-RU")
private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

/**
 * Поиск информации без ключей и без VPN. Только источники, которые работают в России:
 * Open-Meteo (погода), ЦБ РФ (курсы), ленты новостей, Википедия, веб-поиск.
 */
class Knowledge(
    private val http: Http = DefaultHttp,
    /** Поисковики в порядке приоритета; если все молчат — DuckDuckGo и Bing. */
    private val searchers: () -> List<Searcher> = { emptyList() },
) {
    private val json = Json { ignoreUnknownKeys = true }

    fun answer(question: String, hint: String?, settings: Settings): Answer {
        val q = normalize(question)
        return when {
            Regex("(погод|температур|дожд|снег|градус|зонтик|холодно|тепло)").containsMatchIn(q) -> weather(question, settings.city)
            Regex("курс|(сколько стоит|почем) (доллар|евро|юан)").containsMatchIn(q) -> currency(q)
            Regex("новост").containsMatchIn(q) -> news(q)
            else -> facts(hint ?: stripQuestion(question), question, settings.searchEngine)
        }
    }

    // ---------- Погода ----------

    fun weather(question: String, homeCity: String): Answer {
        val city = Regex("(?:в|во)\\s+([А-ЯЁA-Z][а-яёa-z-]+(?:[\\s-][А-ЯЁA-Z][а-яёa-z-]+)?)").find(question)?.groupValues?.get(1)
            ?: Regex("(?:в|во)\\s+([а-яё-]{3,})").find(normalize(question))?.groupValues?.get(1)?.takeIf { it !in DAY_WORDS }
            ?: homeCity.ifBlank { null }
            ?: return Answer("В каком городе? Скажи, например: «погода в Москве», или «мой город Казань», и я запомню.")
        val place = geocode(city) ?: return Answer("Не нашла город «$city». Попробуй сказать иначе.")
        val url = "https://api.open-meteo.com/v1/forecast?latitude=${place.lat}&longitude=${place.lon}" +
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m" +
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max" +
            "&timezone=auto&forecast_days=3&wind_speed_unit=ms"
        val body = http.get(url) ?: return Answer("Сервис погоды сейчас не отвечает. Попробуй чуть позже.")
        val root = json.parseToJsonElement(body).jsonObject
        val q = normalize(question)
        val dayIndex = when {
            q.contains("послезавтра") -> 2
            q.contains("завтра") -> 1
            else -> 0
        }
        val daily = root["daily"]!!.jsonObject
        fun day(key: String) = daily[key]!!.jsonArray[dayIndex].jsonPrimitive
        val max = day("temperature_2m_max").double.roundToInt()
        val min = day("temperature_2m_min").double.roundToInt()
        val rain = day("precipitation_probability_max").intOrNull
        val sky = describeWeather(day("weather_code").int)
        val rainText = rain?.let { ", вероятность осадков $it%" } ?: ""
        val text = if (dayIndex == 0) {
            val cur = root["current"]!!.jsonObject
            val t = cur["temperature_2m"]!!.jsonPrimitive.double.roundToInt()
            val feels = cur["apparent_temperature"]!!.jsonPrimitive.double.roundToInt()
            val wind = cur["wind_speed_10m"]!!.jsonPrimitive.double.roundToInt()
            val now = describeWeather(cur["weather_code"]!!.jsonPrimitive.int)
            "${place.name}: сейчас ${deg(t)}, $now, ощущается как ${deg(feels)}, ветер $wind м/с. " +
                "Днём от ${deg(min)} до ${deg(max)}$rainText."
        } else {
            val label = if (dayIndex == 1) "Завтра" else "Послезавтра"
            "$label, ${place.name}: $sky, от ${deg(min)} до ${deg(max)}$rainText."
        }
        return Answer(text)
    }

    private data class Place(val name: String, val lat: Double, val lon: Double)

    /** «в Москве» → Москва: перебираем падежные окончания, пока геокодер не узнает город. */
    private fun geocode(spoken: String): Place? {
        val w = spoken.trim()
        val candidates = linkedSetOf(w)
        if (w.length > 3) {
            val base = w.dropLast(1)
            when (w.last().lowercaseChar()) {
                'е' -> { candidates += base + "а"; candidates += base; candidates += base + "ь"; candidates += base + "я" }
                'и' -> { candidates += base + "ь"; candidates += base + "а"; candidates += base + "я" }
                'у', 'ю' -> { candidates += base + "а"; candidates += base + "я" }
                else -> candidates += base
            }
            if (w.endsWith("ом", ignoreCase = true) || w.endsWith("ём", ignoreCase = true)) candidates += w.dropLast(2)
        }
        for (name in candidates) {
            val body = http.get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&format=json&name=" + enc(name)) ?: continue
            val first = (json.parseToJsonElement(body).jsonObject["results"] as? JsonArray)?.firstOrNull()?.jsonObject ?: continue
            return Place(
                first["name"]!!.jsonPrimitive.content,
                first["latitude"]!!.jsonPrimitive.double,
                first["longitude"]!!.jsonPrimitive.double,
            )
        }
        return null
    }

    // ---------- Курсы валют ЦБ ----------

    fun currency(q: String): Answer {
        val code = CURRENCIES.entries.firstOrNull { (word, _) -> q.contains(word) }?.value ?: "USD"
        val body = http.get("https://www.cbr-xml-daily.ru/daily_json.js") ?: return Answer("Не получилось получить курс ЦБ. Попробуй позже.")
        val root = json.parseToJsonElement(body).jsonObject
        val v = root["Valute"]?.jsonObject?.get(code)?.jsonObject ?: return Answer("ЦБ не публикует курс этой валюты.")
        val nominal = v["Nominal"]!!.jsonPrimitive.int
        val value = v["Value"]!!.jsonPrimitive.double / nominal
        val prev = v["Previous"]?.jsonPrimitive?.doubleOrNull?.div(nominal)
        val date = root["Date"]?.jsonPrimitive?.contentOrNull?.take(10)?.let {
            LocalDate.parse(it).format(DateTimeFormatter.ofPattern("d MMMM", RU))
        }
        val name = v["Name"]!!.jsonPrimitive.content
        val trend = prev?.let {
            val diff = value - it
            when {
                diff > 0.005 -> ", вырос на ${money(diff)}"
                diff < -0.005 -> ", снизился на ${money(-diff)}"
                else -> ", не изменился"
            }
        } ?: ""
        return Answer("Курс ЦБ${date?.let { " на $it" } ?: ""}: $name — ${money(value)} ₽$trend.")
    }

    // ---------- Новости ----------

    fun news(q: String): Answer {
        val topic = Regex("новост\\S*\\s+(?:про|о|об|по)\\s+(.+)").find(q)?.groupValues?.get(1)?.trim()
        val items = FEEDS.asSequence().mapNotNull { http.get(it) }.map { parseRss(it) }.firstOrNull { it.isNotEmpty() }
            ?: return Answer("Ленты новостей сейчас не отвечают. Попробуй позже.")
        val chosen = if (topic == null) items else {
            val stem = topic.take(maxOf(4, topic.length - 2))
            items.filter { normalize(it.first).contains(stem) }
        }
        if (chosen.isEmpty()) return facts("новости $topic")
        val head = if (topic == null) "Главные новости:" else "Новости про $topic:"
        return Answer(head + "\n" + chosen.take(5).mapIndexed { i, (title, _) -> "${i + 1}. $title" }.joinToString("\n"), chosen.first().second)
    }

    internal fun parseRss(xml: String): List<Pair<String, String>> =
        Jsoup.parse(xml, "", Parser.xmlParser()).select("item").mapNotNull { item ->
            val title = item.selectFirst("title")?.text()?.trim().orEmpty()
            val link = item.selectFirst("link")?.text()?.trim().orEmpty()
            if (title.isEmpty()) null else title to link
        }

    // ---------- Факты: Википедия и веб-поиск ----------

    fun facts(query: String, question: String = query, engine: String = "yandex"): Answer {
        val q = query.trim().trimEnd('?', '.', '!')
        if (q.isEmpty()) return Answer("Что найти?")
        // Сначала поисковики (Яндекс, Google), затем Википедия.
        val web = webSearch(question.trim().ifEmpty { q }).firstOrNull()?.let { result ->
            Answer(
                "Нашла страницу «${result.title}», но не могу подтвердить, что она отвечает на вопрос. Открой источник по ссылке.",
                result.url,
            )
        }
        return web ?: wikipedia(q) ?: if (engine == "google") {
            Answer("Не нашла быстрого ответа. Открой поиск Google по ссылке.", "https://www.google.com/search?hl=ru&q=" + enc(q))
        } else {
            Answer("Не нашла быстрого ответа. Открой поиск Яндекса по ссылке.", yandexLink(q))
        }
    }

    fun wikipedia(query: String): Answer? {
        val search = http.get(
            "https://ru.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch=" + enc(query),
        ) ?: return null
        val title = json.parseToJsonElement(search).jsonObject["query"]?.jsonObject?.get("search")?.jsonArray
            ?.firstOrNull()?.jsonObject?.get("title")?.jsonPrimitive?.content ?: return null
        val summary = http.get("https://ru.wikipedia.org/api/rest_v1/page/summary/" + enc(title.replace(' ', '_')).replace("+", "%20"))
            ?: return null
        val obj = json.parseToJsonElement(summary).jsonObject
        val extract = obj["extract"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() } ?: return null
        val url = (obj["content_urls"] as? JsonObject)?.get("mobile")?.jsonObject?.get("page")?.jsonPrimitive?.contentOrNull
        return Answer(shorten(extract), url)
    }

    /** Веб-поиск: подключённые поисковики по приоритету, затем DuckDuckGo и Bing. */
    fun webSearch(query: String): List<SearchResult> {
        for (searcher in searchers()) {
            val found = try { searcher.search(query) } catch (e: Exception) { emptyList() }
            if (found.isNotEmpty()) return found
        }
        http.get("https://html.duckduckgo.com/html/?kl=ru-ru&q=" + enc(query))?.let { parseDuckDuckGo(it) }?.takeIf { it.isNotEmpty() }?.let { return it }
        http.get("https://www.bing.com/search?setlang=ru&cc=RU&q=" + enc(query))?.let { parseBing(it) }?.takeIf { it.isNotEmpty() }?.let { return it }
        return emptyList()
    }

    internal fun parseDuckDuckGo(html: String): List<SearchResult> =
        Jsoup.parse(html).select("div.result").mapNotNull { r ->
            if (r.hasClass("result--ad")) return@mapNotNull null
            val a = r.selectFirst("a.result__a") ?: return@mapNotNull null
            val snippet = r.selectFirst(".result__snippet")?.text()?.trim().orEmpty()
            if (snippet.isEmpty()) return@mapNotNull null
            SearchResult(a.text().trim(), snippet, unwrapDuckLink(a.attr("href")))
        }.take(3)

    internal fun parseBing(html: String): List<SearchResult> =
        Jsoup.parse(html).select("li.b_algo").mapNotNull { r ->
            val a = r.selectFirst("h2 a") ?: return@mapNotNull null
            val snippet = (r.selectFirst(".b_caption p") ?: r.selectFirst("p"))?.text()?.trim().orEmpty()
            if (snippet.isEmpty()) return@mapNotNull null
            SearchResult(a.text().trim(), snippet, a.attr("href"))
        }.take(3)

    private fun unwrapDuckLink(href: String): String {
        val uddg = Regex("[?&]uddg=([^&]+)").find(href)?.groupValues?.get(1)
        return if (uddg != null) URLDecoder.decode(uddg, "UTF-8") else if (href.startsWith("//")) "https:$href" else href
    }

    companion object {
        private val DAY_WORDS = setOf("завтра", "послезавтра", "сегодня")

        private val FEEDS = listOf(
            "https://lenta.ru/rss/news",
            "https://ria.ru/export/rss2/archive/index.xml",
            "https://tass.ru/rss/v2.xml",
        )

        private val CURRENCIES = linkedMapOf(
            "доллар" to "USD", "евро" to "EUR", "юан" to "CNY", "фунт" to "GBP", "иен" to "JPY", "йен" to "JPY",
            "тенге" to "KZT", "белорус" to "BYN", "гривн" to "UAH", "лир" to "TRY", "франк" to "CHF", "дирхам" to "AED",
            "сом" to "KGS", "драм" to "AMD", "лари" to "GEL",
        )

        fun yandexLink(q: String) = "https://yandex.ru/search/?text=" + enc(q)

        fun stripQuestion(q: String) = q.trim()
            .replace(Regex("^(?i)(искра[,]?\\s+)?(найди|поищи|загугли|скажи|подскажи|расскажи)(\\s+мне)?\\s+"), "")
            .trim()

        private fun deg(t: Int) = (if (t > 0) "+$t" else "$t") + "°"

        private fun money(v: Double) = String.format(RU, "%.2f", v)

        /** Первые предложения — чтобы ответ можно было комфортно прослушать. */
        fun shorten(text: String, limit: Int = 420): String {
            if (text.length <= limit) return text
            val cut = text.take(limit)
            val end = cut.lastIndexOf(". ")
            return if (end > 80) cut.take(end + 1) else "$cut…"
        }

        fun describeWeather(code: Int) = when (code) {
            0 -> "ясно"
            1 -> "преимущественно ясно"
            2 -> "переменная облачность"
            3 -> "пасмурно"
            45, 48 -> "туман"
            51, 53, 55 -> "морось"
            56, 57 -> "ледяная морось"
            61 -> "небольшой дождь"
            63 -> "дождь"
            65 -> "сильный дождь"
            66, 67 -> "ледяной дождь"
            71 -> "небольшой снег"
            73 -> "снег"
            75 -> "сильный снег"
            77 -> "снежная крупа"
            80, 81 -> "ливень"
            82 -> "сильный ливень"
            85, 86 -> "снегопад"
            95 -> "гроза"
            96, 99 -> "гроза с градом"
            else -> "осадки"
        }
    }
}
