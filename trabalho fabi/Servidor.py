"""
TabControl - servidor da interface web.
Usa as funcoes do tabcontrol.py (deixe os dois arquivos + index.html na mesma pasta).
Roda no PyCharm sem instalar nada: execute este arquivo e o navegador abre sozinho.
"""

import json
import os
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tabcontrol as tc

PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA = 8000


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
    "reservas": """
        SELECT r.id, r.inicio, r.fim, r.status, p.nome, p.tag_rfid AS tag_professor, t.codigo
        FROM reservas r
        JOIN professores p ON p.id = r.professor_id
        JOIN tablets t ON t.id = r.tablet_id
        ORDER BY r.inicio""",
    "historico": """
        SELECT p.nome, t.codigo, e.retirada, e.devolucao, e.bateria_retirada, e.bateria_devolucao
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
}


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
    "observacao": lambda d: tc.registrar_observacao(d["codigo"], d.get("tag_professor", ""), d["texto"]),
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

    def do_GET(self):
        rota = self.path.split("?")[0]
        if rota in ("/", "/index.html"):
            with open(os.path.join(PASTA, "index.html"), "rb") as f:
                return self.responder(f.read(), tipo="text/html")
        if rota.startswith("/api/") and rota[5:] in LEITURAS:
            return self.responder(consulta(LEITURAS[rota[5:]]))
        self.responder({"erro": "nao encontrado"}, 404)

    def do_POST(self):
        nome = self.path[5:]
        if nome not in ACOES:
            return self.responder({"erro": "nao encontrado"}, 404)
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
            dados = json.loads(self.rfile.read(tamanho) or "{}")
            ok, msg = ACOES[nome](dados)
        except (KeyError, ValueError):
            ok, msg = False, "Dados inválidos ou incompletos."
        self.responder({"ok": ok, "msg": msg})

    def log_message(self, *args):
        pass  # sem poluir o console do PyCharm


if __name__ == "__main__":
    tc.criar_tabelas()
    url = f"http://127.0.0.1:{PORTA}"
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"TabControl rodando em {url}  (Ctrl+C pra parar)")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")