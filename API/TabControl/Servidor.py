"""
TabControl - servidor da interface web e da API do leitor RFID (ESP32).
Usa as funcoes do tabcontrol.py (deixe os dois arquivos + index.html na mesma pasta).
So usa a biblioteca padrao do Python.

Antes de rodar, crie o arquivo .env (copie o .env.example) com a chave do ESP32
e o usuario/senha do painel. Depois e so executar este arquivo.
"""

import hmac
import json
import os
import secrets
import socket
import sys
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tabcontrol as tc

PASTA = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# Configuracao (vem do .env / variaveis de ambiente)
# ------------------------------------------------------------------
HOST = tc.cfg("TABCONTROL_HOST", "0.0.0.0")      # 0.0.0.0 = aceita conexoes da rede (ESP32, outros PCs)
PORTA = int(tc.cfg("TABCONTROL_PORTA", "8000"))
API_KEY = tc.cfg("TABCONTROL_API_KEY")           # chave que o ESP32 envia no cabecalho X-API-Key
ADMIN_USUARIO = tc.cfg("TABCONTROL_ADMIN_USUARIO", "admin")
ADMIN_SENHA = tc.cfg("TABCONTROL_ADMIN_SENHA")
DEMO = tc.cfg("TABCONTROL_DEMO", "0") == "1"     # so no teste: libera "carregar dados de exemplo"
ABRIR_NAVEGADOR = tc.cfg("TABCONTROL_ABRIR_NAVEGADOR", "0") == "1"
SESSAO_PAINEL_SEG = int(tc.cfg("TABCONTROL_SESSAO_HORAS", "8")) * 3600
MAX_CORPO = 64 * 1024                            # recusa corpos de requisicao enormes

_sessoes_painel = {}   # token -> expira (epoch)
_falhas_login = {}     # ip -> [epochs das ultimas tentativas erradas]


def consulta(sql):
    with tc.conectar() as con:
        return [dict(linha) for linha in con.execute(sql).fetchall()]


LEITURAS = {
    "tablets": """
        SELECT t.*, (SELECT p.nome FROM emprestimos e
                     JOIN professores p ON p.id = e.professor_id
                     WHERE e.tablet_id = t.id AND e.devolucao IS NULL) AS com,
               EXISTS(SELECT 1 FROM emprestimos e
                      WHERE e.tablet_id = t.id AND e.bateria_pendente = 1) AS conferir
        FROM tablets t ORDER BY t.codigo""",
    "professores": "SELECT * FROM professores ORDER BY nome",
    "reservas": """
        SELECT r.id, r.inicio, r.fim, r.status, p.nome, p.tag_rfid AS tag_professor, t.codigo
        FROM reservas r
        JOIN professores p ON p.id = r.professor_id
        JOIN tablets t ON t.id = r.tablet_id
        ORDER BY r.inicio""",
    "historico": """
        SELECT p.nome, t.codigo, e.retirada, e.devolucao, e.bateria_retirada, e.bateria_devolucao,
               e.bateria_pendente
        FROM emprestimos e
        JOIN professores p ON p.id = e.professor_id
        JOIN tablets t ON t.id = e.tablet_id
        ORDER BY e.retirada DESC""",
    "observacoes": """
        SELECT o.data, t.codigo, COALESCE(p.nome, 'Anônimo') AS nome, o.texto
        FROM observacoes o
        JOIN tablets t ON t.id = o.tablet_id
        LEFT JOIN professores p ON p.id = o.professor_id
        ORDER BY o.data DESC""",
    # NOVO: ultimas 100 leituras do ESP32
    "eventos": """
        SELECT quando, dispositivo, uid, tipo, ok, mensagem
        FROM eventos ORDER BY id DESC LIMIT 100""",
}


def data(texto):
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M")


def exemplo(_):
    if not DEMO:
        return False, "Dados de exemplo desativados."
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
    "observacao": lambda d: tc.registrar_observacao(d["codigo"], d.get("tag_professor", ""), d["texto"]),
    "exemplo": exemplo,
}


def ip_local():
    """Descobre o IP desta maquina na rede, para mostrar no console."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class Handler(BaseHTTPRequestHandler):
    # ---------------- utilidades ----------------
    def responder(self, conteudo, status=200, tipo="application/json", cabecalhos=None):
        if not isinstance(conteudo, bytes):
            conteudo = json.dumps(conteudo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if tipo == "application/json":
            self.send_header("Cache-Control", "no-store")
        for nome, valor in (cabecalhos or {}).items():
            self.send_header(nome, valor)
        self.end_headers()
        self.wfile.write(conteudo)

    def ip_cliente(self):
        return self.client_address[0]

    def token_cookie(self):
        for parte in self.headers.get("Cookie", "").split(";"):
            nome, _, valor = parte.strip().partition("=")
            if nome == "tc_sessao":
                return valor
        return ""

    def painel_logado(self):
        token = self.token_cookie()
        expira = _sessoes_painel.get(token)
        if not expira or expira < time.time():
            _sessoes_painel.pop(token, None)
            return False
        return True

    def chave_valida(self):
        enviada = self.headers.get("X-API-Key", "")
        return bool(API_KEY) and hmac.compare_digest(enviada, API_KEY)

    def ler_json(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        if tamanho > MAX_CORPO:
            raise ValueError("corpo grande demais")
        return json.loads(self.rfile.read(tamanho) or "{}")

    def nao_autorizado(self):
        self.responder({"ok": False, "msg": "Faça login."}, 401)

    # ---------------- GET ----------------
    def do_GET(self):
        rota = self.path.split("?")[0]

        if rota in ("/", "/index.html"):
            # aceita index.html ou Index.html (no Linux o nome e sensivel a maiusculas)
            for nome in ("index.html", "Index.html"):
                caminho = os.path.join(PASTA, nome)
                if os.path.exists(caminho):
                    with open(caminho, "rb") as f:
                        return self.responder(f.read(), tipo="text/html")
            return self.responder({"erro": "index.html nao encontrado"}, 404)

        if not rota.startswith("/api/"):
            return self.responder({"erro": "nao encontrado"}, 404)
        if not self.painel_logado():
            return self.nao_autorizado()

        nome = rota[5:]
        if nome in LEITURAS:
            return self.responder(consulta(LEITURAS[nome]))
        if nome == "config":
            return self.responder({"bateria_minima": tc.BATERIA_MINIMA,
                                   "dias_max": tc.DIAS_MAX_ANTECEDENCIA, "demo": DEMO})
        if nome == "dispositivos":
            return self.responder(tc.listar_dispositivos())
        if nome == "ultima_tag":
            return self.responder({"uid": tc.ultima_tag_desconhecida()})
        self.responder({"erro": "nao encontrado"}, 404)

    # ---------------- POST ----------------
    def do_POST(self):
        nome = self.path.split("?")[0][5:]
        try:
            # --- login do painel ---
            if nome == "login":
                return self.login()
            if nome == "logout":
                _sessoes_painel.pop(self.token_cookie(), None)
                return self.responder({"ok": True, "msg": "Sessão encerrada."},
                                      cabecalhos={"Set-Cookie": "tc_sessao=; Path=/; Max-Age=0"})

            # --- ESP32: autenticado por chave, nao por cookie ---
            if nome in ("leitura", "ping"):
                if not self.chave_valida():
                    return self.responder({"ok": False, "acao": "negado", "msg": "Chave invalida."}, 401)
                dados = self.ler_json()
                if nome == "ping":
                    tc.registrar_ping(str(dados["dispositivo"]))
                    return self.responder({"ok": True, "msg": "pong"})
                return self.responder(tc.processar_leitura(str(dados["dispositivo"]), str(dados["uid"])))

            # --- painel ---
            if nome not in ACOES:
                return self.responder({"erro": "nao encontrado"}, 404)
            if not self.painel_logado():
                return self.nao_autorizado()
            ok, msg = ACOES[nome](self.ler_json())
        except (KeyError, ValueError, TypeError):
            ok, msg = False, "Dados inválidos ou incompletos."
        except Exception as e:  # nunca deixa a thread morrer calada
            print(f"[ERRO] {self.path}: {e!r}", file=sys.stderr)
            ok, msg = False, "Erro interno no servidor."
        self.responder({"ok": ok, "msg": msg})

    def login(self):
        ip, agora = self.ip_cliente(), time.time()
        tentativas = [t for t in _falhas_login.get(ip, []) if agora - t < 60]
        if len(tentativas) >= 5:
            return self.responder({"ok": False, "msg": "Muitas tentativas. Aguarde 1 minuto."}, 429)
        dados = self.ler_json()
        usuario_ok = hmac.compare_digest(str(dados.get("usuario", "")), ADMIN_USUARIO)
        senha_ok = hmac.compare_digest(str(dados.get("senha", "")), ADMIN_SENHA)
        if not (usuario_ok and senha_ok):
            tentativas.append(agora)
            _falhas_login[ip] = tentativas
            return self.responder({"ok": False, "msg": "Usuário ou senha incorretos."}, 401)
        _falhas_login.pop(ip, None)
        token = secrets.token_urlsafe(32)
        _sessoes_painel[token] = agora + SESSAO_PAINEL_SEG
        cookie = f"tc_sessao={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSAO_PAINEL_SEG}"
        self.responder({"ok": True, "msg": "Bem-vindo."}, cabecalhos={"Set-Cookie": cookie})

    def log_message(self, *args):
        pass  # sem poluir o console


if __name__ == "__main__":
    faltando = [n for n, v in (("TABCONTROL_API_KEY", API_KEY), ("TABCONTROL_ADMIN_SENHA", ADMIN_SENHA)) if not v]
    if faltando:
        sys.exit("Faltam configuracoes no arquivo .env: " + ", ".join(faltando) +
                 "\nCopie o .env.example para .env e preencha.")
    tc.criar_tabelas()
    servidor = ThreadingHTTPServer((HOST, PORTA), Handler)
    servidor.daemon_threads = True
    print(f"TabControl rodando em http://127.0.0.1:{PORTA}")
    if HOST == "0.0.0.0":
        print(f"Para o ESP32 e outros computadores da rede use: http://{ip_local()}:{PORTA}")
    print("(Ctrl+C pra parar)")
    if ABRIR_NAVEGADOR:
        webbrowser.open(f"http://127.0.0.1:{PORTA}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
