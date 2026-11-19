# App Android - TabControl Bateria 3.0

O app lê o nível de bateria deste próprio tablet e envia a porcentagem automaticamente à API TabControl. Não há campo para digitar o percentual.

## Abrir e compilar

1. Abra esta pasta no Android Studio (a pasta que contém `settings.gradle.kts`).
2. Aguarde a sincronização do Gradle; a primeira compilação baixa as dependências do WorkManager.
3. Execute no emulador ou no tablet Samsung.

## Configuração inicial (uma vez por aparelho)

1. Deixe `Servidor.py` em execução.
2. Informe o endereço da API: `http://10.0.2.2:8000` no emulador; no tablet físico, use o IP do servidor na rede local ou o endereço HTTPS do servidor publicado.
3. Cole o mesmo `TABCONTROL_BATTERY_TOKEN` configurado no `.env` do servidor. Esse token não é a senha do MySQL.
4. Clique em **Buscar cadastros no banco**, selecione o código que corresponde fisicamente ao tablet e clique em **Ativar monitoramento automático**.

O token é enviado no cabeçalho `X-TabControl-Token` em cada `POST /api/bateria`. O app guarda o token nas preferências privadas da aplicação. Se o token for trocado no servidor, abra a configuração, informe o novo token e ative novamente.

## Segundo plano

O app agenda um envio imediato e uma tarefa periódica do WorkManager com intervalo mínimo de 15 minutos, condicionado à conectividade. O Android pode adiar a execução por economia de energia; o horário real não é garantido. O WorkManager mantém o agendamento após reinicialização, mas um app forçado a parar pelo usuário não executa até ser aberto novamente.

## Importante para a operação

- O servidor grava automaticamente `bateria_atualizada_em` a cada leitura recebida.
- A retirada é bloqueada se nunca houve leitura automática, se a leitura tiver mais de 30 minutos ou se a bateria estiver abaixo de 50%.
- A tela do painel não permite mais digitar a porcentagem. Na devolução, o histórico usa a última leitura recebida automaticamente; nenhuma tela solicita percentual manual.
- Em tablets físicos, configure as otimizações de bateria do Android conforme a política do dispositivo para reduzir atrasos do WorkManager.
- Não envie o token em mensagens públicas, não o inclua no APK como valor fixo e não use HTTP em redes não confiáveis. Para acesso pela internet, use HTTPS (por exemplo, reverse proxy com certificado válido) e mantenha o servidor de desenvolvimento atrás dessa camada.
