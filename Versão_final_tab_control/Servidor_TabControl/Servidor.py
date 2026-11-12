"""Servidor HTTP do painel TabControl e endpoint de bateria Android.

O endpoint POST /api/bateria exige o cabecalho X-TabControl-Token.
Configure TABCONTROL_BATTERY_TOKEN no arquivo .env antes de iniciar.
"""

import hmac
import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tabcontrol as tc

PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA = int(os.getenv("TABCONTROL_PORT", "8000"))
NOME_CABECALHO_TOKEN = "X-TabControl-Token"
TAMANHO_MAXIMO_POST = 16 * 1024

LEITURAS = {
    "tablets": """
        SELECT t.id, t.codigo, t.tag_rfid, t.bateria,
               DATE_FORMAT(t.bateria_atualizada_em, '%%Y-%%m-%%dT%%H:%%i:%%sZ') AS bateria_atualizada_em,
               t.hardware, t.status,
               (SELECT p.nome FROM emprestimos e
                JOIN professores p ON p.id = e.professor_id
                WHERE e.tablet_id = t.id AND e.devolucao IS NULL
                ORDER BY e.id DESC LIMIT 1) AS com
        FROM tablets t ORDER BY t.codigo""",
    "professores": "SELECT * FROM professores ORDER BY nome",
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
        SELECT o.id, o.data, o.tipo, o.resolvido, t.codigo,
               COALESCE(p.nome, 'Anônimo') AS nome, o.texto
        FROM observacoes o
        JOIN tablets t ON t.id = o.tablet_id
        LEFT JOIN professores p ON p.id = o.professor_id
        ORDER BY o.data DESC""",
}


def consulta(sql):
    with tc.conectar() as con:
        return [dict(linha) for linha in con.execute(sql).fetchall()]


def data(texto):
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M")


def exemplo(_):
    tc.carregar_exemplo()
    return True, "Dados de exemplo carregados."


def registrar_bateria_android(dados):
    """Grava apenas leituras inteiras de 0-100 e a hora de recebimento no servidor."""
    try:
        codigo = str(dados["codigo"]).strip()
        valor = dados["bateria"]
        if isinstance(valor, bool) or not str(valor).strip().isdigit():
            raise ValueError("bateria deve ser um numero inteiro")
        bateria = int(valor)
    except (KeyError, TypeError, ValueError):
        return False, "Informe o codigo do tablet e a bateria como numero inteiro."

    if not codigo:
        return False, "O codigo do tablet nao pode ficar vazio."
    if len(codigo) > 191:
        return False, "Codigo do tablet excede o tamanho permitido."
    if not 0 <= bateria <= 100:
        return False, "Bateria tem que estar entre 0 e 100."

    with tc.conectar() as con:
        correspondencias = con.execute(
            """SELECT id, codigo FROM tablets
               WHERE UPPER(TRIM(codigo)) = UPPER(TRIM(?)) FOR UPDATE""",
            (codigo,),
        ).fetchall()
        if not correspondencias:
            return False, f"Tablet '{codigo}' nao encontrado. Cadastre-o antes de enviar."
        if len(correspondencias) > 1:
            return False, f"Ha mais de um cadastro equivalente a '{codigo}'. Corrija os codigos duplicados."

        con.execute(
            """UPDATE tablets
               SET bateria = ?, bateria_atualizada_em = ?
               WHERE id = ?""",
            (bateria, datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0), correspondencias[0]["id"]),
        )
        codigo_cadastrado = correspondencias[0]["codigo"]

    return True, f"{codigo_cadastrado}: bateria atualizada para {bateria}% e leitura registrada."


ACOES = {
    "retirar": lambda d: tc.retirar(d["tag_professor"], d["tag_tablet"]),
    "devolver": lambda d: tc.devolver(d["tag_tablet"], d.get("hardware", "ok")),
    "reservar": lambda d: tc.reservar(d["tag_professor"], d["codigo"], data(d["inicio"]), data(d["fim"])),
    "cancelar": lambda d: tc.cancelar_reserva(int(d["id"]), d["tag_professor"]),
    "professor": lambda d: tc.cadastrar_professor(d["nome"], d["email"], d["tag"]),
    "tablet": lambda d: tc.cadastrar_tablet(d["codigo"], d["tag"]),
    # O painel web nao recebe mais percentual manual: altera somente hardware.
    "hardware": lambda d: tc.atualizar_hardware_tablet(d["codigo"], d["hardware"]),
    "bateria": registrar_bateria_android,
    "observacao": lambda d: tc.registrar_observacao(
        d["codigo"], d.get("tag_professor", ""), d["texto"], d.get("tipo") == "defeito"
    ),
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(conteudo)

    def do_GET(self):
        rota = self.path.split("?", 1)[0]
        try:
            if rota in ("/", "/index.html"):
                with open(os.path.join(PASTA, "index.html"), "rb") as arquivo:
                    return self.responder(arquivo.read(), tipo="text/html")
            if rota == "/api/config":
                return self.responder({
                    "bateria_minima": tc.BATERIA_MINIMA,
                    "bateria_max_idade_min": tc.BATERIA_MAX_IDADE_MIN,
                })
            if rota.startswith("/api/") and rota[5:] in LEITURAS:
                return self.responder(consulta(LEITURAS[rota[5:]]))
            return self.responder({"erro": "nao encontrado"}, 404)
        except Exception as erro:
            print(f"Erro em GET {rota}: {erro}", file=sys.stderr)
            return self.responder({"erro": "Erro interno ao consultar o TabControl."}, 500)

    def do_POST(self):
        rota = self.path.split("?", 1)[0]
        nome = rota[5:] if rota.startswith("/api/") else ""
        if nome not in ACOES:
            return self.responder({"erro": "nao encontrado"}, 404)

        if nome == "bateria":
            token_configurado = os.getenv("TABCONTROL_BATTERY_TOKEN", "").strip()
            token_recebido = self.headers.get(NOME_CABECALHO_TOKEN, "").strip()
            if not token_configurado or not token_recebido or not hmac.compare_digest(
                token_recebido.encode("utf-8"), token_configurado.encode("utf-8")
            ):
                return self.responder({"ok": False, "msg": "Token de dispositivo invalido ou ausente."}, 401)

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if tamanho <= 0 or tamanho > TAMANHO_MAXIMO_POST:
                return self.responder({"ok": False, "msg": "Tamanho do corpo da requisicao invalido."}, 413)
            bruto = self.rfile.read(tamanho)
            dados = json.loads(bruto.decode("utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("O corpo JSON precisa ser um objeto.")
            resultado = ACOES[nome](dados)
            ok, msg = resultado[0], resultado[1]
            confirmar = len(resultado) > 2 and resultado[2]
            status_http = 200 if ok else 400
            return self.responder({"ok": ok, "msg": msg, "confirmar": confirmar}, status_http)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self.responder({"ok": False, "msg": "Dados invalidos ou incompletos.", "confirmar": False}, 400)
        except Exception as erro:
            print(f"Erro em POST {rota}: {erro}", file=sys.stderr)
            return self.responder({"ok": False, "msg": "Erro interno ao processar a operacao.", "confirmar": False}, 500)

    def log_message(self, *args):
        pass  # evita poluir o console do PyCharm


def main():
    token = os.getenv("TABCONTROL_BATTERY_TOKEN", "").strip()
    if len(token) < 32 or token.upper().startswith(("COLOQUE", "CONFIGURE", "PLACEHOLDER")):
        raise RuntimeError(
            "Configure TABCONTROL_BATTERY_TOKEN no arquivo .env com um token aleatorio "
            "de pelo menos 32 caracteres. Gere com: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    tc.criar_tabelas()
    url = f"http://127.0.0.1:{PORTA}"
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA), Handler)
    print(f"TabControl rodando em {url} (Ctrl+C para parar)")
    print("Endpoint Android /api/bateria protegido por token.")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
