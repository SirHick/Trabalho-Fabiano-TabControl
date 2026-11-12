# TabControl — migração completa para Aiven MySQL

Este pacote altera o backend Python para usar MySQL na nuvem. O aplicativo Android continua enviando a bateria para a API Python; ele **não** se conecta diretamente ao banco.

## Arquivos importantes

- `Servidor_TabControl/tabcontrol.py`: camada de banco migrada para MySQL.
- `Servidor_TabControl/Servidor.py`: API e interface do TabControl; continua usando as funções do `tabcontrol.py`.
- `Servidor_TabControl/migrar_sqlite_para_mysql.py`: importa os cinco conjuntos de registros SQLite para o MySQL, preservando os IDs.
- `Servidor_TabControl/.env.example`: modelo de configuração, sem credenciais reais.
- `Servidor_TabControl/requirements.txt`: dependências Python.
- `Servidor_TabControl/tabcontrol.db`: banco SQLite original incluído no pacote; mantenha uma cópia de segurança antes de começar.

## 1. Proteja a conta Aiven

A senha anterior foi compartilhada em uma conversa. Troque-a no painel da Aiven antes de executar a migração. Não envie a senha nova em mensagens, não a coloque no código e não publique o arquivo `.env`.

No painel Aiven, confirme que o serviço MySQL está ativo. Copie o host, porta, usuário e nome do banco mostrados na tela do serviço. Baixe o certificado CA/TLS disponibilizado pela Aiven e guarde-o localmente. A conexão do projeto valida o certificado; não desative a verificação TLS.

## 2. Prepare o arquivo `.env`

1. Entre na pasta `Servidor_TabControl`.
2. Faça uma cópia de `.env.example` e renomeie a cópia para `.env`.
3. Abra `.env` e substitua os valores de exemplo pelos valores do seu painel Aiven:

```dotenv
MYSQL_HOST=host-exibido-no-painel.aivencloud.com
MYSQL_PORT=22552
MYSQL_USER=avnadmin
MYSQL_PASSWORD=COLOQUE_A_NOVA_SENHA_AQUI
MYSQL_DATABASE=defaultdb
MYSQL_SSL_CA=C:/caminho/para/ca.pem
TABCONTROL_BATTERY_TOKEN=
TABCONTROL_PORT=8000
```

Gere um token com `python -c "import secrets; print(secrets.token_urlsafe(32))"` e coloque-o em `TABCONTROL_BATTERY_TOKEN`. O mesmo valor será informado na configuração inicial do app Android. O token é independente das credenciais do banco.

Use o host/porta/usuário/banco exatos do painel. `MYSQL_SSL_CA` deve apontar para o certificado CA baixado. Em caminhos Windows, use barras invertidas duplicadas (`\\`) ou barras normais (`/`). O arquivo `.env` está listado no `.gitignore`.

## 3. Instale as dependências

Abra o terminal do PyCharm ou do Windows na pasta `Servidor_TabControl` e execute:

```bash
python -m pip install -r requirements.txt
```

Se o Windows usa o comando `py`, pode usar `py -m pip install -r requirements.txt`.

## 4. Faça backup do SQLite

Antes da migração, pare o servidor antigo e copie `tabcontrol.db` para um local seguro, por exemplo `tabcontrol-backup-antes-migracao.db`. Não apague o arquivo original: ele é a cópia local para recuperação.

## 5. Migre os dados

**Importante:** o script só importa quando as cinco tabelas do destino MySQL estão vazias. Ele não apaga nem sobrescreve dados no MySQL. Se já houver registros, pare e use um banco vazio no serviço Aiven ou planeje uma conciliação antes de prosseguir.

Na pasta `Servidor_TabControl`, execute:

```bash
python migrar_sqlite_para_mysql.py
```

O script cria as tabelas necessárias e copia `professores`, `tablets`, `reservas`, `emprestimos` e `observacoes`, preservando os IDs e respeitando as relações entre elas. Ao final, mostra a quantidade importada por tabela. Se houver erro, a transação de inserção é revertida; o SQLite permanece intacto.

## 6. Valide a migração

No painel/cliente MySQL, execute:

```sql
SELECT COUNT(*) FROM professores;
SELECT COUNT(*) FROM tablets;
SELECT COUNT(*) FROM reservas;
SELECT COUNT(*) FROM emprestimos;
SELECT COUNT(*) FROM observacoes;
```

Compare os totais com os informados pelo script. Confira alguns professores e tablets e confirme que histórico, reservas e observações estão presentes.

## 7. Inicie o TabControl

Com `.env` configurado e a migração validada, execute `Servidor.py` na pasta `Servidor_TabControl`:

```bash
python Servidor.py
```

A interface continuará abrindo no navegador local. O servidor usa MySQL para cadastros, empréstimos, reservas, histórico, observações e leituras de bateria. O Android continua usando a URL da API Python que você configurar no app.

## 8. Sobre acesso remoto e produção

O app Android **não deve** receber host, usuário ou senha do MySQL. Ele envia dados apenas à API. O endpoint Android `POST /api/bateria` exige `X-TabControl-Token`, mas o painel e as demais rotas ainda não têm autenticação completa nem HTTPS nativo. Não exponha a porta 8000 diretamente à internet. Para tablets fora da rede local, publique a API atrás de HTTPS, firewall e autenticação do painel, e configure a URL HTTPS no Android.

## Resolução rápida de problemas

- **Variáveis ausentes:** confira se o arquivo se chama exatamente `.env` e está na pasta `Servidor_TabControl`.
- **Certificado não encontrado:** confira o caminho em `MYSQL_SSL_CA` e se o arquivo CA foi baixado do painel Aiven.
- **Access denied:** revise usuário/senha no painel e atualize a senha se necessário.
- **Can't connect / timeout:** confirme serviço ativo, host e porta corretos, e acesso de rede permitido no Aiven.
- **Destino não vazio:** o script interrompe a migração de propósito para evitar duplicação; não apague tabelas com dados sem fazer backup e decidir conscientemente o que preservar.

## 9. Novas regras da versão consolidada

- Cada POST de bateria grava também `bateria_atualizada_em` com o horário de recebimento do servidor.
- Retirada somente é permitida com leitura automática nos últimos 30 minutos e bateria entre 50% e 100%. Sem leitura ou com leitura antiga, o bloqueio ocorre também no backend, não apenas na tela.
- A retirada usa `SELECT ... FOR UPDATE` e um `UPDATE` condicional na mesma transação InnoDB, protegendo contra duas retiradas simultâneas.
- O esquema inclui `CHECK constraints` para bateria, hardware, status de tablet, status de reserva e baterias do histórico. A inicialização adiciona coluna e restrições em bancos existentes sem apagar registros.
- O painel web não permite editar percentual manualmente. A devolução usa a última leitura automática disponível para o histórico; não exige digitar a bateria.
- Os registros trazidos do SQLite começam sem timestamp de bateria. Faça a primeira sincronização de cada tablet com o app antes de liberar a retirada.
