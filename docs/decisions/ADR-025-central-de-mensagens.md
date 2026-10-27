# ADR-025 — Central de Mensagens: envio manual, modelos, agendamento e estados confirmados sobre o hub existente

**Status:** Aceito (2026-10-27). Implementação por etapas M0–M5 (M6 opcional); ver "Registro de implementação".
**Data:** 2026-10-27
**Origem:** pedido do dono do produto "Evolução do Módulo de Notificações e Gestão de Mensagens" (2026-10-27).
Amplia o [ADR-013](ADR-013-notification-hub.md) (hub), o [ADR-019](ADR-019-canais-de-comunicacao.md) (canais) e o
[ADR-024](ADR-024-worker-agenda.md) (agenda). Não substitui nenhum deles.

## Contexto

O pedido é transformar Notificações numa central de mensagens multicanal **sem reconstruir** o que já funciona. O
levantamento do código (branch `feat/sla-5-indicadores`, `ci-local --all` verde em `1213716`) mostrou que a maior
parte da infraestrutura já existe:

| Já existe | Onde |
|---|---|
| Outbox na mesma transação do negócio (`emit_event` → `domain_events`, acelerado por `pg_notify`) | `notifications/outbox.py` |
| Regras evento → audiência → canais, preferências, horário de silêncio, idempotência | `fanout.py`, `audience.py`, `prefs.py`, `rules_seed.py` |
| Fila persistente `deliveries` (PENDING, SENDING, SENT, DEAD, SKIPPED, CANCELLED), prioridade, `SKIP LOCKED`, espera crescente com jitter, `retry_after`, adiamento sem gastar tentativa, circuito por canal, recuperação de SENDING travado, `delivery_attempts` | `dispatcher.py` |
| Canais: in-app, e-mail (SMTP), Telegram, WhatsApp (Evolution e Meta), Slack, Web Push; segredos cifrados (Fernet) | `channels/`, `channel_store.py` |
| Mensagem direta só para endereço verificado; respostas rápidas do chamado (`wa_templates`) | `direct.py`, `whatsapp/` |
| Agenda persistente com concessão, uma execução por job, subprocesso e nova tentativa | `jobs.py`, `job_runner.py` |
| Robô (abre/consulta chamados como o usuário vinculado), entrada deduplicada, resposta pela fila | `conversation/` |
| Painel: entregas com filtros e tentativas, reenvio de DEAD e cancelamento de PENDING (auditados), regras com simulador, saúde dos canais, agenda | `admin_router.py`, `features/notifications/` |

Lacunas reais:

1. **"Entregue" não existe.** `SENT` significa "o gateway aceitou". Os webhooks da Evolution (só `MESSAGES_UPSERT`) e
   da Meta não leem confirmações; o SMTP não trata devoluções.
2. **Envio manual** só existe para o WhatsApp do solicitante a partir do chamado. Não há vários destinatários,
   prévia, envio de teste nem histórico por envio.
3. **Modelos genéricos** não existem: os dos eventos estão em código (`templates.py`); `wa_templates` é só WhatsApp e
   só chamado.
4. **Agendamento de mensagens** não existe (a agenda do worker roda jobs, não mensagens).
5. **Gateways:** limites são constantes no código e controlados por processo; o estado do circuito só existe na
   memória do worker; não há declaração de capacidades; a verificação periódica de saúde só cobre o WhatsApp.
6. **Escalonamento e canal alternativo** foram desenhados no ADR-013 §6.3 e nunca implementados.
7. **Eventos sem notificação:** entrega/devolução de equipamento (`ticket.asset_delivered`/`returned`) só vão para a
   auditoria; falha final de job só é avisada para o backup.

## Decisão

### 1. Tudo passa pelo hub existente

Nenhuma fila, agendador, laço de worker ou mecanismo de envio novo. Mensagem manual ou agendada vira, por
destinatário, uma `deliveries` ligada a um `domain_events` já expandido (como `direct.py` faz hoje) e é enviada pelo
mesmo `Dispatcher`, com as mesmas retentativas, circuito, ritmo e painel. O agendamento é **um job** a mais na agenda
do ADR-024.

### 2. `SENT` continua significando "aceito pelo gateway"

O painel, os testes e o teto por hora do WhatsApp contam `SENT`. Redefini-lo quebraria todos. A confirmação do
provedor fica numa coluna nova, `deliveries.provider_status` (`accepted`, `delivered`, `read`, `failed`) com
`provider_status_at`, preenchida só por integrações que de fato informam (Evolution `MESSAGES_UPDATE`, Meta
`statuses`, a confirmar na homologação C5 do ADR-019). Canal sem confirmação fica sem `provider_status` e a tela diz
"Aceita pelo gateway", nunca "Entregue".

### 3. Entidades novas (só acréscimos)

| Tabela | Papel |
|---|---|
| `message_templates` | Modelo reutilizável: nome, código, canais, assunto, corpo em marcação neutra mínima (negrito, itálico, link, lista), variáveis permitidas. `wa_templates` continua como respostas rápidas do chamado |
| `outbound_messages` | Um envio (manual, agendado ou teste): autor, canal, modelo, conteúdo final, destinatários pedidos, contadores, `idempotency_key` única. Resume o envio e sobrevive à limpeza de 90 dias das entregas |
| `message_schedules` | Agendamento único ou recorrente (diário, dias da semana, dia do mês), janela de horário, calendário do SLA opcional (dias úteis e feriados), regra para dia não útil (pular ou próximo útil), `next_run_at`, `version` para edição concorrente |
| `deliveries` (+ colunas anuláveis) | `message_id` (agrupa as entregas de um envio), `provider_status`, `provider_status_at` |

### 4. Prévia é o que o adapter envia

A formatação por canal já existe dentro dos adapters (ex.: `whatsapp_evolution.render_text`). A prévia chama essas
mesmas funções; o editor só oferece o que o adapter declara em `Capabilities` (ampliada com formatação, anexos,
digitação, confirmação de entrega). Nada de recurso fictício: o Slack não tem "digitando" para bots, o webhook do
Discord só publica em canal.

### 5. Garantias

- **Sem duplicidade na criação:** POST de envio exige `Idempotency-Key`; cada ocorrência de agendamento usa a chave
  única `schedule_id|instante`; `next_run_at` avança na mesma transação que cria a ocorrência; a reivindicação usa
  `SKIP LOCKED`.
- **Entrega "pelo menos uma vez"** (ADR-013 §4.3) continua: se o worker cair entre o envio e o registro, o provedor
  pode receber duas vezes. A Evolution não aceita chave de idempotência. Isso fica documentado, não prometido.
- **Ocorrência perdida** durante uma parada: enviada atrasada dentro de uma tolerância (padrão 1 h); fora dela é
  pulada e registrada.
- **Envio em massa** (risco de banimento na Evolution): teto de destinatários por envio e por hora, configurável só
  para baixo; somente endereços verificados — telefone digitado em cadastro nunca recebe.
- **Não bloqueia o negócio:** quem origina continua só gravando na fila; envio sempre no worker.

### 6. Permissões e auditoria

Permissões novas (catálogo, risco "alteração"; nenhuma crítica): `notifications.messages.send`,
`notifications.messages.schedule`, `notifications.messages.read`. A migration as concede **só** aos perfis que já
têm `notifications.manage`. Quem só tem `send` alcança usuários dos setores visíveis no `AccessContext` e vê os
próprios envios. Envio, cancelamento, agendamento (criar, editar, cancelar), reenvio e configuração de gateway passam
pelo `AuditRepository`. A trilha imutável (ADR-023) não muda.

### 7. Regras e automações

Os gatilhos atuais não mudam. Entram: os eventos de equipamento entregue/devolvido no outbox (ao lado da auditoria
já existente), `job.failed` na falha final de um job (exceto o backup, que já tem `backup.failed`), um catálogo de
eventos para a tela de regras, o escalonamento do ADR-013 §6.3 (condição verificada no envio; se não vale mais, a
entrega vira `SKIPPED`) e canal alternativo quando a entrega vira `DEAD`. Chaves novas de condição são opcionais; as
regras semeadas não são sobrescritas.

## Etapas

| Etapa | Conteúdo | Depende de |
|---|---|---|
| M0 | Este ADR; testes de caracterização: forma das respostas de `/notifications/admin/deliveries`, `/rules` e `/integrations/whatsapp/tickets/{id}/send`; roteamento de cada regra semeada (quem recebe, por qual canal) | — |
| M1 | `provider_status`; leitura de confirmações (Evolution, Meta); filtros de origem, endereço e texto; circuito visível | M0 |
| M2 | Capacidades declaradas; `GET /notifications/admin/gateways`; limites ajustáveis (só para baixo); saúde periódica de todos os canais no job existente | M1 |
| M3 | `message_templates`, `outbound_messages`; prévia, envio, teste e cancelamento; aba "Central de mensagens" | M2 |
| M4 | `message_schedules` e o job `messages.schedules` | M3; calendários do SLA (ADR-017) publicados |
| M5 | Eventos novos, catálogo, escalonamento, canal alternativo | M0 |
| M6 (opcional) | Anexos, "digitando" onde a API oferece, Discord por webhook de canal | demanda real |

Cada etapa: um PR, `ci-local` verde, migration só aditiva com downgrade que remove apenas o que for novo, testes da
seção "Validação".

## Validação

- Preservação em todas as etapas: suíte de `tests/notifications`, `tests/sla`, robô (`test_telegram`,
  `test_whatsapp_*`), os testes de caracterização do M0 e `tests/access_control/route_access_snapshot.json`.
- Novos: permissão e isolamento por setor; idempotência do POST; teto de envio em massa; recorrência, dia útil e
  feriado, tolerância após parada; dois workers concorrentes e reinício no meio (PostgreSQL real); `provider_status`
  com webhooks simulados; escalonamento (inclusive `SKIPPED`); specs e build do Angular; smoke da pilha completa.

## Consequências

- A central herda a confiabilidade e o painel do hub; cada canal novo continua sendo "um arquivo em `channels/` + uma
  linha no registro".
- Duas tabelas de modelos convivem (`wa_templates` para respostas rápidas do chamado, `message_templates` para a
  central). Unificar mexeria na tela do chamado sem ganho agora; reavaliar depois do M3.
- O ritmo por canal continua por processo: rodar mais de um contêiner de entregas multiplica os limites. Enquanto
  houver um só (ADR-024), isso basta; se precisar escalar, o limite passa a ser contado no banco.

## Alternativas descartadas

- **Fila ou agendador próprios (Celery, APScheduler, Redis):** duplicariam o que `deliveries` e `scheduled_jobs` já
  fazem com garantias testadas, e trariam dependência e contêiner novos.
- **Redefinir `SENT` como "entregue":** quebra o teto do WhatsApp, o painel e os testes; a coluna separada resolve
  sem regressão.
- **Generalizar `wa_templates`:** a tabela pertence ao módulo WhatsApp, que já importa o hub; o hub importá-la
  criaria dependência circular entre módulos (ADR-004).

## Registro de implementação

### M0 — base de compatibilidade (2026-10-27)

- `tests/notifications/test_compat_baseline.py`: para cada regra semeada, o conjunto exato (regra, pessoa, canal)
  que o fan-out planeja, com Telegram vinculado para exercitar `preferred`; endereço não verificado e canal desligado
  não recebem; campos das respostas de `/notifications/admin/deliveries` (lista e detalhe) e `/rules`. Também congela
  que `ticket.asset_delivered`, `ticket.asset_returned` e `job.failed` não notificam ninguém hoje (o M5 muda isso
  de propósito).
- `test_whatsapp_meta.py`: a resposta de `/integrations/whatsapp/tickets/{id}/send` mantém `status`, `delivery_id` e
  `message`.
- Nenhum código de produção alterado. Observado na caracterização: o responsável que também é atendente do setor
  recebe "novo chamado" e "SLA perto de vencer (sem responsável)" como atendente; a violação de SLA chega uma vez só
  a quem é responsável e atendente ao mesmo tempo (deduplicação por pessoa e canal).

### M1 — histórico e estados confirmados (2026-10-27)

- Migration `d1e2f3a4b5c6d`: `deliveries.provider_status`, `provider_status_at` e índice
  `(channel, provider_message_id)`. Só acrescenta; downgrade remove o índice e as colunas.
- `notifications/receipts.py`: `apply_receipts` acha a entrega por canal e id da mensagem no provedor; o estado só
  avança (accepted < delivered < read) e `failed` não desfaz uma entrega. `deliveries.status` não muda.
- Evolution: o webhook passa a ser registrado com `MESSAGES_UPSERT` e `MESSAGES_UPDATE`; `parse_receipts` lê só as
  mensagens que enviamos (`fromMe`) na nossa instância (SERVER_ACK → accepted, DELIVERY_ACK → delivered, READ/PLAYED →
  read, ERROR → failed). **Instalações já pareadas** passam a receber confirmações depois de clicar *Conectar número*
  outra vez (com o número conectado isso só registra o webhook de novo, sem novo QR). Formato conferido no código da
  v2.3.7; homologação real pendente no C5 do ADR-019.
- Meta: o webhook assinado lê `statuses` (sent → accepted, delivered, read, failed) do nosso `phone_number_id`.
- Painel: `GET /notifications/admin/deliveries` aceita `origin` (rule, direct, conversation, system),
  `provider_status` (inclusive `none`), `address` e `q` (título ou texto; `%` e `_` digitados não são curinga); cada
  item ganhou `provider_status`, `provider_status_at` e `origin` (só acréscimos; o contrato do M0 foi ampliado).
  A tela de entregas mostra SENT como **"Aceita pelo gateway"**, a coluna *Confirmação* e os filtros novos; o filtro de
  canal lista todos os canais.
- **Correção do diagnóstico:** o estado do circuito já era visível (`worker_heartbeat.info.open_circuits`, coluna
  `circuit_open` em `/admin/channels`); não foi preciso mudar nada.
- Limitação aceita: uma confirmação que chega antes de o worker gravar o id da mensagem (milissegundos) é ignorada;
  a seguinte corrige o estado.

### M2 — gateways (2026-10-27)

- `Capabilities` ganhou `formatting`, `attachments`, `typing`, `delivery_receipts`, `read_receipts` e `to_dict()`.
  Declaram o que a nossa integração faz hoje: só o WhatsApp lê confirmações; nenhum canal envia anexo ou "digitando"
  ainda (M6). Formatos: e-mail `html`, WhatsApp `whatsapp`, Slack `slack`, demais `plain`.
- `GET /notifications/admin/gateways`: por canal, ligado/configurado, capacidades e limites (teto, limite do
  administrador, ritmo efetivo; no WhatsApp/Evolution também o intervalo e o teto por pessoa por hora, que continuam
  sendo editados na aba WhatsApp). Nenhum segredo sai por aqui.
- `PUT /notifications/admin/gateways/{canal}/limits`: só reduz (acima do teto → 400; canal sem teto, como a caixa de
  entrada, → 400; `null` volta ao teto); auditado (`notifications.gateway_limits_updated`). Fica em
  `channel_configs.config['limits']`, que `save_channel` preserva quando as abas de cada canal gravam o config do zero.
  O dispatcher relê o limite a cada lote e aplica `min(teto, limite)`.
- Checagem periódica: o job `whatsapp.health_check` (nome mantido, para a agenda e o histórico já existentes) passou a
  checar também e-mail, Telegram, Slack e navegador habilitados, com o mesmo debounce (duas falhas seguidas → um
  `channel.degraded` por queda; voltar a funcionar rearma). Se o circuito do envio já abriu para o canal, não avisa de
  novo. Tempo máximo do job: 60 → 120 s. O e-mail não abre conexão SMTP na checagem (só confere a configuração).
- Tela: aba **Gateways** em *Notificações — administração*.
- Mapa de acesso: duas rotas novas com `perm:notifications.manage`.

### M3 — envio manual, modelos e prévia (2026-10-27)

- Migration `e2f3a4b5c6d7e`: `message_templates`, `outbound_messages`, `deliveries.message_id` (nulo no que já
  existia) e as permissões `notifications.messages.send` e `notifications.messages.read`, concedidas só aos perfis que
  já tinham `notifications.manage` (o Administrador as recebe pelo seed). Downgrade remove tudo isso e não toca nas
  entregas. `notifications.messages.schedule` fica para o M4, junto com o recurso.
- `notifications/messages.py`: marcação neutra (`**negrito**`, `- item`, links) → texto do canal (`*negrito*` no
  WhatsApp e no Slack; sem marcas no texto simples) ou HTML escapado no e-mail (moldura `html_frame`, extraída de
  `templates._html_card` sem mudar a saída dos e-mails atuais). Variáveis `{{nome}}`, `{{email}}`, `{{empresa}}`,
  `{{data}}`, `{{hora}}` são preenchidas por destinatário; as demais o remetente informa, e faltar alguma é 422.
- Alcance: com só `send`, pessoas do próprio setor (sem setor, só a si); com `notifications.manage` ou
  `service_desk.tickets.read_all`, qualquer pessoa ativa. Cada destinatário recebe um resultado na prévia e no
  histórico: `queued`, `no_address` (não vinculou o canal), `out_of_scope`, `inactive`, `unknown`.
- API `/notifications/messages`: `GET /recipients` (canais verificados, nunca o endereço), `POST /preview` (não grava;
  texto pelas funções `render_text` dos próprios adapters), `POST` com `Idempotency-Key` obrigatória (repetir devolve
  o mesmo envio, 200), `POST /test` (só para si; 10 por hora, à parte), `GET`, `GET /{id}`, `POST /{id}/cancel` (só o
  autor ou quem administra; cancela as PENDING), CRUD de `/templates` (só `notifications.manage`). Tetos:
  `MESSAGES_MAX_RECIPIENTS` (50) e `MESSAGES_MAX_PER_HOUR` (20) por pessoa. Envio, cancelamento e modelos auditados.
- Painel de entregas: origem nova `message` (entregas da Central).
- Tela `/notifications/messages` (menu Notificações > Central de mensagens): Nova mensagem (só envia depois da prévia;
  qualquer mudança a invalida; a chave de idempotência vale até o envio dar certo), Histórico e Modelos.
- Não unificado: as respostas rápidas do chamado (`wa_templates`, `whatsapp/template_service.py`) mantêm a própria
  substituição de variáveis, que é específica de chamado.

### M4 — agendamento (2026-10-27)

- Migration `f3a4b5c6d7e8f`: `message_schedules`, `outbound_messages.schedule_id`/`scheduled_for` (nulos no que já
  existia) e a permissão `notifications.messages.schedule`, concedida só aos perfis que já tinham
  `notifications.manage`. Downgrade remove tudo isso; os envios já feitos continuam no histórico.
- Recorrência (`notifications/schedules.py`, funções puras): uma vez (`run_at` com fuso), todo dia, dias da semana ou
  dia do mês (mês mais curto: último dia), sempre num horário `HH:MM` no fuso do agendamento (padrão `APP_TIMEZONE`),
  com início e fim opcionais. Calendário do SLA opcional: dia sem expediente ou feriado é pulado (`skip`) ou vai para
  o próximo dia útil (`next`); várias datas que caem no mesmo dia útil viram uma ocorrência só. O calendário só vale
  para os recorrentes.
- Job `messages.schedules` (a cada minuto): agendamentos vencidos com `SKIP LOCKED`, em lotes; cada ocorrência vira
  um envio `kind = scheduled` pelo mesmo `enqueue` do envio manual, com a chave `schedule_id|instante`, e
  `next_run_at` avança na mesma transação. Testado contra PostgreSQL: quatro execuções simultâneas geram um envio;
  falha no meio não deixa nada pela metade e a execução seguinte envia.
- A cada ocorrência valem as permissões e o setor **atuais** de quem agendou (`load_access_context`): sem conta ativa
  ou sem `schedule`, o agendamento é pausado com o motivo; pessoa que saiu do setor ou desvinculou o canal fica de
  fora; ninguém alcançável ou teto por hora estourado é `failed` e o agendamento segue.
- Parada do worker: a ocorrência sai atrasada até `MESSAGES_SCHEDULE_TOLERANCE_MINUTES` (60); depois é `missed`
  (registrada, não enviada). De várias perdidas seguidas só a mais recente ainda pode sair.
- Desvio do texto do ADR: a "janela de horário" virou horário fixo + tolerância; uma janela separada não acrescentava
  nada com recorrência mínima diária.
- API `/notifications/messages/schedules`: `GET /calendars` (nome e fuso, sem exigir a permissão do SLA),
  `POST /occurrences` (próximas 5 datas), `POST` com `Idempotency-Key`, `GET`, `GET /{id}` (próximos envios e os
  últimos 20 feitos), `PUT /{id}` com `version` (409 se outra pessoa alterou), `POST /{id}/pause|resume|cancel`.
  Retomar vale a partir de agora (o que venceu pausado não sai). Teto `MESSAGES_MAX_ACTIVE_SCHEDULES` (20 abertos por
  pessoa). Criar, editar, pausar, retomar, cancelar e cada envio agendado passam pela auditoria. Calendário do SLA
  usado por agendamento aberto não pode ser excluído (409); dos encerrados, o vínculo é desfeito.
- Agendar usa a busca de pessoas e a prévia do envio, então pede também `notifications.messages.send`.
- Tela: em Nova mensagem, "Quando enviar: Agora / Agendar" (nome, repetição, dias, calendário, "Ver próximas datas";
  só agenda depois da prévia); aba nova Agendamentos (situação, próximo envio, último resultado com o motivo,
  pausar/retomar/cancelar, detalhe com próximos envios e envios feitos). O Histórico mostra o tipo "Agendado".
- Não feito nesta etapa: editar um agendamento pela tela (a API aceita; hoje se cancela e cria outro).
