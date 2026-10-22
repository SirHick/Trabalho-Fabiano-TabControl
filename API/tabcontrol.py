"""
TabControl - controle e gerenciamento dos tablets do armario (Centro WEG)
Equipe Brokers - Implementacao de Negocios Inovadores

Roda direto no PyCharm, so usa biblioteca padrao do Python (sqlite3).
O banco (tabcontrol.db) e criado sozinho na primeira execucao.

No menu do console a leitura da tag continua simulada (voce digita o codigo).
Com o ESP32 real, as leituras chegam pelo Servidor.py (POST /api/leitura) e sao
tratadas pela funcao processar_leitura() deste arquivo.
"""

import os
import re
import smtplib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage

# ------------------------------------------------------------------
# Configuracoes
# Tudo pode ser definido no arquivo .env (ao lado deste arquivo) ou em
# variaveis de ambiente. Se nao definir nada, vale o padrao abaixo.
# ------------------------------------------------------------------
PASTA = os.path.dirname(os.path.abspath(__file__))


def carregar_env():
    """Le o arquivo .env (CHAVE=valor) sem precisar de biblioteca externa."""
    caminho = os.path.join(PASTA, ".env")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8-sig") as f:   # utf-8-sig: aceita o BOM do Bloco de Notas
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()


def cfg(nome, padrao=""):
    return os.environ.get(nome, padrao)


# Caminho absoluto: o servidor funciona de qualquer pasta (servico, agendador...)
DB_ARQUIVO = cfg("TABCONTROL_DB", os.path.join(PASTA, "tabcontrol.db"))

BATERIA_MINIMA = int(cfg("BATERIA_MINIMA", "50"))          # abaixo disso o emprestimo e bloqueado (%)
DIAS_MAX_ANTECEDENCIA = int(cfg("DIAS_MAX_ANTECEDENCIA", "7"))  # evita "reserva muito antecipada"
TOLERANCIA_RETIRADA_MIN = int(cfg("TOLERANCIA_RETIRADA_MIN", "5"))  # pode retirar ate X min antes do horario reservado

# Leitor RFID (ESP32)
SESSAO_LEITURA_SEG = int(cfg("SESSAO_LEITURA_SEGUNDOS", "30"))    # tempo que o cracha "vale" para pegar tablets
DEBOUNCE_SEG = int(cfg("DEBOUNCE_SEGUNDOS", "3"))                 # ignora a mesma tag lida varias vezes seguidas
DEVOLUCAO_MIN_SEG = int(cfg("DEVOLUCAO_MIN_SEGUNDOS", "60"))      # evita devolver sem querer logo apos retirar

# Email: se SMTP_HOST ficar vazio, os emails so aparecem no console (simulado)
SMTP_HOST = cfg("SMTP_HOST") or None             # ex: "smtp.gmail.com"
SMTP_PORTA = int(cfg("SMTP_PORTA", "587"))       # 587 = STARTTLS, 465 = SSL direto
SMTP_USUARIO = cfg("SMTP_USUARIO")
SMTP_SENHA = cfg("SMTP_SENHA")
SMTP_REMETENTE = cfg("SMTP_REMETENTE") or SMTP_USUARIO
EMAIL_ADMIN = cfg("EMAIL_ADMIN", "administracao@exemplo.com")

FMT_BANCO = "%Y-%m-%d %H:%M"
FMT_TELA = "%d/%m/%Y %H:%M"


# ------------------------------------------------------------------
# Banco de dados
# ------------------------------------------------------------------
@contextmanager
def conectar():
    con = sqlite3.connect(DB_ARQUIVO, timeout=10)   # espera ate 10s se o banco estiver ocupado
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")        # painel e ESP32 podem usar ao mesmo tempo
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def criar_tabelas():
    with conectar() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS professores (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT NOT NULL,
            email     TEXT NOT NULL UNIQUE,
            tag_rfid  TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS tablets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo     TEXT NOT NULL UNIQUE,
            tag_rfid   TEXT NOT NULL UNIQUE,
            bateria    INTEGER NOT NULL DEFAULT 100,
            hardware   TEXT NOT NULL DEFAULT 'ok',          -- ok / defeito
            status     TEXT NOT NULL DEFAULT 'disponivel'   -- disponivel / emprestado / manutencao
        );

        CREATE TABLE IF NOT EXISTS reservas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id  INTEGER NOT NULL REFERENCES professores(id),
            tablet_id     INTEGER NOT NULL REFERENCES tablets(id),
            inicio        TEXT NOT NULL,
            fim           TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'ativa'     -- ativa / concluida / cancelada
        );

        CREATE TABLE IF NOT EXISTS emprestimos (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id        INTEGER NOT NULL REFERENCES professores(id),
            tablet_id           INTEGER NOT NULL REFERENCES tablets(id),
            retirada            TEXT NOT NULL,
            devolucao           TEXT,
            bateria_retirada    INTEGER,
            bateria_devolucao   INTEGER
        );

        CREATE TABLE IF NOT EXISTS observacoes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tablet_id     INTEGER NOT NULL REFERENCES tablets(id),
            professor_id  INTEGER REFERENCES professores(id),
            data          TEXT NOT NULL,
            texto         TEXT NOT NULL
        );

        -- NOVO: registro de tudo que o leitor RFID (ESP32) enviou
        CREATE TABLE IF NOT EXISTS eventos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            dispositivo  TEXT NOT NULL,
            uid          TEXT NOT NULL,
            quando       TEXT NOT NULL,
            tipo         TEXT NOT NULL,       -- professor / tablet / desconhecida
            ok           INTEGER NOT NULL,
            mensagem     TEXT NOT NULL
        );
        """)

        # NOVO: banco antigo (do simulador) ganha a coluna nova sem perder dados
        colunas = [c["name"] for c in con.execute("PRAGMA table_info(emprestimos)")]
        if "bateria_pendente" not in colunas:
            con.execute("ALTER TABLE emprestimos ADD COLUMN bateria_pendente INTEGER NOT NULL DEFAULT 0")

        # NOVO: padroniza tags ja cadastradas (maiuscula, sem ':' ou espacos)
        for tabela in ("professores", "tablets"):
            for linha in con.execute(f"SELECT id, tag_rfid FROM {tabela}").fetchall():
                limpa = norm_tag(linha["tag_rfid"])
                if limpa != linha["tag_rfid"]:
                    try:
                        con.execute(f"UPDATE {tabela} SET tag_rfid = ? WHERE id = ?", (limpa, linha["id"]))
                    except sqlite3.IntegrityError:
                        print(f"[AVISO] Tag duplicada ao padronizar {tabela} id={linha['id']}: {limpa}")


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------
def agora():
    return datetime.now().strftime(FMT_BANCO)


def para_tela(texto_banco):
    if not texto_banco:
        return "-"
    return datetime.strptime(texto_banco, FMT_BANCO).strftime(FMT_TELA)


def ler_data(texto):
    """Converte 'dd/mm/aaaa hh:mm' em datetime. Retorna None se estiver errado."""
    try:
        return datetime.strptime(texto.strip(), FMT_TELA)
    except ValueError:
        return None


def norm_tag(tag):
    """NOVO: deixa o UID sempre igual: '04:a3 b2' -> '04A3B2'. O leitor e a pessoa que
    digita nao precisam usar o mesmo formato."""
    return re.sub(r"[^0-9A-Za-z]", "", tag or "").upper()


def ler_tag(msg):
    # Usado so no menu do console (simulacao). No ESP32 real a tag chega por /api/leitura.
    return norm_tag(input(msg))


def _enviar_smtp(destino, assunto, corpo):
    try:
        msg = EmailMessage()
        msg["From"] = SMTP_REMETENTE
        msg["To"] = destino
        msg["Subject"] = assunto
        msg.set_content(corpo)
        if SMTP_PORTA == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORTA, timeout=15) as srv:
                srv.login(SMTP_USUARIO, SMTP_SENHA)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORTA, timeout=15) as srv:
                srv.starttls()
                srv.login(SMTP_USUARIO, SMTP_SENHA)
                srv.send_message(msg)
    except Exception as e:
        print(f"Nao consegui enviar o email ({e})")


def enviar_email(destino, assunto, corpo):
    if not SMTP_HOST:
        print(f"\n[EMAIL SIMULADO] para: {destino}\n  assunto: {assunto}\n  {corpo}\n")
        return
    # NOVO: envia em segundo plano, senao um SMTP lento deixaria o ESP32 esperando resposta
    threading.Thread(target=_enviar_smtp, args=(destino, assunto, corpo), daemon=True).start()


# ------------------------------------------------------------------
# Cadastros
# ------------------------------------------------------------------
def cadastrar_professor(nome, email, tag):
    nome, email, tag = nome.strip(), email.strip(), norm_tag(tag)
    if not nome or not email or not tag:
        return False, "Nome, email e tag sao obrigatorios."
    try:
        with conectar() as con:
            con.execute("INSERT INTO professores (nome, email, tag_rfid) VALUES (?, ?, ?)",
                        (nome, email, tag))
        return True, f"Professor {nome} cadastrado."
    except sqlite3.IntegrityError:
        return False, "Ja existe professor com esse email ou essa tag."


def cadastrar_tablet(codigo, tag):
    codigo, tag = codigo.strip(), norm_tag(tag)
    if not codigo or not tag:
        return False, "Codigo e tag sao obrigatorios."
    try:
        with conectar() as con:
            con.execute("INSERT INTO tablets (codigo, tag_rfid) VALUES (?, ?)", (codigo, tag))
        return True, f"Tablet {codigo} cadastrado."
    except sqlite3.IntegrityError:
        return False, "Ja existe tablet com esse codigo ou essa tag."


def atualizar_status_tablet(codigo, bateria, hardware):
    """Simula o que o ESP32 vai mandar (bateria e estado do hardware)."""
    if not 0 <= bateria <= 100:
        return False, "Bateria tem que estar entre 0 e 100."
    if hardware not in ("ok", "defeito"):
        return False, "Hardware tem que ser 'ok' ou 'defeito'."
    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE codigo = ?", (codigo,)).fetchone()
        if not tablet:
            return False, "Tablet nao encontrado."
        novo_status = tablet["status"]
        if hardware == "defeito" and tablet["status"] == "disponivel":
            novo_status = "manutencao"
        elif hardware == "ok" and tablet["status"] == "manutencao":
            novo_status = "disponivel"
        con.execute("UPDATE tablets SET bateria = ?, hardware = ?, status = ? WHERE id = ?",
                    (bateria, hardware, novo_status, tablet["id"]))

        # NOVO: se a ultima devolucao foi feita pelo leitor RFID (sem saber a bateria),
        # esta leitura confirma o valor real e fecha a pendencia.
        pendente = con.execute(
            """SELECT e.id, p.nome FROM emprestimos e
               JOIN professores p ON p.id = e.professor_id
               WHERE e.tablet_id = ? AND e.devolucao IS NOT NULL AND e.bateria_pendente = 1
               ORDER BY e.id DESC LIMIT 1""", (tablet["id"],)).fetchone()
        if pendente:
            con.execute("UPDATE emprestimos SET bateria_devolucao = ?, bateria_pendente = 0 "
                        "WHERE tablet_id = ? AND bateria_pendente = 1", (bateria, tablet["id"]))
    if pendente and (hardware != "ok" or bateria < BATERIA_MINIMA):
        enviar_email(EMAIL_ADMIN, f"Atencao: tablet {codigo}",
                     f"Devolvido com bateria {bateria}% e hardware '{hardware}'. "
                     f"Ultimo usuario: {pendente['nome']}.")
    return True, f"{codigo}: bateria {bateria}%, hardware {hardware}, status {novo_status}."


# ------------------------------------------------------------------
# Reservas
# ------------------------------------------------------------------
def reservar(tag_professor, codigo_tablet, inicio, fim):
    agora_dt = datetime.now()
    if fim <= inicio:
        return False, "O horario final tem que ser depois do inicial."
    if inicio < agora_dt:
        return False, "Nao da pra reservar no passado."
    if inicio > agora_dt + timedelta(days=DIAS_MAX_ANTECEDENCIA):
        return False, f"Reserva muito antecipada (maximo {DIAS_MAX_ANTECEDENCIA} dias)."

    ini, fi = inicio.strftime(FMT_BANCO), fim.strftime(FMT_BANCO)
    tag_professor = norm_tag(tag_professor)
    with conectar() as con:
        prof = con.execute("SELECT * FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        tablet = con.execute("SELECT * FROM tablets WHERE codigo = ?", (codigo_tablet,)).fetchone()
        if not prof:
            return False, "Professor nao encontrado."
        if not tablet:
            return False, "Tablet nao encontrado."
        if tablet["status"] == "manutencao":
            return False, "Esse tablet esta em manutencao."

        conflito = con.execute(
            """SELECT 1 FROM reservas
               WHERE tablet_id = ? AND status = 'ativa' AND inicio < ? AND fim > ?""",
            (tablet["id"], fi, ini)).fetchone()
        if conflito:
            return False, "Ja existe reserva desse tablet nesse horario."

        con.execute("INSERT INTO reservas (professor_id, tablet_id, inicio, fim) VALUES (?, ?, ?, ?)",
                    (prof["id"], tablet["id"], ini, fi))

    enviar_email(prof["email"], "Reserva confirmada - TabControl",
                 f"Ola {prof['nome']}, o tablet {codigo_tablet} foi reservado de "
                 f"{inicio.strftime(FMT_TELA)} ate {fim.strftime(FMT_TELA)}.")
    return True, "Reserva feita."


def cancelar_reserva(reserva_id, tag_professor):
    tag_professor = norm_tag(tag_professor)
    with conectar() as con:
        prof = con.execute("SELECT * FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        if not prof:
            return False, "Professor nao encontrado."
        res = con.execute("SELECT * FROM reservas WHERE id = ? AND status = 'ativa'",
                          (reserva_id,)).fetchone()
        if not res:
            return False, "Reserva ativa nao encontrada."
        if res["professor_id"] != prof["id"]:
            return False, "Essa reserva e de outro professor."
        con.execute("UPDATE reservas SET status = 'cancelada' WHERE id = ?", (reserva_id,))
    return True, "Reserva cancelada."


# ------------------------------------------------------------------
# Retirada e devolucao
# ------------------------------------------------------------------
def retirar(tag_professor, tag_tablet):
    tag_professor, tag_tablet = norm_tag(tag_professor), norm_tag(tag_tablet)
    agora_dt = datetime.now()
    limite = (agora_dt + timedelta(minutes=TOLERANCIA_RETIRADA_MIN)).strftime(FMT_BANCO)

    with conectar() as con:
        prof = con.execute("SELECT * FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        if not prof:
            return False, "Tag de professor nao cadastrada. Acesso negado."

        tablet = con.execute("SELECT * FROM tablets WHERE tag_rfid = ?", (tag_tablet,)).fetchone()
        if not tablet:
            return False, "Tag de tablet nao cadastrada."

        if tablet["status"] == "emprestado":
            return False, "Esse tablet ja esta emprestado."
        if tablet["status"] == "manutencao" or tablet["hardware"] != "ok":
            return False, "Tablet com problema de hardware / em manutencao."
        if tablet["bateria"] < BATERIA_MINIMA:
            return False, (f"Emprestimo bloqueado: bateria em {tablet['bateria']}% "
                           f"(minimo {BATERIA_MINIMA}%).")

        # tem reserva de outra pessoa valendo agora?
        reserva = con.execute(
            """SELECT * FROM reservas
               WHERE tablet_id = ? AND status = 'ativa' AND inicio <= ? AND fim >= ?""",
            (tablet["id"], limite, agora_dt.strftime(FMT_BANCO))).fetchone()
        if reserva and reserva["professor_id"] != prof["id"]:
            return False, "Tablet reservado por outro professor nesse horario."
        if reserva:
            con.execute("UPDATE reservas SET status = 'concluida' WHERE id = ?", (reserva["id"],))

        con.execute(
            """INSERT INTO emprestimos (professor_id, tablet_id, retirada, bateria_retirada)
               VALUES (?, ?, ?, ?)""",
            (prof["id"], tablet["id"], agora(), tablet["bateria"]))
        con.execute("UPDATE tablets SET status = 'emprestado' WHERE id = ?", (tablet["id"],))

    enviar_email(prof["email"], "Retirada de tablet - TabControl",
                 f"Ola {prof['nome']}, voce retirou o tablet {tablet['codigo']} "
                 f"em {agora_dt.strftime(FMT_TELA)} (bateria {tablet['bateria']}%).")
    return True, f"Liberado! {prof['nome']} retirou o {tablet['codigo']}. (fechadura aberta)"


def devolver(tag_tablet, bateria_atual, hardware="ok", pendente=False):
    """pendente=True: devolucao feita pelo leitor RFID, que nao sabe a bateria real.
    A bateria fica marcada 'a confirmar' ate alguem atualizar a leitura no painel."""
    tag_tablet = norm_tag(tag_tablet)
    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE tag_rfid = ?", (tag_tablet,)).fetchone()
        if not tablet:
            return False, "Tag de tablet nao cadastrada."

        emp = con.execute(
            """SELECT e.*, p.nome, p.email FROM emprestimos e
               JOIN professores p ON p.id = e.professor_id
               WHERE e.tablet_id = ? AND e.devolucao IS NULL""", (tablet["id"],)).fetchone()
        if not emp:
            return False, "Nao tem emprestimo em aberto pra esse tablet."

        novo_status = "disponivel" if hardware == "ok" else "manutencao"
        con.execute("UPDATE emprestimos SET devolucao = ?, bateria_devolucao = ?, bateria_pendente = ? WHERE id = ?",
                    (agora(), bateria_atual, 1 if pendente else 0, emp["id"]))
        con.execute("UPDATE tablets SET status = ?, bateria = ?, hardware = ? WHERE id = ?",
                    (novo_status, bateria_atual, hardware, tablet["id"]))

    enviar_email(emp["email"], "Devolucao registrada - TabControl",
                 f"Ola {emp['nome']}, a devolucao do tablet {tablet['codigo']} foi registrada.")

    # com bateria pendente nao da pra avisar o admin ainda (valor desconhecido)
    if not pendente and (hardware != "ok" or bateria_atual < BATERIA_MINIMA):
        enviar_email(EMAIL_ADMIN, f"Atencao: tablet {tablet['codigo']}",
                     f"Devolvido com bateria {bateria_atual}% e hardware '{hardware}'. "
                     f"Ultimo usuario: {emp['nome']}.")
    return True, f"Devolucao do {tablet['codigo']} registrada."


# ------------------------------------------------------------------
# Observacoes / reclamacoes
# ------------------------------------------------------------------
def registrar_observacao(codigo_tablet, tag_professor, texto):
    tag_professor = norm_tag(tag_professor)
    if not texto.strip():
        return False, "Escreva a observacao."
    with conectar() as con:
        tablet = con.execute("SELECT id FROM tablets WHERE codigo = ?", (codigo_tablet,)).fetchone()
        if not tablet:
            return False, "Tablet nao encontrado."
        prof = con.execute("SELECT id FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        con.execute("INSERT INTO observacoes (tablet_id, professor_id, data, texto) VALUES (?, ?, ?, ?)",
                    (tablet["id"], prof["id"] if prof else None, agora(), texto))
    return True, "Observacao registrada."


# ------------------------------------------------------------------
# Consultas
# ------------------------------------------------------------------
def mostrar_tablets():
    with conectar() as con:
        linhas = con.execute("SELECT * FROM tablets ORDER BY codigo").fetchall()
    print(f"\n{'CODIGO':<10}{'TAG':<12}{'BATERIA':<10}{'HARDWARE':<10}STATUS")
    print("-" * 52)
    for t in linhas:
        alerta = "  <- bateria baixa" if t["bateria"] < BATERIA_MINIMA else ""
        print(f"{t['codigo']:<10}{t['tag_rfid']:<12}{str(t['bateria']) + '%':<10}"
              f"{t['hardware']:<10}{t['status']}{alerta}")


def mostrar_professores():
    with conectar() as con:
        linhas = con.execute("SELECT * FROM professores ORDER BY nome").fetchall()
    print(f"\n{'NOME':<25}{'EMAIL':<30}TAG")
    print("-" * 65)
    for p in linhas:
        print(f"{p['nome']:<25}{p['email']:<30}{p['tag_rfid']}")


def mostrar_reservas():
    with conectar() as con:
        linhas = con.execute(
            """SELECT r.id, p.nome, t.codigo, r.inicio, r.fim, r.status
               FROM reservas r
               JOIN professores p ON p.id = r.professor_id
               JOIN tablets t ON t.id = r.tablet_id
               ORDER BY r.inicio""").fetchall()
    print(f"\n{'ID':<5}{'PROFESSOR':<22}{'TABLET':<10}{'INICIO':<18}{'FIM':<18}STATUS")
    print("-" * 80)
    for r in linhas:
        print(f"{r['id']:<5}{r['nome']:<22}{r['codigo']:<10}"
              f"{para_tela(r['inicio']):<18}{para_tela(r['fim']):<18}{r['status']}")


def mostrar_historico():
    with conectar() as con:
        linhas = con.execute(
            """SELECT p.nome, t.codigo, e.retirada, e.devolucao,
                      e.bateria_retirada, e.bateria_devolucao
               FROM emprestimos e
               JOIN professores p ON p.id = e.professor_id
               JOIN tablets t ON t.id = e.tablet_id
               ORDER BY e.retirada DESC""").fetchall()
    print(f"\n{'PROFESSOR':<22}{'TABLET':<10}{'RETIRADA':<18}{'DEVOLUCAO':<18}BATERIA (ret > dev)")
    print("-" * 85)
    for h in linhas:
        dev_bat = f"{h['bateria_devolucao']}%" if h["bateria_devolucao"] is not None else "-"
        print(f"{h['nome']:<22}{h['codigo']:<10}{para_tela(h['retirada']):<18}"
              f"{para_tela(h['devolucao']):<18}{h['bateria_retirada']}% > {dev_bat}")


def mostrar_observacoes():
    with conectar() as con:
        linhas = con.execute(
            """SELECT o.data, t.codigo, COALESCE(p.nome, '-') AS nome, o.texto
               FROM observacoes o
               JOIN tablets t ON t.id = o.tablet_id
               LEFT JOIN professores p ON p.id = o.professor_id
               ORDER BY o.data DESC""").fetchall()
    print()
    for o in linhas:
        print(f"[{para_tela(o['data'])}] {o['codigo']} ({o['nome']}): {o['texto']}")
    if not linhas:
        print("Nenhuma observacao registrada.")


# ------------------------------------------------------------------
# NOVO: leitor RFID (ESP32)
# O ESP32 so manda "dispositivo + uid". Quem decide o que a leitura significa e
# este codigo:
#   tag de professor                      -> abre uma "sessao" (ex.: 30 s) naquele armario
#   tag de tablet livre + sessao aberta   -> retirada
#   tag de tablet emprestado              -> devolucao (bateria fica "a confirmar")
# A sessao continua aberta apos cada retirada, entao um professor pode pegar
# varios tablets seguidos com um unico cracha.
# ------------------------------------------------------------------
_trava = threading.Lock()
_sessoes = {}          # dispositivo -> (tag_professor, nome, expira_em)
_ultimas = {}          # (dispositivo, uid) -> datetime da ultima leitura (anti-repeticao)
_dispositivos = {}     # dispositivo -> datetime do ultimo sinal de vida
_retiradas = {}        # uid do tablet -> datetime exato da ultima retirada (o banco guarda so ate o minuto)


def registrar_ping(dispositivo):
    with _trava:
        _dispositivos[dispositivo] = datetime.now()


def listar_dispositivos():
    with _trava:
        copia = dict(_dispositivos)
    agora_dt = datetime.now()
    return [{"dispositivo": d, "visto_ha_seg": int((agora_dt - quando).total_seconds())}
            for d, quando in sorted(copia.items())]


def _registrar_evento(dispositivo, uid, tipo, ok, mensagem):
    with conectar() as con:
        con.execute("INSERT INTO eventos (dispositivo, uid, quando, tipo, ok, mensagem) VALUES (?, ?, ?, ?, ?, ?)",
                    (dispositivo, uid, agora(), tipo, 1 if ok else 0, mensagem))


def processar_leitura(dispositivo, uid):
    """Retorna um dict: {"ok": bool, "acao": str, "msg": str}.
    acao: aguardando_tablet | retirada | devolucao | negado | desconhecida | ignorada | invalida"""
    dispositivo = (dispositivo or "").strip()
    uid = norm_tag(uid)
    if not dispositivo or not uid:
        return {"ok": False, "acao": "invalida", "msg": "Informe dispositivo e uid."}

    agora_dt = datetime.now()
    with _trava:
        _dispositivos[dispositivo] = agora_dt

        # anti-repeticao: o leitor pode ler a mesma tag varias vezes em 1 segundo
        ultima = _ultimas.get((dispositivo, uid))
        _ultimas[(dispositivo, uid)] = agora_dt
        if ultima and (agora_dt - ultima).total_seconds() < DEBOUNCE_SEG:
            return {"ok": True, "acao": "ignorada", "msg": "Leitura repetida ignorada."}

        with conectar() as con:
            prof = con.execute("SELECT * FROM professores WHERE tag_rfid = ?", (uid,)).fetchone()
            tablet = con.execute("SELECT * FROM tablets WHERE tag_rfid = ?", (uid,)).fetchone()
            emp_aberto = None
            if tablet:
                emp_aberto = con.execute(
                    "SELECT * FROM emprestimos WHERE tablet_id = ? AND devolucao IS NULL",
                    (tablet["id"],)).fetchone()

        if prof:
            tipo, ok, acao = "professor", True, "aguardando_tablet"
            expira = agora_dt + timedelta(seconds=SESSAO_LEITURA_SEG)
            _sessoes[dispositivo] = (prof["tag_rfid"], prof["nome"], expira)
            msg = f"Ola, {prof['nome']}. Aproxime a tag do tablet."

        elif tablet:
            tipo = "tablet"
            if emp_aberto:
                # tablet que esta na rua voltando para o armario
                retirada = _retiradas.get(tablet["tag_rfid"])
                if retirada and (agora_dt - retirada).total_seconds() < DEVOLUCAO_MIN_SEG:
                    ok, acao = False, "negado"
                    msg = f"{tablet['codigo']} acabou de ser retirado. Aguarde para devolver."
                else:
                    ok, msg = devolver(tablet["tag_rfid"], tablet["bateria"], tablet["hardware"], pendente=True)
                    acao = "devolucao" if ok else "negado"
            else:
                sessao = _sessoes.get(dispositivo)
                if not sessao or sessao[2] < agora_dt:
                    ok, acao = False, "negado"
                    msg = "Passe o cracha antes de pegar o tablet."
                else:
                    ok, msg = retirar(sessao[0], tablet["tag_rfid"])
                    acao = "retirada" if ok else "negado"
                    if ok:  # mantem a sessao aberta para pegar mais tablets
                        _retiradas[tablet["tag_rfid"]] = agora_dt
                        _sessoes[dispositivo] = (sessao[0], sessao[1],
                                                 agora_dt + timedelta(seconds=SESSAO_LEITURA_SEG))
        else:
            tipo, ok, acao = "desconhecida", False, "desconhecida"
            msg = "Tag nao cadastrada."

        _registrar_evento(dispositivo, uid, tipo, ok, msg)
    return {"ok": ok, "acao": acao, "msg": msg}


def ultima_tag_desconhecida(segundos=300):
    """Ajuda no cadastro: devolve o UID da ultima tag lida que ainda nao esta cadastrada."""
    with conectar() as con:
        ev = con.execute("SELECT uid, quando FROM eventos WHERE tipo = 'desconhecida' ORDER BY id DESC LIMIT 1").fetchone()
    if not ev:
        return None
    if (datetime.now() - datetime.strptime(ev["quando"], FMT_BANCO)).total_seconds() > segundos:
        return None
    return ev["uid"]


# ------------------------------------------------------------------
# Dados de exemplo (pra testar rapido)
# ------------------------------------------------------------------
def carregar_exemplo():
    cadastrar_professor("Ana Souza", "ana@exemplo.com", "P001")
    cadastrar_professor("Carlos Lima", "carlos@exemplo.com", "P002")
    for i, bat in enumerate([95, 60, 15], start=1):
        cadastrar_tablet(f"TAB-{i:02d}", f"T00{i}")
        atualizar_status_tablet(f"TAB-{i:02d}", bat, "ok")
    print("Exemplo carregado: professores P001 e P002 | tablets T001, T002 e T003 (T003 com 15%).")


# ------------------------------------------------------------------
# Menu
# ------------------------------------------------------------------
def resposta(resultado):
    ok, msg = resultado
    print(("\n[OK] " if ok else "\n[ERRO] ") + msg)


def pedir_inteiro(msg):
    try:
        return int(input(msg).strip())
    except ValueError:
        return None


def menu():
    opcoes = """
===== TabControl =====
 1  - Retirar tablet (RFID)
 2  - Devolver tablet
 3  - Reservar horario
 4  - Cancelar reserva
 5  - Listar tablets
 6  - Listar reservas
 7  - Historico de retiradas/devolucoes
 8  - Cadastrar professor
 9  - Cadastrar tablet
10  - Atualizar bateria/hardware (simula ESP32)
11  - Registrar observacao/reclamacao
12  - Ver observacoes
13  - Listar professores
14  - Carregar dados de exemplo
 0  - Sair
"""
    while True:
        print(opcoes)
        op = input("Escolha: ").strip()

        if op == "1":
            tag_p = ler_tag("Aproxime a tag do professor: ")
            tag_t = ler_tag("Aproxime a tag do tablet: ")
            resposta(retirar(tag_p, tag_t))

        elif op == "2":
            tag_t = ler_tag("Aproxime a tag do tablet: ")
            bat = pedir_inteiro("Bateria atual (%): ")
            if bat is None:
                print("\n[ERRO] Bateria invalida.")
                continue
            hw = input("Hardware ok? (s/n): ").strip().lower()
            resposta(devolver(tag_t, bat, "ok" if hw != "n" else "defeito"))

        elif op == "3":
            tag_p = ler_tag("Tag do professor: ")
            codigo = input("Codigo do tablet: ").strip()
            ini = ler_data(input("Inicio (dd/mm/aaaa hh:mm): "))
            fim = ler_data(input("Fim    (dd/mm/aaaa hh:mm): "))
            if not ini or not fim:
                print("\n[ERRO] Data/hora invalida. Use o formato dd/mm/aaaa hh:mm")
                continue
            resposta(reservar(tag_p, codigo, ini, fim))

        elif op == "4":
            rid = pedir_inteiro("ID da reserva: ")
            tag_p = ler_tag("Tag do professor: ")
            if rid is None:
                print("\n[ERRO] ID invalido.")
                continue
            resposta(cancelar_reserva(rid, tag_p))

        elif op == "5":
            mostrar_tablets()
        elif op == "6":
            mostrar_reservas()
        elif op == "7":
            mostrar_historico()

        elif op == "8":
            nome = input("Nome: ").strip()
            email = input("Email: ").strip()
            tag = ler_tag("Tag RFID: ")
            resposta(cadastrar_professor(nome, email, tag))

        elif op == "9":
            codigo = input("Codigo do tablet (ex: TAB-04): ").strip()
            tag = ler_tag("Tag RFID: ")
            resposta(cadastrar_tablet(codigo, tag))

        elif op == "10":
            codigo = input("Codigo do tablet: ").strip()
            bat = pedir_inteiro("Bateria (%): ")
            hw = input("Hardware (ok/defeito): ").strip().lower()
            if bat is None:
                print("\n[ERRO] Bateria invalida.")
                continue
            resposta(atualizar_status_tablet(codigo, bat, hw))

        elif op == "11":
            codigo = input("Codigo do tablet: ").strip()
            tag_p = ler_tag("Tag do professor (Enter pra deixar anonimo): ")
            texto = input("Observacao: ").strip()
            resposta(registrar_observacao(codigo, tag_p, texto))

        elif op == "12":
            mostrar_observacoes()
        elif op == "13":
            mostrar_professores()
        elif op == "14":
            carregar_exemplo()
        elif op == "0":
            print("Ate mais!")
            break
        else:
            print("\nOpcao invalida.")


if __name__ == "__main__":
    criar_tabelas()
    menu()