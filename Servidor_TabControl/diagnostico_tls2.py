"""Testa a validacao do certificado do Aiven em varias configuracoes do Python.
Nao envia usuario nem senha. Rode na pasta Servidor_TabControl, com o .venv ativo:
    python diagnostico_tls2.py
"""
import os
import socket
import ssl
import struct
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
host = os.getenv("MYSQL_HOST", "").strip()
port = int(os.getenv("MYSQL_PORT", "3306"))
ca_path = os.getenv("MYSQL_SSL_CA", "").strip()
PRELUDIO_MYSQL = os.getenv("TLS_TESTE_SEM_MYSQL") is None


def abrir_socket():
    s = socket.create_connection((host, port), timeout=15)
    if PRELUDIO_MYSQL:  # MySQL negocia TLS depois do handshake inicial
        cab = s.recv(4)
        s.recv(struct.unpack("<I", cab[:3] + b"\0")[0])
        caps = 0x0001 | 0x0200 | 0x0800 | 0x8000
        s.sendall(struct.pack("<I", 32)[:3] + b"\x01"
                  + struct.pack("<IIB", caps, 2 ** 24, 45) + b"\0" * 23)
    return s


def contexto(strict=True, hostname=True, partial=False):
    ctx = ssl.create_default_context(cafile=ca_path)  # igual ao que o PyMySQL faz
    if strict:
        ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    else:
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    if partial:
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    ctx.check_hostname = hostname
    return ctx


def testar(rotulo, ctx):
    s = abrir_socket()
    try:
        tls = ctx.wrap_socket(s, server_hostname=host)
        print(f"  OK     - {rotulo}")
        tls.close()
    except ssl.SSLCertVerificationError as e:
        print(f"  FALHOU - {rotulo}\n           {e.verify_message} (codigo {e.verify_code})")
    except Exception as e:
        print(f"  ERRO   - {rotulo}\n           {type(e).__name__}: {e}")
    finally:
        s.close()


print("Python:", sys.version.split()[0], "|", ssl.OPENSSL_VERSION)
print("Host:", host, "| Porta:", port)
print("CA:", ca_path, "| existe:", os.path.isfile(ca_path))
default = ssl.create_default_context()
print("Strict ligado por padrao neste Python:", bool(default.verify_flags & ssl.VERIFY_X509_STRICT))
print("\nResultados (cada linha e um teste independente):")
testar("A) padrao (o que o seu codigo usa hoje)", contexto())
testar("B) sem VERIFY_X509_STRICT", contexto(strict=False))
testar("C) sem strict + PARTIAL_CHAIN", contexto(strict=False, partial=True))
testar("D) padrao, sem checar nome do host", contexto(hostname=False))
