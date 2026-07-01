package uz.komment.cookiegrabber

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var status: TextView
    private lateinit var username: EditText
    private lateinit var btnSend: Button
    private var sessionid: String = ""

    private val mobileUA =
        "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        username = findViewById(R.id.username)
        status = findViewById(R.id.status)
        btnSend = findViewById(R.id.btnSend)
        web = findViewById(R.id.web)

        val cm = CookieManager.getInstance()
        cm.setAcceptCookie(true)
        cm.setAcceptThirdPartyCookies(web, true)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.userAgentString = mobileUA
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                grabCookie(false)
            }
        }

        findViewById<Button>(R.id.btnStart).setOnClickListener {
            val u = username.text.toString().trim()
            if (u.isEmpty()) {
                status.text = "Avval username yozing!"
                return@setOnClickListener
            }
            web.loadUrl("https://www.instagram.com/accounts/login/")
            status.text = "Instagram'ga @${u.removePrefix("@")} bilan kiring..."
        }

        findViewById<Button>(R.id.btnGrab).setOnClickListener { grabCookie(true) }

        findViewById<Button>(R.id.btnLogout).setOnClickListener {
            cm.removeAllCookies(null)
            cm.flush()
            sessionid = ""
            btnSend.isEnabled = false
            web.loadUrl("https://www.instagram.com/accounts/login/")
            status.text = "Tozalandi. Yangi username yozing va kiring."
        }

        btnSend.setOnClickListener { sendToTelegram() }
    }

    private fun grabCookie(manual: Boolean) {
        val cookies = CookieManager.getInstance().getCookie("https://www.instagram.com") ?: ""
        val part = cookies.split(";").map { it.trim() }
            .firstOrNull { it.startsWith("sessionid=") }
        val value = part?.substringAfter("sessionid=") ?: ""
        if (value.length > 5) {
            sessionid = value
            btnSend.isEnabled = true
            status.text = "✅ sessionid olindi! Endi 'Telegramga yubor' bosing."
        } else if (manual) {
            status.text = "❌ sessionid topilmadi. Avval Instagram'ga to'liq kiring."
        }
    }

    private fun sendToTelegram() {
        val u = username.text.toString().trim().removePrefix("@")
        if (u.isEmpty()) {
            status.text = "Username kiriting!"
            return
        }
        if (sessionid.isEmpty()) {
            status.text = "Avval 'Cookie olish' bosing!"
            return
        }
        val text = "/add $u $sessionid"
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(send, "Komment Qiroli botga yuboring"))
        status.text = "Telegram'da botni (yoki bot chatini) tanlab, yuboring."
    }
}
