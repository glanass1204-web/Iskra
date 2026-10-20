package ru.iskra.assistant

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity

/**
 * Показывает проверку «Я не робот» от Яндекса или Google. После неё браузерные cookies
 * сохраняются, и невидимый поиск Искры снова работает сам.
 */
class SearchCheckActivity : ComponentActivity() {
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent.getStringExtra(EXTRA_URL) ?: return finish()
        val hint = TextView(this).apply {
            text = "Поисковик просит подтвердить, что ты не робот. Нажми «Я не робот», потом «Готово»."
            textSize = 16f
            setPadding(32, 48, 32, 16)
        }
        val web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
            loadUrl(url)
        }
        val done = Button(this).apply {
            text = "Готово"
            setOnClickListener { finish() }
        }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                fitsSystemWindows = true
                addView(hint)
                addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
                addView(done, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            },
        )
        SearchCheck.clear()
    }

    companion object {
        const val EXTRA_URL = "url"
    }
}
