package br.com.tabcontrol.bateria

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.roundToInt

/** Envia a bateria automaticamente; o Android agenda as execuções em segundo plano. */
class BatterySyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : Worker(appContext, workerParams) {

    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
        val baseUrl = prefs.getString(MainActivity.KEY_SERVER, null)?.trim()?.trimEnd('/')
        val tabletCode = prefs.getString(MainActivity.KEY_CODE, null)?.trim()
        val apiToken = prefs.getString(MainActivity.KEY_TOKEN, null)?.trim()

        if (baseUrl.isNullOrBlank() || tabletCode.isNullOrBlank() || apiToken.isNullOrBlank()) {
            prefs.edit().putString(MainActivity.KEY_LAST_RESULT, "Monitoramento ainda não foi configurado.").apply()
            return Result.failure()
        }

        val level = readBatteryLevel()
        if (level == null) {
            prefs.edit().putString(MainActivity.KEY_LAST_RESULT, "Não foi possível ler a bateria deste aparelho.").apply()
            return Result.retry()
        }

        var connection: HttpURLConnection? = null
        try {
            val url = URL("$baseUrl/api/bateria")
            connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 8_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Accept", "application/json")
                setRequestProperty("X-TabControl-Token", apiToken)
            }

            val payload = JSONObject()
                .put("codigo", tabletCode)
                .put("bateria", level)
                .toString()
                .toByteArray(Charsets.UTF_8)
            connection.outputStream.use { it.write(payload) }

            val httpCode = connection.responseCode
            val responseStream = if (httpCode in 200..299) connection.inputStream else connection.errorStream
            val responseText = responseStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            val response = try { JSONObject(responseText) } catch (_: Exception) { JSONObject() }
            val ok = httpCode in 200..299 && response.optBoolean("ok", true)
            val message = response.optString("msg", "Resposta HTTP $httpCode")

            if (ok) {
                prefs.edit()
                    .putInt(MainActivity.KEY_LAST_BATTERY, level)
                    .putLong(MainActivity.KEY_LAST_SYNC, System.currentTimeMillis())
                    .putString(MainActivity.KEY_LAST_RESULT, "Sincronização concluída: $message")
                    .apply()
                return Result.success()
            }

            prefs.edit().putString(MainActivity.KEY_LAST_RESULT, "Falha no envio: $message (HTTP $httpCode)").apply()
            return if (httpCode >= 500) Result.retry() else Result.failure()
        } catch (e: Exception) {
            prefs.edit()
                .putString(MainActivity.KEY_LAST_RESULT, "Sem conexão com a API: ${e.localizedMessage ?: e.javaClass.simpleName}")
                .apply()
            return Result.retry()
        } finally {
            connection?.disconnect()
        }
    }

    private fun readBatteryLevel(): Int? {
        val intentBateria = applicationContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        if (intentBateria != null) {
            val nivel = intentBateria.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val escala = intentBateria.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            if (nivel >= 0 && escala > 0) return ((nivel * 100f) / escala).roundToInt().coerceIn(0, 100)
        }
        val manager = applicationContext.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val capacidade = manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        return capacidade.takeIf { it in 0..100 }
    }
}
