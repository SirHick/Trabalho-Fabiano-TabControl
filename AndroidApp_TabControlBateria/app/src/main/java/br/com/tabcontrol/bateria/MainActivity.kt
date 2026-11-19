package br.com.tabcontrol.bateria

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.BatteryManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import org.json.JSONArray
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

class MainActivity : Activity() {
    companion object {
        const val PREFS = "tabcontrol_monitor"
        const val KEY_SERVER = "server_url"
        const val KEY_CODE = "tablet_code"
        const val KEY_TOKEN = "battery_api_token"
        const val KEY_LAST_BATTERY = "last_battery"
        const val KEY_LAST_SYNC = "last_sync_ms"
        const val KEY_LAST_RESULT = "last_result"
        private const val UNIQUE_PERIODIC_WORK = "tabcontrol-battery-periodic"
        private const val UNIQUE_INITIAL_WORK = "tabcontrol-battery-initial"
    }

    private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var setupPanel: LinearLayout
    private lateinit var monitorPanel: LinearLayout
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var tabletSpinner: Spinner
    private lateinit var setupStatusView: TextView
    private lateinit var monitorStatusView: TextView
    private lateinit var batteryView: TextView
    private lateinit var pairedTabletView: TextView
    private val tabletCodes = mutableListOf<String>()

    private val refreshMonitor = object : Runnable {
        override fun run() {
            if (::monitorPanel.isInitialized && monitorPanel.visibility == View.VISIBLE) {
                atualizarPainelMonitoramento()
            }
            handler.postDelayed(this, 10_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.rgb(243, 246, 250))
            isFillViewport = true
        }
        val coluna = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(28), dp(22), dp(28))
        }
        scroll.addView(coluna)

        coluna.addView(TextView(this).apply {
            text = "TabControl"
            textSize = 30f
            setTextColor(Color.rgb(20, 52, 88))
            setTypeface(typeface, Typeface.BOLD)
        })
        coluna.addView(TextView(this).apply {
            text = "Monitoramento automático da bateria"
            textSize = 16f
            setTextColor(Color.rgb(82, 98, 119))
            setPadding(0, dp(4), 0, dp(20))
        })

        setupPanel = criarCartao()
        monitorPanel = criarCartao()
        criarPainelConfiguracao()
        criarPainelMonitoramento()
        coluna.addView(setupPanel, larguraCompleta())
        coluna.addView(monitorPanel, larguraCompleta())

        coluna.addView(TextView(this).apply {
            text = "O vínculo é feito uma única vez por aparelho. Depois disso, o nível é enviado em segundo plano, sem digitar a porcentagem nem apertar um botão a cada leitura."
            textSize = 12f
            setTextColor(Color.rgb(98, 111, 129))
            setPadding(dp(2), dp(16), dp(2), 0)
        })

        setContentView(scroll)
        mostrarPainelCorreto()

        if (prefs.getString(KEY_CODE, null).isNullOrBlank() ||
            prefs.getString(KEY_TOKEN, null).isNullOrBlank()) {
            carregarTablets()
        } else {
            agendarMonitoramento()
        }
        handler.post(refreshMonitor)
    }

    private fun criarPainelConfiguracao() {
        setupPanel.addView(TextView(this).apply {
            text = "Configuração inicial"
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.rgb(20, 52, 88))
        })
        setupPanel.addView(TextView(this).apply {
            text = "Selecione o cadastro que corresponde fisicamente a este tablet. Isso evita registrar a bateria no equipamento errado."
            textSize = 14f
            setTextColor(Color.rgb(82, 98, 119))
            setPadding(0, dp(6), 0, dp(12))
        })

        setupPanel.addView(rotulo("Endereço do servidor TabControl"))
        serverInput = EditText(this).apply {
            setSingleLine(true)
            hint = "http://10.0.2.2:8000"
            setText(prefs.getString(KEY_SERVER, "http://10.0.2.2:8000"))
            textSize = 15f
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
        }
        setupPanel.addView(serverInput, campoParams())

        setupPanel.addView(rotulo("Token de segurança da API"))
        tokenInput = EditText(this).apply {
            setSingleLine(true)
            hint = "Cole o mesmo token configurado no .env do servidor"
            setText(prefs.getString(KEY_TOKEN, ""))
            textSize = 15f
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        setupPanel.addView(tokenInput, campoParams())
        setupPanel.addView(TextView(this).apply {
            text = "O token é fornecido pelo administrador do servidor. Ele protege o envio da bateria e não é a senha do MySQL."
            textSize = 12f
            setTextColor(Color.rgb(98, 111, 129))
            setPadding(0, 0, 0, dp(8))
        })

        setupPanel.addView(rotulo("Tablet cadastrado no banco"))
        tabletSpinner = Spinner(this)
        setupPanel.addView(tabletSpinner, campoParams())

        setupPanel.addView(botao("Buscar cadastros no banco") { carregarTablets() }, botaoParams())
        setupPanel.addView(botao("Ativar monitoramento automático") { ativarMonitoramento() }, botaoParams())

        setupStatusView = TextView(this).apply {
            text = "Buscando tablets cadastrados..."
            textSize = 13f
            setTextColor(Color.rgb(57, 72, 91))
            setPadding(0, dp(10), 0, 0)
        }
        setupPanel.addView(setupStatusView)
    }

    private fun criarPainelMonitoramento() {
        monitorPanel.addView(TextView(this).apply {
            text = "Monitoramento ativo"
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.rgb(20, 52, 88))
        })
        pairedTabletView = TextView(this).apply {
            text = "Tablet vinculado: —"
            textSize = 15f
            setTextColor(Color.rgb(57, 72, 91))
            setPadding(0, dp(8), 0, 0)
        }
        monitorPanel.addView(pairedTabletView)

        batteryView = TextView(this).apply {
            text = "--%"
            textSize = 48f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.rgb(14, 115, 91))
            setPadding(0, dp(12), 0, 0)
        }
        monitorPanel.addView(batteryView)
        monitorPanel.addView(TextView(this).apply {
            text = "Nível detectado neste aparelho. O envio ao servidor é automático."
            textSize = 13f
            setTextColor(Color.rgb(98, 111, 129))
            setPadding(0, 0, 0, dp(12))
        })
        monitorStatusView = TextView(this).apply {
            text = "Aguardando a primeira sincronização..."
            textSize = 13f
            setTextColor(Color.rgb(57, 72, 91))
        }
        monitorPanel.addView(monitorStatusView)
        monitorPanel.addView(botao("Configurar / vincular outro tablet") {
            mostrarConfiguracao()
            carregarTablets()
        }, botaoParams())
    }

    private fun carregarTablets() {
        val baseUrl = normalizarUrl(serverInput.text.toString())
        if (baseUrl == null) {
            setupStatusView.text = "Informe um endereço válido começando com http:// ou https://."
            return
        }
        setupStatusView.text = "Consultando os tablets cadastrados..."
        executor.execute {
            var conexao: HttpURLConnection? = null
            try {
                conexao = (URL("$baseUrl/api/tablets").openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 5_000
                    readTimeout = 5_000
                    setRequestProperty("Accept", "application/json")
                }
                val codigoHttp = conexao.responseCode
                if (codigoHttp !in 200..299) throw IOException("O servidor respondeu HTTP $codigoHttp")
                val corpo = conexao.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                val json = JSONArray(corpo)
                val encontrados = mutableListOf<String>()
                for (i in 0 until json.length()) {
                    val tablet = json.optJSONObject(i) ?: continue
                    val codigo = tablet.optString("codigo", "").trim()
                    if (codigo.isNotEmpty()) encontrados.add(codigo)
                }
                encontrados.sortBy { it.lowercase(Locale.ROOT) }
                runOnUiThread {
                    tabletCodes.clear()
                    tabletCodes.addAll(encontrados)
                    val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, tabletCodes)
                    adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
                    tabletSpinner.adapter = adapter
                    val vinculado = prefs.getString(KEY_CODE, null)
                    val indice = tabletCodes.indexOfFirst { it.equals(vinculado, ignoreCase = true) }
                    if (indice >= 0) tabletSpinner.setSelection(indice)
                    setupStatusView.text = if (tabletCodes.isEmpty()) {
                        "Nenhum tablet foi retornado. Cadastre um tablet no TabControl e busque novamente."
                    } else {
                        "${tabletCodes.size} tablet(s) encontrado(s). Escolha o cadastro correspondente a este aparelho."
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    setupStatusView.text = "Não foi possível consultar a API. Confira se o Servidor.py está rodando e se o endereço está correto. Detalhe: ${e.localizedMessage ?: e.javaClass.simpleName}"
                }
            } finally {
                conexao?.disconnect()
            }
        }
    }

    private fun ativarMonitoramento() {
        val baseUrl = normalizarUrl(serverInput.text.toString())
        if (baseUrl == null) {
            setupStatusView.text = "Informe um endereço válido começando com http:// ou https://."
            return
        }
        val token = tokenInput.text.toString().trim()
        if (token.length < 32) {
            setupStatusView.text = "Informe o token de segurança fornecido pelo administrador (mínimo de 32 caracteres)."
            return
        }
        val codigo = tabletCodes.getOrNull(tabletSpinner.selectedItemPosition)
        if (codigo.isNullOrBlank()) {
            setupStatusView.text = "Nenhum tablet selecionado. Clique em 'Buscar cadastros no banco'."
            return
        }

        prefs.edit()
            .putString(KEY_SERVER, baseUrl)
            .putString(KEY_CODE, codigo)
            .putString(KEY_TOKEN, token)
            .apply()
        agendarMonitoramento()
        mostrarPainelCorreto()
        atualizarPainelMonitoramento()
    }

    private fun agendarMonitoramento() {
        val restricoes = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        // Envio imediato para validar o vínculo; a rotina periódica faz as próximas leituras.
        val imediato = OneTimeWorkRequest.Builder(BatterySyncWorker::class.java)
            .setConstraints(restricoes)
            .build()
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            UNIQUE_INITIAL_WORK,
            ExistingWorkPolicy.REPLACE,
            imediato
        )

        // WorkManager respeita as otimizações de energia do Android; o intervalo real pode variar.
        val periodico = PeriodicWorkRequest.Builder(
            BatterySyncWorker::class.java, 15, TimeUnit.MINUTES
        ).setConstraints(restricoes).build()
        WorkManager.getInstance(applicationContext).enqueueUniquePeriodicWork(
            UNIQUE_PERIODIC_WORK,
            ExistingPeriodicWorkPolicy.UPDATE,
            periodico
        )
    }

    private fun atualizarPainelMonitoramento() {
        val codigo = prefs.getString(KEY_CODE, null) ?: return
        pairedTabletView.text = "Tablet vinculado: $codigo"
        val local = lerNivelBateria()
        batteryView.text = if (local == null) "--%" else "$local%"

        val ultimoNivel = prefs.getInt(KEY_LAST_BATTERY, -1)
        val ultimaHora = prefs.getLong(KEY_LAST_SYNC, 0L)
        val ultimoResultado = prefs.getString(KEY_LAST_RESULT, "Aguardando a primeira sincronização...")
        val dataHora = if (ultimaHora > 0L) {
            SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale("pt", "BR")).format(Date(ultimaHora))
        } else {
            "ainda não enviado"
        }
        monitorStatusView.text = buildString {
            append("Última bateria enviada: ")
            append(if (ultimoNivel in 0..100) "$ultimoNivel%" else "—")
            append("\nÚltimo envio: ")
            append(dataHora)
            append("\n")
            append(ultimoResultado)
            append("\n\nO envio automático ocorre aproximadamente a cada 15 minutos, quando o Android e a rede permitem.")
        }
    }

    private fun mostrarPainelCorreto() {
        val configurado = !prefs.getString(KEY_CODE, null).isNullOrBlank() &&
            !prefs.getString(KEY_TOKEN, null).isNullOrBlank()
        setupPanel.visibility = if (configurado) View.GONE else View.VISIBLE
        monitorPanel.visibility = if (configurado) View.VISIBLE else View.GONE
        if (configurado && ::monitorPanel.isInitialized) atualizarPainelMonitoramento()
    }

    private fun mostrarConfiguracao() {
        setupPanel.visibility = View.VISIBLE
        monitorPanel.visibility = View.GONE
        serverInput.setText(prefs.getString(KEY_SERVER, "http://10.0.2.2:8000"))
        tokenInput.setText(prefs.getString(KEY_TOKEN, ""))
    }

    private fun lerNivelBateria(): Int? {
        val intentBateria = registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        if (intentBateria != null) {
            val nivel = intentBateria.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val escala = intentBateria.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            if (nivel >= 0 && escala > 0) return ((nivel * 100f) / escala).roundToInt().coerceIn(0, 100)
        }
        val manager = getSystemService(BATTERY_SERVICE) as BatteryManager
        val capacidade = manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        return capacidade.takeIf { it in 0..100 }
    }

    private fun normalizarUrl(valor: String): String? {
        val url = valor.trim().trimEnd('/')
        return if (url.startsWith("http://") || url.startsWith("https://")) url else null
    }

    private fun criarCartao() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(18))
        background = GradientDrawable().apply {
            setColor(Color.WHITE)
            cornerRadius = dp(18).toFloat()
            setStroke(dp(1), Color.rgb(225, 231, 239))
        }
    }

    private fun rotulo(texto: String) = TextView(this).apply {
        text = texto
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(Color.rgb(43, 59, 79))
        setPadding(0, dp(8), 0, dp(2))
    }

    private fun botao(texto: String, acao: () -> Unit) = Button(this).apply {
        text = texto
        setOnClickListener { acao() }
    }

    private fun larguraCompleta() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    ).apply { bottomMargin = dp(10) }

    private fun campoParams() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    ).apply { bottomMargin = dp(8) }

    private fun botaoParams() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    ).apply { topMargin = dp(4); bottomMargin = dp(4) }

    private fun dp(valor: Int): Int = (valor * resources.displayMetrics.density).roundToInt()

    override fun onDestroy() {
        handler.removeCallbacks(refreshMonitor)
        executor.shutdownNow()
        super.onDestroy()
    }
}
