"""Migra os registros do tabcontrol.db local para o MySQL/Aiven.

Uso: python migrar_sqlite_para_mysql.py
A ferramenta nao apaga dados do SQLite. Por seguranca, recusa migrar se o MySQL
ja tiver qualquer registro em uma das tabelas de negocio.
"""
import os
import sqlite3
import sys

import tabcontrol as tc

BASE = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE, "tabcontrol.db")
TABELAS = ("professores", "tablets", "reservas", "emprestimos", "observacoes")


def main():
    if not os.path.isfile(SQLITE_PATH):
        print(f"ERRO: banco SQLite nao encontrado: {SQLITE_PATH}")
        sys.exit(1)

    print("1/4 - Criando/verificando as tabelas no MySQL Aiven...")
    tc.criar_tabelas()

    print("2/4 - Verificando se o destino esta vazio...")
    with tc.conectar() as mysql:
        destino = {t: int(mysql.execute(f"SELECT COUNT(*) AS total FROM {t}").fetchone()["total"])
                   for t in TABELAS}
    ocupadas = {t: n for t, n in destino.items() if n}
    if ocupadas:
        print("MIGRACAO CANCELADA: o MySQL ja contem dados nas tabelas abaixo:")
        for tabela, quantidade in ocupadas.items():
            print(f"  - {tabela}: {quantidade} registro(s)")
        print("A ferramenta nao sobrescreve nem mistura dados automaticamente.")
        sys.exit(2)

    print("3/4 - Contando registros na origem SQLite...")
    origem = sqlite3.connect(SQLITE_PATH)
    origem.row_factory = sqlite3.Row
    try:
        contagens = {}
        for tabela in TABELAS:
            existe = origem.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)
            ).fetchone()
            if not existe:
                raise RuntimeError(f"A tabela '{tabela}' nao existe no SQLite de origem.")
            contagens[tabela] = origem.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]

        print("Registros que serao copiados:")
        for tabela, quantidade in contagens.items():
            print(f"  - {tabela}: {quantidade}")
        confirmacao = input("Digite MIGRAR para confirmar a copia (qualquer outra coisa cancela): ").strip()
        if confirmacao != "MIGRAR":
            print("Operacao cancelada. Nenhum registro foi copiado.")
            return

        print("4/4 - Copiando os dados, preservando os IDs originais...")
        # Ordem respeita as chaves estrangeiras.
        with tc.conectar() as mysql:
            for tabela in TABELAS:
                linhas = origem.execute(f"SELECT * FROM {tabela} ORDER BY id").fetchall()
                if not linhas:
                    continue
                colunas = list(linhas[0].keys())
                nomes_sql = ", ".join(f"`{coluna}`" for coluna in colunas)
                placeholders = ", ".join(["%s"] * len(colunas))
                sql = f"INSERT INTO `{tabela}` ({nomes_sql}) VALUES ({placeholders})"
                cursor = mysql.conexao.cursor()
                try:
                    cursor.executemany(sql, [tuple(linha[coluna] for coluna in colunas) for linha in linhas])
                finally:
                    cursor.close()

        print("\nMIGRACAO CONCLUIDA. Conferencia de contagens:")
        with tc.conectar() as mysql:
            divergencias = []
            for tabela in TABELAS:
                quantidade_mysql = int(mysql.execute(f"SELECT COUNT(*) AS total FROM {tabela}").fetchone()["total"])
                print(f"  - {tabela}: SQLite={contagens[tabela]} | MySQL={quantidade_mysql}")
                if quantidade_mysql != contagens[tabela]:
                    divergencias.append(tabela)
        if divergencias:
            print("ATENCAO: diferenca de contagem nas tabelas: " + ", ".join(divergencias))
            sys.exit(3)
        print("Todos os totais conferem. O arquivo tabcontrol.db original foi mantido intacto.")
    finally:
        origem.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"ERRO durante a migracao: {erro}")
        print("O SQLite original nao e alterado. Verifique a conexao, o certificado CA e os logs.")
        sys.exit(1)
