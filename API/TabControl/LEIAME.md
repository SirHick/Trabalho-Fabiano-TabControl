# TabControl - Equipe Brokers

Sistema de controle dos tablets do armário (Centro WEG): painel web + API + leitor RFID (ESP32 + PN532).
Só usa a biblioteca padrão do Python (3.9 ou mais novo).

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `tabcontrol.py` | Regras de negócio e banco de dados (SQLite). Também roda como menu de console. |
| `Servidor.py` | Painel web + API. É o que fica rodando na máquina da empresa. |
| `index.html` | Tela do painel (precisa estar na mesma pasta do `Servidor.py`). |
| `.env.example` | Modelo de configuração. Copie para `.env` e preencha. |
| `simular_esp32.py` | Simula o leitor RFID para testar rede e fluxo **sem hardware**. |
| `esp32_tabcontrol/esp32_tabcontrol.ino` | Firmware do ESP32 (Arduino IDE). **Ainda não testado em hardware.** |

## Como rodar

1. Copie `.env.example` para `.env`.
2. Gere a chave do ESP32 e cole em `TABCONTROL_API_KEY`:
   `python -c "import secrets; print(secrets.token_hex(16))"`
3. Defina `TABCONTROL_ADMIN_SENHA` (senha do painel).
4. `python Servidor.py`. O console mostra o endereço para o ESP32 (ex.: `http://192.168.0.10:8000`).
5. Abra o endereço no navegador e entre com o usuário e a senha do `.env`.

O banco `tabcontrol.db` é criado sozinho. Um banco antigo do simulador é atualizado sem perder dados.

## Testar sem o ESP32

```
python simular_esp32.py --ping                 # testa rede + chave
python simular_esp32.py CRACHA TABLET          # retirada (use as tags cadastradas)
python simular_esp32.py TABLET                 # devolução (se o tablet estiver emprestado)
```
Para outra máquina: `--url http://IP_DO_SERVIDOR:8000`.

## Como o leitor funciona

| O que é lido | Situação | Resultado |
|---|---|---|
| Cracha de professor | sempre | abre uma "sessão" de 30 s naquele armário |
| Tag de tablet livre | sessão aberta | **retirada** (a sessão continua aberta: dá para pegar vários tablets) |
| Tag de tablet livre | sem sessão | negado: "Passe o crachá antes" |
| Tag de tablet emprestado | (passou mais de 60 s da retirada) | **devolução** (bateria fica "a confirmar") |
| Tag não cadastrada | sempre | negado; o UID fica disponível no botão "Ler do armário" em Cadastros |

A bateria **não vem do RFID** (Decisão 5D do documento: registro manual). Na devolução pelo leitor o
tablet fica marcado "Conferir bateria" até alguém salvar a leitura no painel.

## Limitações conhecidas

- A fechadura continua independente (Decisão 1A): o sistema registra, mas não abre nem bloqueia a porta.
- O UID do crachá pode ser copiado (risco já registrado no documento de decisões).
- O tráfego é HTTP (sem criptografia). Aceitável em rede interna de piloto; para uso definitivo, colocar HTTPS na frente.
- Se o ESP32 ficar sem rede, a leitura **não é guardada**: ele tenta 3 vezes e sinaliza erro (LED vermelho piscando).
- Os horários são gravados até o minuto.

## Alterações em relação ao simulador original

### tabcontrol.py
- Configurações agora vêm do `.env` / variáveis de ambiente (antes fixas no código), inclusive SMTP.
- Caminho do banco absoluto (`DB_ARQUIVO`): funciona se iniciado de qualquer pasta ou como serviço.
- `conectar()`: espera até 10 s se o banco estiver ocupado e usa modo WAL (painel e ESP32 ao mesmo tempo).
- Nova tabela `eventos` (tudo que o leitor enviou) e nova coluna `emprestimos.bateria_pendente`, criadas automaticamente em bancos antigos.
- Tags padronizadas por `norm_tag()` (maiúsculas, sem `:` ou espaço); tags já cadastradas são convertidas.
- `enviar_email()`: envia em segundo plano (thread), com timeout; suporta porta 465 (SSL).
- `cadastrar_professor`, `cadastrar_tablet`, `registrar_observacao`: validam campos vazios.
- `devolver()`: novo parâmetro `pendente`. `atualizar_status_tablet()`: confirma a bateria pendente e avisa o administrador se estiver baixa.
- Novas: `processar_leitura()`, `registrar_ping()`, `listar_dispositivos()`, `ultima_tag_desconhecida()`.

### Servidor.py
- Escuta em `0.0.0.0` (antes só `127.0.0.1`) e mostra o IP da máquina ao iniciar.
- Login do painel (cookie de sessão HttpOnly, 8 h) e limite de 5 tentativas erradas por minuto.
- Todas as rotas `/api/` exigem login, exceto `/api/leitura` e `/api/ping`, que exigem a chave `X-API-Key`.
- Novas rotas: `/api/leitura`, `/api/ping`, `/api/login`, `/api/logout`, `/api/config`, `/api/eventos`, `/api/dispositivos`, `/api/ultima_tag`.
- Serve `index.html` ou `Index.html` (corrige o 404 em Linux).
- `/api/exemplo` só funciona com `TABCONTROL_DEMO=1`.
- Não abre mais o navegador sozinho (só com `TABCONTROL_ABRIR_NAVEGADOR=1`); recusa corpos grandes; erros inesperados viram resposta JSON.
- Se faltar chave ou senha no `.env`, o servidor não inicia e explica o motivo.

### index.html
- Tela de login e botão Sair; volta ao login se a sessão expirar.
- Limite de bateria vem do servidor (antes o painel dizia 20% e o servidor bloqueava com 50%).
- Nova aba **Leituras** (eventos do ESP32 e leitor online/sem sinal).
- Painel e histórico se atualizam sozinhos a cada 8 s, sem apagar formulários em preenchimento.
- Botão "Ler do armário" nos cadastros preenche a tag com a última tag desconhecida lida.
- Aviso "Conferir bateria" e "a confirmar" no histórico para devoluções feitas pelo leitor.
- "Carregar dados de exemplo" só aparece em modo demo.
