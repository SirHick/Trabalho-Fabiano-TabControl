# TabControl — migração de SQLite para Aiven MySQL

Esta versão muda o sistema inteiro para MySQL na nuvem. A interface web e o app Android continuam falando com a API Python; **o Android não recebe usuário, senha nem conexão direta ao MySQL**.

## 1. Faça uma cópia de segurança

1. Feche o TabControl.
2. Copie `tabcontrol.db` para um local seguro. A ferramenta de migração não altera esse arquivo, mas mantenha a cópia como contingência.
3. Se a senha do Aiven já foi compartilhada em mensagens, troque-a no painel Aiven antes de continuar. Não coloque a senha no código, no GitHub ou em mensagens.

## 2. Instale os requisitos

Abra o terminal na pasta `Servidor_TabControl`:

```bash
python -m venv .venv
```

No Windows:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

No macOS/Linux, ative com `source .venv/bin/activate` e depois instale `requirements.txt`.

## 3. Configure o Aiven

No painel Aiven, abra o serviço MySQL e confirme que está ativo. Copie o **host, port, user e database** mostrados no painel. Baixe o certificado CA/TLS disponibilizado pelo serviço e salve-o na pasta `certs` da raiz `TabControl_Aiven` (o pacote já inclui um arquivo `certs/ca.pem`; confirme que ele é o CA atual do seu serviço).

Copie `.env.example` para um arquivo chamado `.env` na mesma pasta e preencha os valores reais:

```dotenv
MYSQL_HOST=host-exato-fornecido-pelo-aiven
MYSQL_PORT=22552
MYSQL_USER=avnadmin
MYSQL_PASSWORD=sua_nova_senha
MYSQL_DATABASE=defaultdb
MYSQL_SSL_CA=C:/caminho/completo/TabControl_Aiven/certs/ca.pem
TABCONTROL_BATTERY_TOKEN=
TABCONTROL_PORT=8000
```

Gere o token fora do código com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copie o resultado para `TABCONTROL_BATTERY_TOKEN` no `.env`. Use pelo menos 32 caracteres e mantenha o mesmo valor para configurar o app Android. Nunca coloque o token no GitHub nem envie junto do ZIP público.

- O host e a porta acima são exemplos de formato; use os valores exibidos no painel da sua instância.
- `MYSQL_SSL_CA` precisa apontar para o certificado CA baixado. No Windows, barras `/` funcionam no caminho.
- Não inclua aspas ao redor dos valores, salvo se a própria senha exigir cuidado especial com caracteres. Se a senha tiver `#`, espaços ou caracteres de interpretação do `.env`, consulte a sintaxe do `python-dotenv` ou gere uma senha compatível.
- Não compartilhe o arquivo `.env`. Ele está listado no `.gitignore`.

## 4. Migre os registros locais

Antes de iniciar a interface, execute:

```bash
python migrar_sqlite_para_mysql.py
```

A ferramenta:

1. testa a conexão TLS com o MySQL;
2. cria as tabelas necessárias;
3. recusa continuar se alguma tabela de negócio no MySQL já tiver registros, para não duplicar nem misturar dados;
4. mostra a contagem de registros do SQLite;
5. só copia depois que você digitar exatamente `MIGRAR`;
6. preserva os IDs e as relações entre professores, tablets, reservas, empréstimos e observações;
7. compara as contagens depois da cópia.

A ordem de cópia respeita as chaves estrangeiras. Se houver falha durante a cópia, a transação de dados é revertida e o SQLite original permanece intacto. A criação das tabelas pode permanecer no MySQL, o que é seguro: rode novamente a ferramenta depois de corrigir o problema. Se a migração já tiver inserido dados, a proteção de destino ocupado impedirá uma segunda cópia automática; não apague tabelas manualmente sem confirmar primeiro o estado dos dados.

## 5. Inicie o TabControl

Depois que a migração terminar e as contagens conferirem:

```bash
python Servidor.py
```

Abra `http://127.0.0.1:8000`. O servidor cria/verifica as tabelas no MySQL ao iniciar e todas as consultas e alterações do sistema passam a usar o banco Aiven. **O arquivo `tabcontrol.db` não é mais consultado pela aplicação normal**; ele fica como backup da origem.

## 6. Configure o Android

- Emulador Android no mesmo computador: use `http://10.0.2.2:8000` no campo de endereço do servidor do app.
- Tablet físico na mesma rede Wi-Fi: use o IP local do computador que executa `Servidor.py`, por exemplo `http://192.168.x.x:8000`, e configure o firewall para permitir a conexão na rede privada. O servidor escuta interfaces de rede para viabilizar esse acesso; permita a porta 8000 apenas em redes confiáveis.
- O envio de bateria exige token, mas o painel e as demais rotas ainda são uma aplicação de uso interno e não implementam autenticação completa nem HTTPS nativo. **Não encaminhe a porta 8000 diretamente para a internet.** Para acesso remoto, coloque a API atrás de um reverse proxy com HTTPS válido, firewall e autenticação para o painel; use no Android o endereço HTTPS. HTTP deve ficar restrito ao emulador ou a uma rede local confiável.

O app continua usando `GET /api/tablets` e `POST /api/bateria`; não precisa de credenciais do MySQL nem de alteração para a migração do banco.

## 7. Teste de aceitação

1. Confirme que a ferramenta mostrou contagens iguais para SQLite e MySQL.
2. Inicie `Servidor.py` sem erro de conexão.
3. Abra o painel e verifique professores, tablets, histórico e observações.
4. No app Android, clique em **Buscar cadastros no banco**.
5. Selecione o tablet correto e ative o monitoramento.
6. Confira se o percentual da bateria muda no painel.
7. Confirme que a coluna `bateria_atualizada_em` muda a cada envio do app.
8. Aguarde mais de 30 minutos sem sincronização e confirme que a retirada é bloqueada; ao receber uma nova leitura, confirme que a liberação volta a ser possível quando a bateria estiver em 50% ou mais.
9. Tente enviar a bateria sem token e com token incorreto; ambos devem receber HTTP 401.
10. Cadastre um registro de teste e confirme que ele continua presente depois de reiniciar o servidor.

## Correção do painel (V4.1)

A consulta de tablets usa `DATE_FORMAT` para expor a hora da última leitura de bateria. Como o PyMySQL aplica a interpolação de parâmetros `%` do Python, os sinais de porcentagem do formato MySQL precisam aparecer duplicados no código (`%%Y`, `%%m`, etc.). O MySQL recebe os especificadores originais (`%Y`, `%m`, etc.). O painel também valida as respostas das consultas e mostra um aviso quando a API não consegue carregar os dados, em vez de exibir contadores zerados sem explicação.

Após substituir os arquivos, encerre o servidor anterior com `Ctrl+C` e inicie novamente com `python Servidor.py`. Atualize o navegador com `Ctrl+F5`.

## Solução de problemas

- **`MYSQL_SSL_CA` não encontrado:** confira se o arquivo CA foi baixado e se o caminho no `.env` está correto.
- **Access denied:** confirme usuário, senha atual e permissões no painel Aiven. Não cole a senha em logs ou mensagens.
- **Can't connect / timeout:** verifique se o serviço Aiven está ativo e se host e porta foram copiados corretamente.
- **Destino já contém registros:** a migração foi interrompida de propósito. Confira o banco de destino antes de decidir como proceder; a ferramenta não apaga dados.
- **Token ausente/inválido:** confira `TABCONTROL_BATTERY_TOKEN` no `.env` e informe o mesmo valor no app Android. O servidor exige token com pelo menos 32 caracteres.
- **Tablet bloqueado por leitura antiga:** confirme que o app está vinculado ao código correto, tem rede e mostra uma sincronização concluída. A retirada exige uma leitura recebida nos últimos 30 minutos.
- **O painel não abre:** veja se o Python iniciou sem erro e se a porta configurada está livre.
