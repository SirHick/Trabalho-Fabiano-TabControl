# TabControl + Aiven MySQL + monitoramento automático de bateria

Esta é a versão consolidada do projeto. O backend usa MySQL/Aiven, o painel web consulta a API Python e cada tablet Android envia automaticamente sua própria bateria.

## Preparação inicial

1. Faça backup de `Servidor_TabControl/tabcontrol.db`.
2. Abra `Servidor_TabControl/.env.example`, copie-o para `.env` e preencha host, porta, usuário, senha, banco e certificado CA do Aiven. Não inclua credenciais reais no código nem compartilhe o `.env`.
3. Gere o token de bateria com `python -c "import secrets; print(secrets.token_urlsafe(32))"` e cole o resultado em `TABCONTROL_BATTERY_TOKEN` no `.env`.
4. Instale os pacotes: `python -m pip install -r requirements.txt` dentro de `Servidor_TabControl`.
5. Execute `python migrar_sqlite_para_mysql.py` na pasta `Servidor_TabControl` e digite `MIGRAR` somente depois de conferir as contagens.
6. Inicie a API/painel com `python Servidor.py`.
7. No Android Studio, abra `AndroidApp_TabControlBateria`. Configure URL, token idêntico ao do `.env` e o cadastro do tablet correspondente.

## Regras de segurança e bateria

- O endpoint Android `POST /api/bateria` exige o cabeçalho `X-TabControl-Token`.
- A cada leitura recebida, o servidor atualiza `bateria_atualizada_em`.
- A retirada é bloqueada quando não há leitura automática, quando ela tem mais de 30 minutos ou quando a bateria está abaixo de 50%.
- A retirada é protegida por transação e bloqueio da linha no MySQL para impedir duas retiradas concorrentes do mesmo tablet.
- O MySQL valida no próprio banco faixas de bateria e valores permitidos de status/hardware por `CHECK constraints`.
- O painel não oferece campo para digitar percentual. A devolução grava no histórico a última leitura automática disponível.
- Tablets copiados do SQLite começam com `bateria_atualizada_em = NULL`; cada um precisa sincronizar pelo app uma vez antes de poder ser retirado. Isso evita tratar bateria antiga como leitura atual.
- Para operação na internet, use HTTPS com certificado válido, firewall e autenticação do painel. Não exponha a porta HTTP 8000 diretamente. HTTP só deve ser usado em emulador ou rede local confiável.

## Documentação detalhada

- Migração e configuração do Aiven: `LEIA-ME-MIGRACAO-MYSQL.md` e `Servidor_TabControl/README_MIGRACAO_AIVEN.md`.
- Configuração do app: `AndroidApp_TabControlBateria/README.md`.


## Atualização V4.1 — correção do carregamento dos tablets

Esta revisão corrige a formatação de `DATE_FORMAT` no PyMySQL, que impedia a consulta `/api/tablets` e interrompia o carregamento inicial do painel. Também adiciona uma mensagem visível quando uma consulta GET falhar. Para aplicar, encerre o servidor anterior (`Ctrl+C`), extraia esta versão em uma pasta e execute `python Servidor.py`; depois atualize o navegador com `Ctrl+F5`. Não execute novamente a migração SQLite → MySQL se o Aiven já contém os registros.
