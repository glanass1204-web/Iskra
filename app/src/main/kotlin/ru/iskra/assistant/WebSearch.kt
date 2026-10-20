package ru.iskra.assistant

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import ru.iskra.core.SearchResult
import ru.iskra.core.Searcher
import java.net.URLEncoder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

enum class SearchEngine(val id: String, val label: String) {
    YANDEX("yandex", "Яндекс"),
    GOOGLE("google", "Google");

    fun url(query: String): String {
        val q = URLEncoder.encode(query, "UTF-8")
        return when (this) {
            YANDEX -> "https://yandex.ru/search/?lr=225&text=$q"
            GOOGLE -> "https://www.google.com/search?hl=ru&gl=ru&q=$q"
        }
    }

    companion object {
        fun byId(id: String) = entries.firstOrNull { it.id == id } ?: YANDEX
    }
}

/** Если поисковик попросил доказать, что ты не робот, — адрес проверки. Экран чата её показывает. */
object SearchCheck {
    private val _pending = MutableStateFlow<String?>(null)
    val pending: StateFlow<String?> = _pending.asStateFlow()
    fun request(url: String) { _pending.value = url }
    fun clear() { _pending.value = null }
}

/**
 * Поиск в Яндексе или Google через невидимый встроенный браузер: страницы открываются
 * как в обычном Chrome на телефоне, а скрипт serp.js достаёт из выдачи ответы.
 * Вызывать не из главного потока.
 */
class WebViewSearcher(private val context: Context, private val engine: SearchEngine) : Searcher {
    private val main = Handler(Looper.getMainLooper())
    private val json = Json { ignoreUnknownKeys = true }
    private val script by lazy { context.assets.open("serp.js").bufferedReader().use { it.readText() } }

    @SuppressLint("SetJavaScriptEnabled")
    override fun search(query: String): List<SearchResult> {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Поиск нельзя вызывать из главного потока" }
        val url = engine.url(query)
        val latch = CountDownLatch(1)
        var results = emptyList<SearchResult>()
        var view: WebView? = null

        main.post {
            val web = WebView(context.applicationContext)
            view = web
            web.settings.javaScriptEnabled = true
            web.settings.domStorageEnabled = true
            web.settings.blockNetworkImage = true
            var attempts = 0
            fun extract() {
                if (latch.count == 0L) return
                web.evaluateJavascript(script) { raw ->
                    if (latch.count == 0L) return@evaluateJavascript
                    val parsed = parse(raw)
                    when {
                        parsed.first -> { SearchCheck.request(url); latch.countDown() }
                        parsed.second.isNotEmpty() -> { results = parsed.second; latch.countDown() }
                        // Выдача иногда дорисовывается после загрузки — пробуем ещё пару раз.
                        ++attempts < 4 -> main.postDelayed({ extract() }, 900)
                        else -> latch.countDown()
                    }
                }
            }
            web.webViewClient = object : WebViewClient() {
                override fun onPageFinished(v: WebView, loaded: String) {
                    main.postDelayed({ extract() }, 600)
                }
            }
            web.loadUrl(url)
        }

        latch.await(15, TimeUnit.SECONDS)
        main.post {
            view?.stopLoading()
            view?.destroy()
        }
        return results
    }

    private fun parse(raw: String?): Pair<Boolean, List<SearchResult>> = try {
        val obj = json.parseToJsonElement(raw ?: "null").jsonObject
        val captcha = obj["captcha"]?.jsonPrimitive?.boolean ?: false
        val items = obj["items"]?.jsonArray.orEmpty().map {
            val o = it.jsonObject
            SearchResult(o["t"]!!.jsonPrimitive.content, o["s"]!!.jsonPrimitive.content, o["u"]!!.jsonPrimitive.content)
        }
        captcha to items
    } catch (e: Exception) {
        false to emptyList()
    }
}
