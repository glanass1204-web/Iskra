package ru.iskra.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class KnowledgeTest {
    /** Отвечает заготовкой для первого подходящего фрагмента адреса и запоминает запросы. */
    private class FakeHttp(private val routes: List<Pair<String, String?>>) : Http {
        val calls = mutableListOf<String>()
        override fun get(url: String): String? {
            calls += url
            return routes.firstOrNull { url.contains(it.first) }?.second
        }
    }

    private val settings = Settings(city = "Казань")

    private val forecast = """
        {"current":{"temperature_2m":-3.4,"apparent_temperature":-8.1,"weather_code":71,"wind_speed_10m":4.6},
         "daily":{"weather_code":[71,3,0],"temperature_2m_max":[-1.2,2.4,5.0],"temperature_2m_min":[-6.0,-2.6,1.0],
                  "precipitation_probability_max":[80,20,0]}}
    """.trimIndent()

    @Test
    fun weatherUsesSpokenCityInAnyCase() {
        val http = FakeHttp(
            listOf(
                "name=%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B5" to """{"generationtime_ms":0.5}""", // «Москве» — не найдено
                "name=%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0" to """{"results":[{"name":"Москва","latitude":55.75,"longitude":37.62}]}""",
                "api.open-meteo.com" to forecast,
            ),
        )
        val a = Knowledge(http).answer("Какая погода в Москве", null, settings)
        assertEquals("Москва: сейчас -3°, небольшой снег, ощущается как -8°, ветер 5 м/с. Днём от -6° до -1°, вероятность осадков 80%.", a.text)
    }

    @Test
    fun weatherTomorrowUsesHomeCity() {
        val http = FakeHttp(
            listOf(
                "geocoding" to """{"results":[{"name":"Казань","latitude":55.8,"longitude":49.1}]}""",
                "api.open-meteo.com" to forecast,
            ),
        )
        val a = Knowledge(http).answer("погода завтра", null, settings)
        assertEquals("Завтра, Казань: пасмурно, от -3° до +2°, вероятность осадков 20%.", a.text)
    }

    @Test
    fun weatherAsksForCityWhenUnknown() {
        val a = Knowledge(FakeHttp(emptyList())).answer("какая погода", null, Settings())
        assertTrue(a.text.startsWith("В каком городе?"))
    }

    @Test
    fun currencyFromCentralBank() {
        val http = FakeHttp(
            listOf(
                "cbr-xml-daily" to """{"Date":"2026-10-21T11:30:00+03:00","Valute":{
                    "USD":{"CharCode":"USD","Nominal":1,"Name":"Доллар США","Value":81.2534,"Previous":80.9001},
                    "CNY":{"CharCode":"CNY","Nominal":10,"Name":"Китайский юань","Value":113.4,"Previous":113.4}}}""",
            ),
        )
        assertEquals("Курс ЦБ на 21 октября: Доллар США — 81,25 ₽, вырос на 0,35.", Knowledge(http).answer("курс доллара", null, settings).text)
        assertEquals("Курс ЦБ на 21 октября: Китайский юань — 11,34 ₽, не изменился.", Knowledge(http).answer("какой курс юаня", null, settings).text)
    }

    @Test
    fun newsFromRss() {
        val rss = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
            <item><title>Первая новость</title><link>https://lenta.ru/1</link></item>
            <item><title>Вторая новость про футбол</title><link>https://lenta.ru/2</link></item>
            </channel></rss>"""
        val k = Knowledge(FakeHttp(listOf("lenta.ru" to rss)))
        val all = k.answer("какие новости", null, settings)
        assertEquals("Главные новости:\n1. Первая новость\n2. Вторая новость про футбол", all.text)
        assertEquals("Новости про футбол:\n1. Вторая новость про футбол", k.answer("новости про футбол", null, settings).text)
    }

    @Test
    fun definitionsComeFromWikipedia() {
        val http = FakeHttp(
            listOf(
                "w/api.php" to """{"query":{"search":[{"title":"Пушкин, Александр Сергеевич"}]}}""",
                "page/summary/" to """{"extract":"Алекса́ндр Серге́евич Пу́шкин — русский поэт.","content_urls":{"mobile":{"page":"https://ru.m.wikipedia.org/wiki/Pushkin"}}}""",
            ),
        )
        val a = Knowledge(http).answer("Кто такой Пушкин", "пушкин", settings)
        assertEquals("Алекса́ндр Серге́евич Пу́шкин — русский поэт.", a.text)
        assertEquals("https://ru.m.wikipedia.org/wiki/Pushkin", a.link)
    }

    @Test
    fun generalQuestionsUseWebSearchWithFallbacks() {
        val ddg = """<div class="result results_links"><h2 class="result__title">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.ru%2Fpage&amp;rut=x">Заголовок</a></h2>
            <a class="result__snippet" href="#">Ответ из <b>поиска</b>.</a></div>"""
        val a = Knowledge(FakeHttp(listOf("duckduckgo" to ddg))).answer("когда открывается эрмитаж", null, settings)
        assertEquals("Ответ из поиска.", a.text)
        assertEquals("https://example.ru/page", a.link)

        val bing = """<ol><li class="b_algo"><h2><a href="https://bing.example/x">Т</a></h2>
            <div class="b_caption"><p>Ответ из Bing.</p></div></li></ol>"""
        assertEquals("Ответ из Bing.", Knowledge(FakeHttp(listOf("bing.com" to bing))).answer("вопрос", null, settings).text)

        // Яндекс и Google идут первыми; если они молчат или падают — следующий источник.
        val yandex = Searcher { listOf(SearchResult("Эрмитаж", "Открыт с 11:00 до 18:00.", "https://hermitage.ru")) }
        val broken = Searcher { error("капча") }
        val first = Knowledge(FakeHttp(listOf("duckduckgo" to ddg))) { listOf(broken, yandex) }.answer("когда открывается эрмитаж", null, settings)
        assertEquals("Открыт с 11:00 до 18:00.", first.text)

        val none = Knowledge(FakeHttp(emptyList())).answer("вопрос без ответа", null, settings)
        assertTrue(none.link!!.startsWith("https://yandex.ru/search/?text="))
    }

    @Test
    fun calculatorHandlesWordsAndSymbols() {
        assertEquals("Получается 100.", Calculator.tryAnswer("Сколько будет 25 умножить на 4"))
        assertEquals("Получается 100.", Calculator.tryAnswer("сколько будет 25 на 4"))
        assertEquals("Получается 14.", Calculator.tryAnswer("посчитай (3 + 4) * 2"))
        assertEquals("Получается 2,5.", Calculator.tryAnswer("5 / 2"))
        assertEquals("15% от 2000 — это 300.", Calculator.tryAnswer("15 процентов от 2000"))
        assertEquals("На ноль делить нельзя.", Calculator.tryAnswer("сколько будет 5 разделить на 0"))
        assertNull(Calculator.tryAnswer("сколько стоит доллар"))
        assertNull(Calculator.tryAnswer("сколько времени"))
    }

    @Test
    fun brainRoutesEverydayPhrases() {
        val store = Store(null)
        val brain = Brain(store)
        assertEquals("Получается 4.", brain.handle("сколько будет 2 плюс 2").text)
        assertTrue(SmallTalk.tryAnswer("подбрось монетку", "друг", random = Random(1)) in setOf("Орёл!", "Решка!"))
        assertTrue(brain.handle("расскажи анекдот").text.isNotBlank())
        brain.handle("Мой город казань")
        assertEquals("Казань", store.value.settings.city)
        assertEquals(OnlineRequest.Ask("Какая погода завтра"), brain.handle("Какая погода завтра").online)
        assertEquals(OnlineRequest.Ask("курс доллара"), brain.handle("курс доллара").online)
    }

    @Test
    fun rudeModeIsOptIn() {
        val store = Store(null)
        val brain = Brain(store)
        assertEquals(Rude.HINT, brain.handle("иди нахуй").text)
        assertEquals(Rude.ON, brain.handle("включи мат").text)
        assertTrue(store.value.settings.rudeMode)
        assertTrue(Rude.hasSwearing(brain.handle("ты охуела").text))
        // Крепкое словцо в начале не мешает командам.
        assertEquals("Добавила задачу: «купить пиво».", brain.handle("Бля, задача купить пиво").text)
        assertTrue(brain.handle("бля, что ты умеешь").text.startsWith("Вот что я умею"))
        assertTrue(Rude.hasSwearing(SmallTalk.tryAnswer("как дела", "друг", rude = true)!!))
        assertEquals(Rude.OFF, brain.handle("без мата").text)
        assertTrue(!store.value.settings.rudeMode)
        assertTrue(!Rude.hasSwearing("небо себя хуже сукно"))
        val spiced = (0 until 20).map { Rude.spice("Готово.", Random(it)) }
        assertTrue(spiced.any { Rude.hasSwearing(it) })
    }
}
