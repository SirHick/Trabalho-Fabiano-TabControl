"""
TabControl - servidor da interface web.
Usa as funcoes do tabcontrol.py (deixe os dois arquivos + index.html na mesma pasta).
Roda no PyCharm sem instalar nada: execute este arquivo e o navegador abre sozinho.
"""

import hmac
import json
import os
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import tabcontrol as tc

try:  # opcional: so e necessario para receber os eventos da fechadura por MQTT
    import paho.mqtt.client as paho_mqtt
except ImportError:
    paho_mqtt = None

PASTA = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA)  # garante que o tabcontrol.db seja sempre o desta pasta
PORTA = int(os.getenv("PORTA", "8000"))

# --- Fechadura (ESP32 / Wokwi) por MQTT -----------------------------
# Use o MESMO topico no codigo do ESP32. O broker hivemq e publico: troque o final por algo so seu.
MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPICO = os.getenv("MQTT_TOPICO", "tabcontrol/armario-weg-7k2/eventos")
MQTT_WS = os.getenv("MQTT_WS", "") == "1"   # 1 = MQTT sobre WebSocket (use MQTT_PORT=8000) se a rede bloquear 1883

# --- API de bateria -------------------------------------------------
# Quem pode ouvir: "127.0.0.1" = so este PC | "0.0.0.0" = a rede toda (necessario p/ os tablets enviarem)
HOST = os.getenv("TABCONTROL_HOST", "0.0.0.0")
# Token opcional. Se definido, os tablets precisam mandar o cabecalho X-TabControl-Token.
# Ex. (Windows):  set TABCONTROL_BATTERY_TOKEN=minha-senha-123
TOKEN_BATERIA = os.getenv("TABCONTROL_BATTERY_TOKEN", "")


def consulta(sql):
    with tc.conectar() as con:
        return [dict(linha) for linha in con.execute(sql).fetchall()]


LEITURAS = {
    "tablets": """
        SELECT t.*, (SELECT p.nome FROM emprestimos e
                     JOIN professores p ON p.id = e.professor_id
                     WHERE e.tablet_id = t.id AND e.devolucao IS NULL) AS com
        FROM tablets t ORDER BY t.codigo""",
    "professores": "SELECT * FROM professores ORDER BY nome",
    "acessos": """
        SELECT a.id, a.tipo, a.baia, a.detalhe, a.id_cracha, a.recebido_em, a.horario_dispositivo,
               COALESCE(p.nome, NULLIF(a.usuario, ''), '—') AS nome,
               (p.id IS NOT NULL) AS cadastrado
        FROM acessos_armario a
        LEFT JOIN professores p ON p.id = a.professor_id
        ORDER BY a.id DESC LIMIT 500""",
    "reservas": """
        SELECT r.id, r.inicio, r.fim, r.status, p.nome, p.tag_rfid AS tag_professor, t.codigo
        FROM reservas r
        JOIN professores p ON p.id = r.professor_id
        JOIN tablets t ON t.id = r.tablet_id
        ORDER BY r.inicio""",
    "historico": """
        SELECT e.id, p.nome, p.email, p.tag_rfid AS tag_professor,
               t.codigo, t.tag_rfid AS tag_tablet,
               e.retirada, e.devolucao, e.bateria_retirada, e.bateria_devolucao
        FROM emprestimos e
        JOIN professores p ON p.id = e.professor_id
        JOIN tablets t ON t.id = e.tablet_id
        ORDER BY e.retirada DESC, e.id DESC""",
    "observacoes": """
        SELECT o.id, o.data, o.tipo, o.resolvido, t.codigo, COALESCE(p.nome, 'Anônimo') AS nome, o.texto
        FROM observacoes o
        JOIN tablets t ON t.id = o.tablet_id
        LEFT JOIN professores p ON p.id = o.professor_id
        ORDER BY o.data DESC""",
}


def receber_bateria(d):
    """Aceita os dois formatos:
       - API antiga (main.py):  {"device_id", "level", "temperature", "voltage", "health", "timestamp"}
       - App Android:           {"codigo", "bateria"}
    device_id / codigo = codigo do tablet cadastrado (ex.: TAB-01)."""
    codigo = str(d.get("codigo") or d.get("device_id") or "").strip()
    nivel = d.get("bateria", d.get("level"))
    if not codigo or nivel is None:
        return False, "Envie o codigo do tablet (codigo/device_id) e a bateria (bateria/level)."
    return tc.registrar_leitura_bateria(
        codigo, nivel,
        temperatura=d.get("temperature", d.get("temperatura")),
        tensao=d.get("voltage", d.get("tensao")),
        saude=d.get("health", d.get("saude")),
        horario_tablet=d.get("timestamp"),
    )


def receber_evento_armario(d):
    """Evento da fechadura: {"ts","tipo","usuario","id","baia","detalhe"}"""
    return tc.registrar_acesso(d.get("tipo"), d.get("usuario"), d.get("id"),
                               d.get("baia"), d.get("detalhe"), d.get("ts"))


def tratar_mensagem_mqtt(payload):
    try:
        d = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        print("[MQTT] mensagem ignorada (nao e JSON valido).")
        return False
    ok, msg = receber_evento_armario(d)
    print(f"[MQTT] {d.get('tipo')}: {msg}")
    return ok


def iniciar_mqtt():
    if paho_mqtt is None:
        print("[MQTT] desligado: instale com  pip install paho-mqtt  para receber a fechadura.")
        return
    try:
        cliente = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2,
                                   transport="websockets" if MQTT_WS else "tcp")
    except AttributeError:  # paho-mqtt 1.x
        cliente = paho_mqtt.Client(transport="websockets" if MQTT_WS else "tcp")

    def ao_conectar(c, userdata, flags, rc, *extra):
        print(f"[MQTT] conectado a {MQTT_HOST}:{MQTT_PORT}, ouvindo '{MQTT_TOPICO}'")
        c.subscribe(MQTT_TOPICO)  # assina de novo a cada reconexao

    cliente.on_connect = ao_conectar
    cliente.on_message = lambda c, u, msg: tratar_mensagem_mqtt(msg.payload)
    cliente.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    cliente.loop_start()  # thread propria, reconecta sozinha


def data(texto):
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M")


def exemplo(_):
    tc.carregar_exemplo()
    return True, "Dados de exemplo carregados."


ACOES = {
    "retirar": lambda d: tc.retirar(d["tag_professor"], d["tag_tablet"]),
    "devolver": lambda d: tc.devolver(d["tag_tablet"], int(d["bateria"]), d["hardware"]),
    "reservar": lambda d: tc.reservar(d["tag_professor"], d["codigo"], data(d["inicio"]), data(d["fim"])),
    "cancelar": lambda d: tc.cancelar_reserva(int(d["id"]), d["tag_professor"]),
    "professor": lambda d: tc.cadastrar_professor(d["nome"], d["email"], d["tag"]),
    "tablet": lambda d: tc.cadastrar_tablet(d["codigo"], d["tag"]),
    "status": lambda d: tc.atualizar_status_tablet(d["codigo"], int(d["bateria"]), d["hardware"]),
    "observacao": lambda d: tc.registrar_observacao(d["codigo"], d.get("tag_professor", ""), d["texto"], d.get("tipo") == "defeito"),
    "excluir_professor": lambda d: tc.excluir_professor(int(d["id"]), bool(d.get("forcar"))),
    "excluir_tablet": lambda d: tc.excluir_tablet(int(d["id"]), bool(d.get("forcar"))),
    "exemplo": exemplo,
}


class Handler(BaseHTTPRequestHandler):
    def responder(self, conteudo, status=200, tipo="application/json"):
        if not isinstance(conteudo, bytes):
            conteudo = json.dumps(conteudo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(conteudo)))
        self.end_headers()
        self.wfile.write(conteudo)

    def token_ok(self):
        if not TOKEN_BATERIA:
            return True
        enviado = self.headers.get("X-TabControl-Token", "")
        return hmac.compare_digest(enviado.encode(), TOKEN_BATERIA.encode())

    def do_GET(self):
        url = urlsplit(self.path)
        rota = url.path.rstrip("/") or "/"
        if rota in ("/", "/index.html"):
            with open(os.path.join(PASTA, "index.html"), "rb") as f:
                return self.responder(f.read(), tipo="text/html")
        if rota in ("/health", "/api/health"):
            return self.responder({"status": "ok"})
        if rota == "/api/config":
            return self.responder({"bateria_minima": tc.BATERIA_MINIMA,
                                   "leitura_max_idade_min": tc.LEITURA_MAX_IDADE_MIN})
        # ---- rotas no formato da API antiga (main.py), usadas pelo dashboard.py ----
        if rota == "/devices":
            return self.responder(tc.dispositivos_api_antiga())
        p = rota.strip("/").split("/")
        if len(p) == 3 and p[0] == "battery" and p[2] in ("latest", "history"):
            if p[2] == "latest":
                leitura = tc.leituras_api_antiga(p[1], 1)
                if not leitura:
                    return self.responder({"detail": "Dispositivo sem leituras"}, 404)
                return self.responder(leitura[0])
            try:
                limite = min(max(int(parse_qs(url.query).get("limit", ["100"])[0]), 1), 1000)
            except ValueError:
                limite = 100
            return self.responder(tc.leituras_api_antiga(p[1], limite))

        # historico de bateria de um tablet: /api/bateria/TAB-01/historico?limite=50
        partes = rota.strip("/").split("/")
        if len(partes) == 4 and partes[:2] == ["api", "bateria"] and partes[3] == "historico":
            try:
                limite = min(max(int(parse_qs(url.query).get("limite", ["100"])[0]), 1), 1000)
            except ValueError:
                limite = 100
            return self.responder(tc.historico_bateria(partes[2], limite))
        if rota.startswith("/api/") and rota[5:] in LEITURAS:
            return self.responder(consulta(LEITURAS[rota[5:]]))
        self.responder({"erro": "nao encontrado"}, 404)

    def do_POST(self):
        rota = urlsplit(self.path).path.rstrip("/")
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
            dados = json.loads(self.rfile.read(tamanho) or "{}")
            if not isinstance(dados, dict):
                raise ValueError

            # ---- API de bateria (tablets / app Android) ----
            if rota in ("/api/bateria", "/battery"):
                if not self.token_ok():
                    return self.responder({"ok": False, "msg": "Token invalido."}, 401)
                ok, msg = receber_bateria(dados)
                return self.responder({"ok": ok, "msg": msg, "status": "ok" if ok else "erro"},
                                      201 if ok else 400)

            # ---- evento da fechadura por HTTP (alternativa ao MQTT) ----
            if rota == "/api/acesso":
                if not self.token_ok():
                    return self.responder({"ok": False, "msg": "Token invalido."}, 401)
                ok, msg = receber_evento_armario(dados)
                return self.responder({"ok": ok, "msg": msg}, 201 if ok else 400)

            # ---- acoes da tela web ----
            nome = rota[5:]
            if not rota.startswith("/api/") or nome not in ACOES:
                return self.responder({"erro": "nao encontrado"}, 404)
            resultado = ACOES[nome](dados)
            ok, msg = resultado[0], resultado[1]
            confirmar = len(resultado) > 2 and resultado[2]  # acao pede confirmacao do usuario
        except (KeyError, ValueError, TypeError):
            ok, msg, confirmar = False, "Dados inválidos ou incompletos.", False
        self.responder({"ok": ok, "msg": msg, "confirmar": confirmar})

    def log_message(self, *args):
        pass  # sem poluir o console do PyCharm


if __name__ == "__main__":
    tc.criar_tabelas()
    url = f"http://127.0.0.1:{PORTA}"
    iniciar_mqtt()
    servidor = ThreadingHTTPServer((HOST, PORTA), Handler)
    print(f"TabControl rodando em {url}  (Ctrl+C pra parar)")
    print(f"API de bateria:  POST http://<IP-DESTE-PC>:{PORTA}/api/bateria"
          f"  ({'com token' if TOKEN_BATERIA else 'SEM token'})")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")