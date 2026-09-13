/* MPL-2.0 */
package org.mozilla.fenix.settings.trustpanel

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import mozilla.components.browser.engine.gecko.GeckoEngineSession
import mozilla.components.concept.engine.EngineSession
import org.json.JSONObject

/** Current tab only. Closing the panel stops requests and drops the snapshot. */
@Composable
internal fun RufoxProtectionSummary(engine: EngineSession?, onOpen: () -> Unit) {
    var summary by remember(engine) { mutableStateOf("Получение состояния…") }
    DisposableEffect(engine) {
        val handler = Handler(Looper.getMainLooper())
        var active = true
        val poll = object : Runnable {
            override fun run() {
                val gecko = engine as? GeckoEngineSession
                if (gecko == null) {
                    summary = "Состояние проверки недоступно"
                    return
                }
                gecko.requestRufoxProtection { raw ->
                    if (active) {
                        summary = try {
                            val status = JSONObject(raw ?: "{}")
                            when (status.optString("state")) {
                                "blocked" -> "Заблокировано запросов: ${status.optInt("blocked")}. " +
                                    "Доменов: ${if (status.optBoolean("truncated")) "не менее " else ""}${status.optInt("blockedDomains")}"
                                "exception" -> "Действует пользовательское разрешение"
                                "allowed" -> if (status.optString("badge") == "CT") {
                                    "CT · SCT страницы проверен"
                                } else {
                                    "Сертификаты запросов прошли проверку CAnttRUst"
                                }
                                "unavailable" -> "? · Проверка сертификата страницы недоступна"
                                "unobserved" -> "Запросов с этим УЦ не обнаружено"
                                else -> "Состояние проверки недоступно"
                            }
                        } catch (_: Exception) {
                            "Состояние проверки недоступно"
                        }
                        handler.postDelayed(this, 1000)
                    }
                }
            }
        }
        handler.post(poll)
        onDispose {
            active = false
            handler.removeCallbacks(poll)
        }
    }
    TextButton(onClick = onOpen) {
        Column {
            Text("Защита сертификатов · CAnttRUst")
            Text(summary)
            Text("Посмотреть домены этой страницы")
        }
    }
}
