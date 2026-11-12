"""
TabControl - controle e gerenciamento dos tablets do armario (Centro WEG).

Backend MySQL/Aiven. Configure as variaveis em Servidor_TabControl/.env.
A API e o app Android nao recebem credenciais do banco de dados.
"""

import os
import smtplib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import IntegrityError
from dotenv import load_dotenv

PASTA = os.path.dirname(os.path.abspath(__file__))
DB_ARQUIVO = os.path.join(PASTA, "tabcontrol.db")  # backup legado; nao usado pela aplicacao
load_dotenv(os.path.join(PASTA, ".env"))

FMT_BANCO = "%Y-%m-%d %H:%M"
FMT_TELA = "%d/%m/%Y %H:%M"
BATERIA_MINIMA = 50
BATERIA_MAX_IDADE_MIN = 30
DIAS_MAX_ANTECEDENCIA = 7
TOLERANCIA_RETIRADA_MIN = 5

# Email: se SMTP_HOST ficar None, os emails aparecem no console (simulado).
SMTP_HOST = None
SMTP_PORTA = 587
SMTP_USUARIO = ""
SMTP_SENHA = ""
EMAIL_ADMIN = "administracao@exemplo.com"


class Linha(dict):
    """Linha compativel com acesso por nome (linha['id']) ou indice (linha[0])."""
    def __getitem__(self, chave):
        if isinstance(chave, int):
            return list(self.values())[chave]
        return super().__getitem__(chave)


class CursorCompativel:
    def __init__(self, cursor=None, rowcount=-1):
        self._cursor = cursor
        self.rowcount = rowcount if cursor is None else cursor.rowcount

    def fetchone(self):
        if self._cursor is None:
            return None
        try:
            linha = self._cursor.fetchone()
            return Linha(linha) if linha is not None else None
        finally:
            self._cursor.close()
            self._cursor = None

    def fetchall(self):
        if self._cursor is None:
            return []
        try:
            return [Linha(linha) for linha in self._cursor.fetchall()]
        finally:
            self._cursor.close()
            self._cursor = None

    def close(self):
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None


class ConexaoCompativel:
    """Mantem o padrao con.execute(SQL com ?, parametros) sobre PyMySQL."""
    def __init__(self, conexao):
        self.conexao = conexao

    def execute(self, sql, parametros=None):
        cursor = self.conexao.cursor(DictCursor)
        cursor.execute(sql.replace("?", "%s"), parametros or ())
        if cursor.description is None:
            quantidade = cursor.rowcount
            cursor.close()
            return CursorCompativel(rowcount=quantidade)
        return CursorCompativel(cursor)

    def commit(self):
        self.conexao.commit()

    def rollback(self):
        self.conexao.rollback()

    def close(self):
        self.conexao.close()


@contextmanager
def conectar():
    """Abre conexao TLS validada com MySQL/Aiven e controla a transacao."""
    host = os.getenv("MYSQL_HOST", "").strip()
    porta = int(os.getenv("MYSQL_PORT", "3306"))
    usuario = os.getenv("MYSQL_USER", "").strip()
    senha = os.getenv("MYSQL_PASSWORD", "")
    banco = os.getenv("MYSQL_DATABASE", "defaultdb").strip()
    certificado = os.getenv("MYSQL_SSL_CA", "").strip()

    faltando = [nome for nome, valor in {
        "MYSQL_HOST": host,
        "MYSQL_USER": usuario,
        "MYSQL_PASSWORD": senha,
        "MYSQL_DATABASE": banco,
        "MYSQL_SSL_CA": certificado,
    }.items() if not valor]
    if faltando:
        raise RuntimeError("Configure no arquivo .env as variaveis: " + ", ".join(faltando))
    if not os.path.isfile(certificado):
        raise RuntimeError(
            f"Certificado TLS nao encontrado: {certificado}. "
            "Baixe o CA da Aiven e ajuste MYSQL_SSL_CA."
        )

    conexao = pymysql.connect(
        host=host,
        port=porta,
        user=usuario,
        password=senha,
        database=banco,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
        ssl_ca=certificado,
        ssl_verify_cert=True,
        ssl_verify_identity=True,
    )
    con = ConexaoCompativel(conexao)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _garantir_check(con, tabela, nome, expressao, consulta_invalidos):
    existente = con.execute(
        """SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = ?
             AND CONSTRAINT_NAME = ? AND CONSTRAINT_TYPE = 'CHECK'""",
        (tabela, nome),
    ).fetchone()
    if existente:
        return
    invalidos = int(con.execute(consulta_invalidos).fetchone()["total"])
    if invalidos:
        raise RuntimeError(
            f"Nao foi possivel criar a restricao {nome}: existem {invalidos} registro(s) "
            f"invalidos em {tabela}. Corrija os dados antes de continuar."
        )
    con.execute(f"ALTER TABLE `{tabela}` ADD CONSTRAINT `{nome}` CHECK ({expressao})")


def criar_tabelas():
    """Cria o esquema e aplica migracoes incrementais idempotentes."""
    comandos = [
        """CREATE TABLE IF NOT EXISTS professores (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            nome VARCHAR(255) NOT NULL,
            email VARCHAR(320) NOT NULL UNIQUE,
            tag_rfid VARCHAR(191) NOT NULL UNIQUE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS tablets (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            codigo VARCHAR(191) NOT NULL UNIQUE,
            tag_rfid VARCHAR(191) NOT NULL UNIQUE,
            bateria INT NOT NULL DEFAULT 100,
            bateria_atualizada_em DATETIME NULL,
            hardware VARCHAR(20) NOT NULL DEFAULT 'ok',
            status VARCHAR(30) NOT NULL DEFAULT 'disponivel',
            CONSTRAINT chk_tablets_bateria CHECK (bateria BETWEEN 0 AND 100),
            CONSTRAINT chk_tablets_hardware CHECK (hardware IN ('ok', 'defeito')),
            CONSTRAINT chk_tablets_status CHECK (status IN ('disponivel', 'emprestado', 'manutencao'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS reservas (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            professor_id BIGINT NOT NULL,
            tablet_id BIGINT NOT NULL,
            inicio VARCHAR(19) NOT NULL,
            fim VARCHAR(19) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'ativa',
            CONSTRAINT fk_reservas_professor FOREIGN KEY (professor_id) REFERENCES professores(id),
            CONSTRAINT fk_reservas_tablet FOREIGN KEY (tablet_id) REFERENCES tablets(id),
            CONSTRAINT chk_reservas_status CHECK (status IN ('ativa', 'cancelada', 'concluida')),
            INDEX idx_reservas_tablet_horario (tablet_id, status, inicio, fim)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS emprestimos (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            professor_id BIGINT NOT NULL,
            tablet_id BIGINT NOT NULL,
            retirada VARCHAR(19) NOT NULL,
            devolucao VARCHAR(19) NULL,
            bateria_retirada INT NULL,
            bateria_devolucao INT NULL,
            CONSTRAINT fk_emprestimos_professor FOREIGN KEY (professor_id) REFERENCES professores(id),
            CONSTRAINT fk_emprestimos_tablet FOREIGN KEY (tablet_id) REFERENCES tablets(id),
            CONSTRAINT chk_emprestimos_bateria_retirada CHECK (bateria_retirada IS NULL OR bateria_retirada BETWEEN 0 AND 100),
            CONSTRAINT chk_emprestimos_bateria_devolucao CHECK (bateria_devolucao IS NULL OR bateria_devolucao BETWEEN 0 AND 100),
            INDEX idx_emprestimos_abertos (tablet_id, devolucao)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        """CREATE TABLE IF NOT EXISTS observacoes (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            tablet_id BIGINT NOT NULL,
            professor_id BIGINT NULL,
            data VARCHAR(19) NOT NULL,
            texto TEXT NOT NULL,
            tipo VARCHAR(30) NOT NULL DEFAULT 'observacao',
            resolvido TINYINT NOT NULL DEFAULT 0,
            CONSTRAINT fk_observacoes_tablet FOREIGN KEY (tablet_id) REFERENCES tablets(id),
            CONSTRAINT fk_observacoes_professor FOREIGN KEY (professor_id) REFERENCES professores(id),
            CONSTRAINT chk_observacoes_resolvido CHECK (resolvido IN (0, 1)),
            INDEX idx_observacoes_data (data)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    ]
    with conectar() as con:
        for comando in comandos:
            con.execute(comando)

        # Evolucao segura para quem ja tem o esquema anterior no Aiven.
        coluna = con.execute(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tablets'
                 AND COLUMN_NAME = 'bateria_atualizada_em'"""
        ).fetchone()
        if not coluna:
            con.execute("ALTER TABLE tablets ADD COLUMN bateria_atualizada_em DATETIME NULL AFTER bateria")

        checks = [
            ("tablets", "chk_tablets_bateria", "bateria BETWEEN 0 AND 100",
             "SELECT COUNT(*) AS total FROM tablets WHERE bateria IS NULL OR bateria < 0 OR bateria > 100"),
            ("tablets", "chk_tablets_hardware", "hardware IN ('ok', 'defeito')",
             "SELECT COUNT(*) AS total FROM tablets WHERE hardware NOT IN ('ok', 'defeito') OR hardware IS NULL"),
            ("tablets", "chk_tablets_status", "status IN ('disponivel', 'emprestado', 'manutencao')",
             "SELECT COUNT(*) AS total FROM tablets WHERE status NOT IN ('disponivel', 'emprestado', 'manutencao') OR status IS NULL"),
            ("reservas", "chk_reservas_status", "status IN ('ativa', 'cancelada', 'concluida')",
             "SELECT COUNT(*) AS total FROM reservas WHERE status NOT IN ('ativa', 'cancelada', 'concluida') OR status IS NULL"),
            ("emprestimos", "chk_emprestimos_bateria_retirada", "bateria_retirada IS NULL OR bateria_retirada BETWEEN 0 AND 100",
             "SELECT COUNT(*) AS total FROM emprestimos WHERE bateria_retirada IS NOT NULL AND (bateria_retirada < 0 OR bateria_retirada > 100)"),
            ("emprestimos", "chk_emprestimos_bateria_devolucao", "bateria_devolucao IS NULL OR bateria_devolucao BETWEEN 0 AND 100",
             "SELECT COUNT(*) AS total FROM emprestimos WHERE bateria_devolucao IS NOT NULL AND (bateria_devolucao < 0 OR bateria_devolucao > 100)"),
            ("observacoes", "chk_observacoes_resolvido", "resolvido IN (0, 1)",
             "SELECT COUNT(*) AS total FROM observacoes WHERE resolvido NOT IN (0, 1) OR resolvido IS NULL"),
        ]
        for tabela, nome, expressao, consulta_invalidos in checks:
            _garantir_check(con, tabela, nome, expressao, consulta_invalidos)


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
    except IntegrityError:
        return False, "Ja existe professor com esse email ou essa tag."


def cadastrar_tablet(codigo, tag):
    try:
        with conectar() as con:
            con.execute("INSERT INTO tablets (codigo, tag_rfid) VALUES (?, ?)", (codigo, tag))
        return True, f"Tablet {codigo} cadastrado."
    except IntegrityError:
        return False, "Ja existe tablet com esse codigo ou essa tag."


def atualizar_hardware_tablet(codigo, hardware):
    """Atualiza somente o estado do hardware, sem alterar a bateria automatica."""
    if hardware not in ("ok", "defeito"):
        return False, "Hardware tem que ser 'ok' ou 'defeito'."
    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE codigo = ? FOR UPDATE", (codigo,)).fetchone()
        if not tablet:
            return False, "Tablet nao encontrado."
        novo_status = tablet["status"]
        if hardware == "defeito" and novo_status == "disponivel":
            novo_status = "manutencao"
        elif hardware == "ok" and novo_status == "manutencao":
            novo_status = "disponivel"
        con.execute("UPDATE tablets SET hardware = ?, status = ? WHERE id = ?",
                    (hardware, novo_status, tablet["id"]))
        if hardware == "ok" and tablet["hardware"] != "ok":
            con.execute("""UPDATE observacoes SET resolvido = 1
                           WHERE tablet_id = ? AND tipo = 'defeito' AND resolvido = 0""", (tablet["id"],))
    return True, f"{codigo}: hardware {hardware}, status {novo_status}. A bateria continua sendo atualizada pelo app."


# ------------------------------------------------------------------
# Exclusao de cadastros
# ------------------------------------------------------------------
def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def excluir_professor(prof_id, forcar=False):
    """Retorna (ok, msg) ou (False, msg, True) quando precisa de confirmacao."""
    with conectar() as con:
        prof = con.execute("SELECT * FROM professores WHERE id = ?", (prof_id,)).fetchone()
        if not prof:
            return False, "Professor nao encontrado."
        if con.execute("SELECT 1 FROM emprestimos WHERE professor_id = ? AND devolucao IS NULL",
                       (prof_id,)).fetchone():
            return False, (f"{prof['nome']} esta com um tablet emprestado. "
                           "Registre a devolucao antes de excluir.")

        n_emp = con.execute("SELECT COUNT(*) FROM emprestimos WHERE professor_id = ?", (prof_id,)).fetchone()[0]
        n_res = con.execute("SELECT COUNT(*) FROM reservas WHERE professor_id = ?", (prof_id,)).fetchone()[0]
        n_obs = con.execute("SELECT COUNT(*) FROM observacoes WHERE professor_id = ?", (prof_id,)).fetchone()[0]

        if (n_emp or n_res) and not forcar:
            return False, (f"{prof['nome']} tem {_plural(n_emp, 'emprestimo', 'emprestimos')} no historico e "
                           f"{_plural(n_res, 'reserva', 'reservas')}. Excluir o professor tambem apaga esses registros."), True

        con.execute("DELETE FROM emprestimos WHERE professor_id = ?", (prof_id,))
        con.execute("DELETE FROM reservas WHERE professor_id = ?", (prof_id,))
        con.execute("UPDATE observacoes SET professor_id = NULL WHERE professor_id = ?", (prof_id,))  # fica anonima
        con.execute("DELETE FROM professores WHERE id = ?", (prof_id,))
    return True, f"Professor {prof['nome']} excluido."


def excluir_tablet(tablet_id, forcar=False):
    """Retorna (ok, msg) ou (False, msg, True) quando precisa de confirmacao."""
    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE id = ?", (tablet_id,)).fetchone()
        if not tablet:
            return False, "Tablet nao encontrado."
        if tablet["status"] == "emprestado" or con.execute(
                "SELECT 1 FROM emprestimos WHERE tablet_id = ? AND devolucao IS NULL", (tablet_id,)).fetchone():
            return False, (f"O tablet {tablet['codigo']} esta emprestado. "
                           "Registre a devolucao antes de excluir.")

        n_emp = con.execute("SELECT COUNT(*) FROM emprestimos WHERE tablet_id = ?", (tablet_id,)).fetchone()[0]
        n_res = con.execute("SELECT COUNT(*) FROM reservas WHERE tablet_id = ?", (tablet_id,)).fetchone()[0]
        n_obs = con.execute("SELECT COUNT(*) FROM observacoes WHERE tablet_id = ?", (tablet_id,)).fetchone()[0]

        if (n_emp or n_res or n_obs) and not forcar:
            return False, (f"O tablet {tablet['codigo']} tem {_plural(n_emp, 'emprestimo', 'emprestimos')} no historico, "
                           f"{_plural(n_res, 'reserva', 'reservas')} e "
                           f"{_plural(n_obs, 'observacao', 'observacoes')}. Excluir o tablet tambem apaga esses registros."), True

        con.execute("DELETE FROM emprestimos WHERE tablet_id = ?", (tablet_id,))
        con.execute("DELETE FROM reservas WHERE tablet_id = ?", (tablet_id,))
        con.execute("DELETE FROM observacoes WHERE tablet_id = ?", (tablet_id,))
        con.execute("DELETE FROM tablets WHERE id = ?", (tablet_id,))
    return True, f"Tablet {tablet['codigo']} excluido."


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
        tablet = con.execute("SELECT * FROM tablets WHERE codigo = ? FOR UPDATE", (codigo_tablet,)).fetchone()
        if not prof:
            return False, "Professor nao encontrado."
        if not tablet:
            return False, "Tablet nao encontrado."
        if tablet["status"] == "manutencao" or tablet["hardware"] != "ok":
            return False, "Esse tablet esta em manutencao (defeito registrado)."

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
def _leitura_bateria_recente(tablet, agora_dt=None):
    """True somente quando existe leitura automatica dentro da janela permitida."""
    leitura = tablet.get("bateria_atualizada_em")
    if leitura is None:
        return False
    if isinstance(leitura, str):
        try:
            leitura = datetime.fromisoformat(leitura.replace("T", " "))
        except ValueError:
            return False
    if not isinstance(leitura, datetime):
        return False
    referencia = agora_dt or datetime.now(timezone.utc).replace(tzinfo=None)
    idade_segundos = (referencia - leitura).total_seconds()
    return 0 <= idade_segundos <= BATERIA_MAX_IDADE_MIN * 60


def _mensagem_leitura_bateria(tablet):
    leitura = tablet.get("bateria_atualizada_em")
    if leitura is None:
        return "O app ainda nao enviou uma leitura automatica de bateria para este tablet."
    if isinstance(leitura, datetime):
        data_leitura = leitura.strftime("%d/%m/%Y %H:%M:%S UTC")
    else:
        data_leitura = str(leitura)
    return (f"A ultima leitura automatica foi em {data_leitura} e esta vencida. "
            f"O limite e {BATERIA_MAX_IDADE_MIN} minutos; aguarde a sincronizacao do app.")


def retirar(tag_professor, tag_tablet):
    """Retirada serializada com lock de linha e validacao do frescor da bateria."""
    agora_dt = datetime.now()
    limite = (agora_dt + timedelta(minutes=TOLERANCIA_RETIRADA_MIN)).strftime(FMT_BANCO)

    with conectar() as con:
        prof = con.execute("SELECT * FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        if not prof:
            return False, "Tag de professor nao cadastrada. Acesso negado."

        # FOR UPDATE serializa tentativas simultaneas para o mesmo tablet no InnoDB.
        tablet = con.execute(
            "SELECT * FROM tablets WHERE tag_rfid = ? FOR UPDATE", (tag_tablet,)
        ).fetchone()
        if not tablet:
            return False, "Tag de tablet nao cadastrada."

        agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if tablet["status"] == "emprestado":
            return False, "Esse tablet ja esta emprestado."
        if tablet["status"] == "manutencao" or tablet["hardware"] != "ok":
            return False, "Tablet com problema de hardware / em manutencao."
        if not _leitura_bateria_recente(tablet, agora_utc):
            return False, _mensagem_leitura_bateria(tablet)
        if not BATERIA_MINIMA <= int(tablet["bateria"]) <= 100:
            return False, (f"Emprestimo bloqueado: bateria em {tablet['bateria']}% "
                           f"(minimo {BATERIA_MINIMA}%).")

        emprestimo_aberto = con.execute(
            "SELECT 1 FROM emprestimos WHERE tablet_id = ? AND devolucao IS NULL LIMIT 1",
            (tablet["id"],),
        ).fetchone()
        if emprestimo_aberto:
            return False, "Ja existe um emprestimo em aberto para este tablet."

        reserva = con.execute(
            """SELECT * FROM reservas
               WHERE tablet_id = ? AND status = 'ativa' AND inicio <= ? AND fim >= ?
               ORDER BY inicio LIMIT 1""",
            (tablet["id"], limite, agora_dt.strftime(FMT_BANCO)),
        ).fetchone()
        if reserva and reserva["professor_id"] != prof["id"]:
            return False, "Tablet reservado por outro professor nesse horario."

        # Segunda barreira condicional: somente uma transacao pode mudar disponivel -> emprestado.
        atualizacao = con.execute(
            """UPDATE tablets SET status = 'emprestado'
               WHERE id = ? AND status = 'disponivel' AND hardware = 'ok' AND bateria >= ?
                 AND bateria_atualizada_em IS NOT NULL
                 AND bateria_atualizada_em >= ? AND bateria_atualizada_em <= ?""",
            (tablet["id"], BATERIA_MINIMA,
             agora_utc - timedelta(minutes=BATERIA_MAX_IDADE_MIN), agora_utc),
        )
        if atualizacao.rowcount != 1:
            return False, "A retirada foi bloqueada porque o estado do tablet mudou. Atualize e tente novamente."

        if reserva:
            con.execute("UPDATE reservas SET status = 'concluida' WHERE id = ? AND status = 'ativa'",
                        (reserva["id"],))

        con.execute(
            """INSERT INTO emprestimos (professor_id, tablet_id, retirada, bateria_retirada)
               VALUES (?, ?, ?, ?)""",
            (prof["id"], tablet["id"], agora(), tablet["bateria"]),
        )

    enviar_email(prof["email"], "Retirada de tablet - TabControl",
                 f"Ola {prof['nome']}, voce retirou o tablet {tablet['codigo']} "
                 f"em {agora_dt.strftime(FMT_TELA)} (bateria {tablet['bateria']}%).")
    return True, f"Liberado! {prof['nome']} retirou o {tablet['codigo']}. (fechadura aberta)"


def devolver(tag_tablet, hardware="ok"):
    """Registra a devolucao usando a ultima leitura automatica disponivel."""
    if hardware not in ("ok", "defeito"):
        return False, "Hardware tem que ser 'ok' ou 'defeito'."

    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE tag_rfid = ? FOR UPDATE", (tag_tablet,)).fetchone()
        if not tablet:
            return False, "Tag de tablet nao cadastrada."

        emp = con.execute(
            """SELECT e.*, p.nome, p.email FROM emprestimos e
               JOIN professores p ON p.id = e.professor_id
               WHERE e.tablet_id = ? AND e.devolucao IS NULL
               ORDER BY e.id DESC LIMIT 1 FOR UPDATE""",
            (tablet["id"],),
        ).fetchone()
        if not emp:
            return False, "Nao tem emprestimo em aberto pra esse tablet."

        if tablet["hardware"] != "ok":
            hardware = "defeito"  # defeito registrado durante o emprestimo continua valendo
        bateria_registrada = int(tablet["bateria"])
        novo_status = "disponivel" if hardware == "ok" else "manutencao"
        con.execute("UPDATE emprestimos SET devolucao = ?, bateria_devolucao = ? WHERE id = ?",
                    (agora(), bateria_registrada, emp["id"]))
        con.execute("UPDATE tablets SET status = ?, hardware = ? WHERE id = ?",
                    (novo_status, hardware, tablet["id"]))

    enviar_email(emp["email"], "Devolucao registrada - TabControl",
                 f"Ola {emp['nome']}, a devolucao do tablet {tablet['codigo']} foi registrada.")

    if hardware != "ok" or bateria_registrada < BATERIA_MINIMA:
        enviar_email(EMAIL_ADMIN, f"Atencao: tablet {tablet['codigo']}",
                     f"Devolvido com bateria registrada em {bateria_registrada}% e hardware '{hardware}'. "
                     f"Ultimo usuario: {emp['nome']}.")
    return True, (f"Devolucao do {tablet['codigo']} registrada. Bateria no historico: "
                  f"{bateria_registrada}% (ultima leitura disponivel).")


# ------------------------------------------------------------------
# Observacoes / reclamacoes
# ------------------------------------------------------------------
def registrar_observacao(codigo_tablet, tag_professor, texto, defeito=False):
    """Se 'defeito' for True, o tablet fica bloqueado (retirada e reserva) e vai pra manutencao."""
    texto = texto.strip()
    if not texto:
        return False, "Descreva o que aconteceu."
    with conectar() as con:
        tablet = con.execute("SELECT * FROM tablets WHERE codigo = ? FOR UPDATE", (codigo_tablet,)).fetchone()
        if not tablet:
            return False, "Tablet nao encontrado."
        prof = con.execute("SELECT id FROM professores WHERE tag_rfid = ?", (tag_professor,)).fetchone()
        con.execute("""INSERT INTO observacoes (tablet_id, professor_id, data, texto, tipo)
                       VALUES (?, ?, ?, ?, ?)""",
                    (tablet["id"], prof["id"] if prof else None, agora(), texto,
                     "defeito" if defeito else "observacao"))
        if defeito:
            # emprestado continua emprestado; vai pra manutencao quando for devolvido
            novo_status = "manutencao" if tablet["status"] == "disponivel" else tablet["status"]
            con.execute("UPDATE tablets SET hardware = 'defeito', status = ? WHERE id = ?",
                        (novo_status, tablet["id"]))

    if not defeito:
        return True, "Observacao registrada."

    enviar_email(EMAIL_ADMIN, f"Defeito registrado: tablet {codigo_tablet}", texto)
    if tablet["status"] == "emprestado":
        return True, (f"Defeito registrado. O {codigo_tablet} esta emprestado e vai para "
                      "manutencao assim que for devolvido.")
    return True, f"Defeito registrado. O {codigo_tablet} foi bloqueado e enviado para manutencao."


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
    for i in range(1, 4):
        cadastrar_tablet(f"TAB-{i:02d}", f"T00{i}")
    print("Exemplo carregado: professores P001 e P002 | tablets T001, T002 e T003.")
    print("Cada tablet precisa enviar uma leitura pelo app antes de poder ser retirado.")


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
10  - Atualizar estado do hardware (sem alterar bateria)
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
            hw = input("Hardware ok? (s/n): ").strip().lower()
            resposta(devolver(tag_t, "ok" if hw != "n" else "defeito"))

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
            hw = input("Hardware (ok/defeito): ").strip().lower()
            resposta(atualizar_hardware_tablet(codigo, hw))

        elif op == "11":
            codigo = input("Codigo do tablet: ").strip()
            tag_p = ler_tag("Tag do professor (Enter pra deixar anonimo): ")
            texto = input("Observacao: ").strip()
            defeito = input("E um defeito que impede o uso? (s/n): ").strip().lower() == "s"
            resposta(registrar_observacao(codigo, tag_p, texto, defeito))

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