"""
TabControl - controle e gerenciamento dos tablets do armario (Centro WEG)
Equipe Brokers - Implementacao de Negocios Inovadores

Roda direto no PyCharm, so usa biblioteca padrao do Python (sqlite3).
O banco (tabcontrol.db) e criado sozinho na primeira execucao.

A leitura da tag RFID e simulada: voce digita o codigo da tag no console.
Quando o ESP32 + leitor RFID estiverem prontos, e so trocar o input()
da funcao ler_tag() pela leitura real (serial, MQTT, HTTP, etc).
"""

import smtplib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage

# ------------------------------------------------------------------
# Configuracoes
# ------------------------------------------------------------------
DB_ARQUIVO = "tabcontrol.db"

BATERIA_MINIMA = 50          # abaixo disso o emprestimo e bloqueado (%)
DIAS_MAX_ANTECEDENCIA = 7    # evita "reserva muito antecipada"
TOLERANCIA_RETIRADA_MIN = 5 # pode retirar ate 5 min antes do horario reservado

# Email: se SMTP_HOST ficar None, os emails so aparecem no console (simulado)
SMTP_HOST = None             # ex: "smtp.gmail.com"
SMTP_PORTA = 587
SMTP_USUARIO = ""
SMTP_SENHA = ""
EMAIL_ADMIN = "administracao@exemplo.com"

FMT_BANCO = "%Y-%m-%d %H:%M"
FMT_TELA = "%d/%m/%Y %H:%M"


# ------------------------------------------------------------------
# Banco de dados
# ------------------------------------------------------------------
@contextmanager
def conectar():
    con = sqlite3.connect(DB_ARQUIVO)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
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
        """)


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


def ler_tag(msg):
    # Aqui entra a leitura real do RFID depois. Por enquanto, digita.
    return input(msg).strip()


def enviar_email(destino, assunto, corpo):
    if not SMTP_HOST:
        print(f"\n[EMAIL SIMULADO] para: {destino}\n  assunto: {assunto}\n  {corpo}\n")
        return
    try:
        msg = EmailMessage()
        msg["From"] = SMTP_USUARIO
        msg["To"] = destino
        msg["Subject"] = assunto
        msg.set_content(corpo)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORTA) as srv:
            srv.starttls()
            srv.login(SMTP_USUARIO, SMTP_SENHA)
            srv.send_message(msg)
    except Exception as e:
        print(f"Nao consegui enviar o email ({e})")


# ------------------------------------------------------------------
# Cadastros
# ------------------------------------------------------------------
def cadastrar_professor(nome, email, tag):
    try:
        with conectar() as con:
            con.execute("INSERT INTO professores (nome, email, tag_rfid) VALUES (?, ?, ?)",
                        (nome, email, tag))
        return True, f"Professor {nome} cadastrado."
    except sqlite3.IntegrityError:
        return False, "Ja existe professor com esse email ou essa tag."


def cadastrar_tablet(codigo, tag):
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


def devolver(tag_tablet, bateria_atual, hardware="ok"):
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
        con.execute("UPDATE emprestimos SET devolucao = ?, bateria_devolucao = ? WHERE id = ?",
                    (agora(), bateria_atual, emp["id"]))
        con.execute("UPDATE tablets SET status = ?, bateria = ?, hardware = ? WHERE id = ?",
                    (novo_status, bateria_atual, hardware, tablet["id"]))

    enviar_email(emp["email"], "Devolucao registrada - TabControl",
                 f"Ola {emp['nome']}, a devolucao do tablet {tablet['codigo']} foi registrada.")

    if hardware != "ok" or bateria_atual < BATERIA_MINIMA:
        enviar_email(EMAIL_ADMIN, f"Atencao: tablet {tablet['codigo']}",
                     f"Devolvido com bateria {bateria_atual}% e hardware '{hardware}'. "
                     f"Ultimo usuario: {emp['nome']}.")
    return True, f"Devolucao do {tablet['codigo']} registrada."


# ------------------------------------------------------------------
# Observacoes / reclamacoes
# ------------------------------------------------------------------
def registrar_observacao(codigo_tablet, tag_professor, texto):
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