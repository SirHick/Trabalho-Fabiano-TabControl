"""
Simula o ESP32 sem precisar do hardware: manda leituras para o servidor,
exatamente como o firmware vai mandar. Serve para testar a rede e o fluxo.

Exemplos (servidor rodando):
    python simular_esp32.py --ping
    python simular_esp32.py 04A3B2C1 T001          # cracha e depois tablet (retirada)
    python simular_esp32.py T001                    # so o tablet (devolucao, se estiver emprestado)

Configuracao: usa TABCONTROL_API_KEY do arquivo .env (ou --chave) e --url.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))


def ler_chave_do_env():
    """Le o .env do mesmo jeito que o servidor (aceita aspas, espacos e BOM do Bloco de Notas)."""
    try:
        with open(os.path.join(PASTA, ".env"), encoding="utf-8-sig") as f:
            for linha in f:
                linha = linha.strip()
                if "=" not in linha or linha.startswith("#"):
                    continue
                nome, valor = linha.split("=", 1)
                if nome.strip() == "TABCONTROL_API_KEY":
                    return valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get("TABCONTROL_API_KEY", "")


def enviar(url, chave, rota, corpo):
    req = urllib.request.Request(url + rota, data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json", "X-API-Key": chave})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except OSError as e:
        return 0, {"msg": f"Sem conexao com o servidor ({e}). Confira IP, porta e firewall."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("uids", nargs="*", help="UIDs na ordem em que seriam passados no leitor")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--chave", default=ler_chave_do_env())
    ap.add_argument("--dispositivo", default="armario-01")
    ap.add_argument("--ping", action="store_true", help="so testa a conexao e a chave")
    ap.add_argument("--pausa", type=float, default=1.5, help="segundos entre leituras")
    a = ap.parse_args()
    url = a.url.rstrip("/")

    if a.ping or not a.uids:
        status, r = enviar(url, a.chave, "/api/ping", {"dispositivo": a.dispositivo})
        print(f"[{status}] {r.get('msg')}")
        if status == 401:
            print("A chave enviada (%d caracteres) e diferente da que o servidor carregou.\n"
                  "Confira o .env e REINICIE o Servidor.py depois de qualquer alteracao nele." % len(a.chave))
        sys.exit(0 if status == 200 else 1)

    for i, uid in enumerate(a.uids):
        if i:
            time.sleep(a.pausa)
        status, r = enviar(url, a.chave, "/api/leitura", {"dispositivo": a.dispositivo, "uid": uid})
        print(f"{uid:<12} [{status}] {r.get('acao', '-'):<18} {r.get('msg')}")
