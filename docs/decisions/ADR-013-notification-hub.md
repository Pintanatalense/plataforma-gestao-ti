# ADR-013 — Hub de notificações e automação multicanal

**Status:** Proposto (aguarda aprovação; nenhum código escrito)
**Data:** 2026-10-15
**Base:** commit `a544af7`; `docs/PROJECT_MAP.md`, `docs/AUDIT.md`
**Numeração:** `DEC-013` já é citado em `core/events.py` mas não tem arquivo; este ADR usa o próximo número livre da série ADR.

---

## 1. Contexto

O que existe hoje, verificado (mapa §6.9–6.10, auditoria P1-1, P1-7, P1-14):

| Peça | Situação real |
|---|---|
| `core/events.py` (`EventBus`) | in-process, síncrono; falha de handler é engolida; único consumidor é a auditoria |
| Auditoria | grava duas vezes por evento (direto + listener) |
| Notificação in-app | modelo, REST e WebSocket prontos; **nada cria notificações** |
| E-mail | único canal que dispara (nova interação), SMTP síncrono dentro da requisição, falha só vai para o log |
| WhatsApp saída | tabela `wa_outbox` com anti-ban, **sem worker**; itens ficam `PENDING` |
| WhatsApp entrada | webhook sem autenticação, vínculo por matrícula, resposta devolvida no corpo HTTP |
| WebSocket | `dict` em memória, 4 workers uvicorn |
| Agendamento | não existe (backup, SLA, lembretes) |

O objetivo é: eventos de domínio chegam às pessoas certas pelos canais certos (in-app, e-mail, Slack, WhatsApp, Telegram), com painel de tratamento e base para automações, cada peça encaixável.

**Restrições do projeto:** desenvolvedor solo, self-hosted, Docker, "não adicionar infraestrutura sem necessidade comprovada", custo zero ou baixo.

**Pré-requisitos (da auditoria):** P0-1 (cabeça única no Alembic) e P0-3 (chave secreta) precisam estar resolvidos antes da primeira migration deste ADR; P1-1 (auditoria duplicada) é resolvido pela decisão D1.

---

## 2. Decisões (resumo)

| # | Decisão |
|---|---|
| D1 | Eventos de domínio viram linhas na tabela `domain_events`, gravadas **na mesma transação** da mudança de negócio (padrão outbox). O `EventBus` in-process deixa de ser o mecanismo de entrega. |
| D2 | Um **worker dedicado** (mesma imagem, container `worker`, 1 processo) lê `domain_events`, resolve destinatários e canais, cria `deliveries` e as envia. Só PostgreSQL: **sem Redis, RabbitMQ ou Celery**. |
| D3 | Cada canal é um **adapter** com interface única; adicionar canal = 1 arquivo + 1 linha de registro. |
| D4 | Roteamento por **regras no banco** (evento → audiência → canais) + preferências por usuário + horário de silêncio + escalonamento simples. |
| D5 | Canais de entrada: **camada conversacional independente de transporte** (máquina de estados) + transportes finos; webhooks autenticados; vínculo de identidade por **código de verificação**. |
| D6 | Painel de notificações em **Angular** (reuso de auth e guards) no curto prazo; HTMX só depois de resolver sessão por cookie (ver §9). |
| D7 | Tempo real: **`LISTEN/NOTIFY` do Postgres** mantendo 4 workers de API. |
| D8 | Agendador: **loop dentro do worker** com tabela `scheduled_jobs`; sem cron externo nem APScheduler. |
| D9 | Entrega **at-least-once**, com idempotência por chave única e dead-letter visível. |

---

## 3. D1 — Modelo de eventos

### 3.1 Avaliação do `core/events.py`

| Característica | Problema para este uso |
|---|---|
| Handlers rodam em memória durante a requisição | Se o processo cair depois do `commit` e antes do envio, o evento se perde; se cair antes, o envio pode ocorrer sem `commit` |
| Handler com erro é só logado (`events.py:115-122`) | Falhas de notificação ficam invisíveis |
| Auditoria usa sessão própria (`audit/listener.py`) | Não é atômica com o negócio; gerou a duplicação |
| Estado em memória por worker | Não serve para 4 workers |

**Decisão:** `core/events.py` continua existindo como **API de emissão** (`emit(session, event)`), mas a implementação passa a **inserir uma linha em `domain_events` usando a sessão da requisição**. Quem emite não conhece canais, destinatários nem regras. A auditoria vira **um consumidor** do mesmo registro (elimina a gravação dupla). O `subscribe/on` in-process pode permanecer só para efeitos locais síncronos, mas nenhum fluxo novo depende dele.

Alternativas consideradas:

| Alternativa | Por que não |
|---|---|
| Manter o bus e chamar canais nos handlers | É envio síncrono na requisição: lento (SMTP 10 s), perde mensagem em falha, acopla tudo a um processo |
| Chamar o serviço de notificação direto do service (como já se faz com `EmailService`) | Cada módulo passa a conhecer canais; contraria ADR-004 |
| `LISTEN/NOTIFY` como fila | Não é durável (se ninguém escuta, perde); usado só como **acordar** o worker (D7), nunca como fonte de verdade |
| Event sourcing | Excessivo; só precisamos de log de eventos + entrega |

### 3.2 Estrutura do evento

`domain_events`: `id` (uuid), `event_type`, `entity_type`, `entity_id`, `actor_user_id` (nulo para sistema), `payload` (JSONB, **mínimo**: ids e textos de exibição, nunca copiar dados pessoais em bloco), `priority` (`low|normal|high|critical`), `created_at`, `fanned_out_at` (nulo até o worker expandir).

### 3.3 Catálogo inicial

Nomes em inglês, `entidade.fato_no_passado`. "Existe" = já há ponto de emissão hoje (`service_desk/services.py:824`).

| Evento | Quando | Audiência padrão | Canais padrão | Pré-requisito |
|---|---|---|---|---|
| `ticket.created` | abertura | técnicos do setor responsável; solicitante (confirmação) | in-app, e-mail | existe (reemitir pelo outbox) |
| `ticket.assigned` | atribuição | atribuído; solicitante | in-app (+ canal preferido) | existe |
| `ticket.status_changed` | mudança de status | solicitante; atribuído | in-app, canal preferido | existe |
| `ticket.interaction_added` | resposta pública | solicitante ou atribuído (o outro lado); nota interna só equipe | in-app, e-mail, canal preferido | existe |
| `ticket.sla_breached` / `ticket.sla_warning` | prazo vencido / 80% | atribuído, gestão do setor | in-app, e-mail, escalonamento | **novo**: campo de prazo por prioridade |
| `asset.assigned` | entrega de ativo | colaborador; TI | in-app, e-mail | existe como movimento; emitir |
| `asset.term_pending` | termo não registrado como assinado em N dias | colaborador, técnico | e-mail, canal preferido | **novo**: modelar termo (`asset_terms`), hoje só há anexo por nome de arquivo |
| `asset.warranty_expiring` | 30 e 7 dias | gestão de ativos | e-mail, in-app | job diário (`warranty_expires` existe) |
| `stock.below_minimum` | saldo cruza `min_quantity` para baixo | gestão de estoque | in-app, e-mail | emitir em `StockService.add_movement` com estado "já notificado" para não repetir |
| `inventory.divergence_found` | item conferido ≠ esperado | responsável pelo inventário | in-app, e-mail | emitir ao atualizar item (hoje inventário não calcula divergência) |
| `backup.completed` / `backup.failed` | fim de backup | administradores | `failed`: e-mail + in-app, prioridade `critical` | agendamento (D8) |
| `channel.degraded` | circuito aberto num canal | administradores | in-app, e-mail | gerado pelo próprio hub |
| `conversation.reply` | resposta do bot a mensagem recebida | o remetente | o mesmo canal de entrada | D5 |

Regras: um evento por fato (não por destinatário); a expansão para pessoas acontece no worker (D4); quem emite informa `priority` e `payload`, nunca canal.

---

## 4. D2 — Entrega confiável

### 4.1 Tabelas

| Tabela | Campos principais |
|---|---|
| `domain_events` | ver §3.2 |
| `deliveries` | `id`, `event_id` (FK), `rule_id` (FK nula), `recipient_user_id` (FK nula), `channel`, `address` (destino resolvido no envio), `status` (`PENDING`,`SENDING`,`SENT`,`FAILED`,`DEAD`,`SKIPPED`,`CANCELLED`), `priority`, `message` (JSONB: título, corpo, variáveis), `attempts`, `max_attempts`, `next_attempt_at`, `locked_at`, `locked_by`, `provider_message_id`, `last_error`, `created_at`, `sent_at`, **`idempotency_key` único** = `hash(event_id, rule_id, recipient, channel)` |
| `delivery_attempts` | `delivery_id`, `attempt_no`, `started_at`, `finished_at`, `outcome` (`ok`,`retryable`,`permanent`), `error`, `provider_response` truncado |
| `worker_heartbeat` | `name`, `beat_at`, `info` |

`notifications` (in-app, existente) passa a ser a **caixa de entrada**: o adapter `in_app` grava ali e dispara `NOTIFY`. `wa_outbox` é substituída por `deliveries` (migração de dados desnecessária: está vazia em produção real; itens pendentes podem ser descartados).

### 4.2 Algoritmo do worker (1 processo)

```
loop:
  1. fan-out: SELECT eventos com fanned_out_at IS NULL FOR UPDATE SKIP LOCKED LIMIT n
     -> resolve regras/audiência/preferências/silêncio -> INSERT deliveries (ON CONFLICT idempotency_key DO NOTHING)
     -> marca fanned_out_at   (mesma transação)
  2. dispatch: SELECT deliveries PENDING com next_attempt_at <= now()
     ORDER BY priority, next_attempt_at FOR UPDATE SKIP LOCKED LIMIT n
     -> status=SENDING, locked_at=now(); COMMIT
     -> adapter.send(...) FORA da transação
     -> grava resultado + delivery_attempts
  3. jobs: executa scheduled_jobs vencidos (D8)
  4. recuperação: SENDING com locked_at > 5 min volta a PENDING (processo morreu)
  5. heartbeat
  6. dorme até NOTIFY ou 5 s (o que vier primeiro)
```

### 4.3 Retentativa, idempotência e dead-letter

- Resultado do adapter: `ok`; `retryable` (timeout, 5xx, 429 com `Retry-After`); `permanent` (destinatário inválido, 4xx exceto 429, canal desabilitado).
- Backoff: 30 s, 2 min, 10 min, 1 h, 6 h, com jitter ±20%; `max_attempts=5`. `permanent` ou tentativas esgotadas → `DEAD` (dead-letter), visível no painel com último erro, reenvio manual cria **nova** entrega ligada ao mesmo evento.
- Semântica **at-least-once**: se o processo morrer entre o envio ao provedor e o `COMMIT` do resultado, a mensagem pode duplicar. SMTP, Telegram, Slack e Meta não oferecem chave de idempotência utilizável. Mitigação: `SENDING` é gravado antes do envio e a recuperação do passo 4 é conservadora (5 min); duplicata rara é aceitável para notificações. A unicidade de `idempotency_key` evita duplicar a *criação* por reprocessamento de evento.
- Um evento não é perdido nem reenviado em massa se o worker reiniciar: o estado vive nas tabelas.

### 4.4 É preciso algo além do Postgres?

**Não, hoje.** Volume esperado: dezenas a centenas de entregas por dia (empresa única, equipe de TI). `FOR UPDATE SKIP LOCKED` em Postgres comporta milhares por segundo; o gargalo real são os limites dos provedores (Telegram ~30 msg/s no total, Slack ~1 msg/s por canal, WhatsApp por política anti-ban), não o banco.

| Opção | Ganho | Custo | Decisão |
|---|---|---|---|
| Redis + RQ/Celery | latência menor, retentativas prontas | +1 serviço, +1 ponto de falha, estado duplicado, perda se Redis cair sem persistência, outro painel para monitorar | descartado |
| RabbitMQ | roteamento sofisticado | operação pesada para o volume | descartado |
| Celery com broker Postgres | ecossistema | Celery é grande, o transporte SQLAlchemy/Postgres é pouco usado e frágil | descartado |
| APScheduler/Arq dentro do API | simples | roda em 4 workers → execução duplicada | descartado |

**Gatilho para reavaliar:** > 10 mil entregas/dia sustentadas, necessidade de múltiplos hosts de worker, ou latência fim a fim > 5 s medida como problema.

### 4.5 Um processo só

O worker roda em **1 réplica** de propósito: o limitador de taxa por canal e o circuito (D3) ficam em memória sem coordenação. `SKIP LOCKED` já permitiria escalar depois; se isso acontecer, o limitador precisa migrar para o banco.

Compose: serviço `worker` (mesma imagem, `command: python -m app.worker`), sem portas, `restart: unless-stopped`, healthcheck lendo `worker_heartbeat` (< 60 s).

---

## 5. D3 — Canais como adapters

```python
@dataclass(frozen=True)
class Recipient:            # destino já resolvido
    user_id: UUID | None
    address: str            # e-mail, chat_id, telefone E.164, Slack user/channel id
    display_name: str | None

@dataclass(frozen=True)
class Message:
    title: str
    body_text: str
    body_html: str | None   # só e-mail; já escapado
    link: str | None
    priority: str

@dataclass(frozen=True)
class DeliveryResult:
    outcome: Literal["ok", "retryable", "permanent"]
    provider_message_id: str | None = None
    error: str | None = None
    retry_after_seconds: int | None = None

class ChannelAdapter(Protocol):
    channel: ClassVar[str]
    capabilities: ClassVar[Capabilities]      # rich_text, inbound, max_len, rate_per_second, needs_template_window
    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult: ...
    async def health(self) -> ChannelHealth: ...   # chamada leve, usada pelo painel
```

- Registro: `notifications/channels/__init__.py` com um `dict[str, type[ChannelAdapter]]`.
- **Adicionar um canal:** (1) `channels/<canal>.py` com o adapter e seu schema de configuração (Pydantic); (2) uma linha no registro; (3) configuração via painel. Nenhum arquivo de roteamento, worker ou modelo muda.
- Adapters iniciais: `in_app`, `email` (smtplib em `asyncio.to_thread` ou `aiosmtplib`, avaliar dependência), `telegram` (Bot API via `httpx`), `slack` (Web API `chat.postMessage` via `httpx`), `whatsapp_evolution`, `whatsapp_meta`. Nenhum SDK novo: tudo com `httpx` já instalado.
- Configuração e segredos: tabela `channel_configs` (`channel`, `enabled`, `config` JSONB, `secrets` cifrados). Cifra simétrica (Fernet) com chave `APP_ENCRYPTION_KEY` em variável de ambiente (a lib `cryptography` já vem com `python-jose[cryptography]`). Resolve a senha SMTP e o `api_key` em texto puro de hoje (AUDIT P2-12).
- Taxa e proteção anti-ban: política **por adapter** (`rate_per_second`, e para WhatsApp não oficial os delays/jitter já existentes), aplicada no worker; a configuração anti-ban de `wa_configs` vira parâmetros do adapter WhatsApp em vez de um sistema próprio.
- Circuito: após 5 falhas consecutivas o canal entra em `DEGRADED` por 5 min (entregas ficam `PENDING` com backoff, não consomem tentativas), gera `channel.degraded`; sucesso fecha o circuito.

Alternativas: um módulo grande com `if canal == …` (descartado, é o que se quer evitar); plugins por entry points/descoberta dinâmica (descartado: um registro explícito é mais simples e verificável por quem está iniciando em desenvolvimento).

---

## 6. D4 — Roteamento, preferências, silêncio, escalonamento

### 6.1 Regras

`notification_rules`: `id`, `name`, `enabled`, `event_type` (exato ou prefixo `ticket.*`), `condition` (JSONB opcional: prioridade mínima, categoria, setor), `audience` (JSONB: lista de seletores), `channels` (ordenada), `template_code`, `escalation` (JSONB opcional).

Seletores de audiência: `requester`, `assignee`, `sector_responsible_attendants`, `role:<nome>`, `user:<id>`, `sector_manager`. A resolução usa o `payload`/entidade do evento; lógica em **um** módulo (`notifications/audience.py`), com testes.

Regras vêm semeadas (as da tabela §3.3) e são editáveis no painel; seed idempotente que **não sobrescreve** regras editadas (evita repetir P1-10).

### 6.2 Preferências do usuário

`user_notification_prefs`: por usuário e canal (`enabled`), por categoria de evento (`ticket`, `asset`, `stock`, `system`), `quiet_hours` (início, fim, fuso `America/Fortaleza` padrão), `critical_bypass` (padrão verdadeiro). Regra de precedência: **canal desabilitado pelo usuário** > regra > padrão do sistema; `in_app` não pode ser desligado (é o piso garantido).

`user_channel_addresses`: `user_id`, `channel`, `address`, `verified_at` (entrega a canais externos só com endereço verificado; e-mail vem do `UserAccount.email`).

### 6.3 Silêncio e escalonamento

- Fora do horário: a entrega é criada com `next_attempt_at` = fim da janela; `priority=critical` ignora. Mensagens de conversa (resposta a quem acabou de escrever) ignoram o silêncio.
- Escalonamento (v1, só chamados): a regra define `if_not_acknowledged_after_minutes: X` e `then`: outro canal ou outro destinatário (ex.: gestão do setor). Implementação: ao criar a entrega original, cria-se também uma entrega `escalation` em `next_attempt_at = now + X`, com condição verificada **no momento do envio** (chamado ainda sem primeira interação do atendente / notificação ainda não lida); se a condição não vale, vira `SKIPPED`. Sem motor de workflow.

Alternativas: preferências só globais (descartado: o usuário precisa escolher WhatsApp ou e-mail); motor de regras com DSL (descartado: seletores fixos em JSON cobrem os casos; DSL é abstração sem necessidade comprovada).

---

## 7. D5 — Canais de entrada

### 7.1 Separação de camadas

```
Transporte (por canal)                 Conversação (única)                    Domínio
POST /integrations/<canal>/webhook --> InboundMessage --> ConversationEngine --> ServiceDeskService
   verify() + parse()                   (canal, id externo,    máquina de estados     (mesmas checagens de
                                         texto, msg_id)         + sessão persistida    acesso da API web)
                                                      <-- OutboundMessage (lista) --> deliveries (canal de origem)
```

- `InboundTransport` por canal implementa `verify(request) -> bool` e `parse(request) -> InboundMessage | None`. O endpoint é fino: verifica, converte, **enfileira** e responde 200 vazio. Nunca devolve o texto do bot no corpo.
- `ConversationEngine.handle(msg) -> list[OutboundMessage]` não conhece HTTP nem canal: usa a mesma máquina de estados de hoje (`conversation_service.py`), generalizando `wa_sessions` para `conversation_sessions` (`channel`, `external_id` únicos, `state`, `context`, `user_id`). As respostas viram `deliveries` do canal de origem, com `priority=high` e sem silêncio.
- A engine atua **como o usuário vinculado**: usa `get_ticket_for_user` e permissões reais, portanto não existe mais `author_id = employee.id` (AUDIT P1-16) e não há acesso além do que a web daria.
- Deduplicação: `inbound_messages (channel, message_id UNIQUE)`; reentrega do provedor não executa duas vezes.
- Limite por remetente (ex.: 20 mensagens/min) para impedir inundação de chamados.

### 7.2 Autenticação dos webhooks

| Canal | Mecanismo | Verificação |
|---|---|---|
| Telegram | `secret_token` definido em `setWebhook` | cabeçalho `X-Telegram-Bot-Api-Secret-Token` com `hmac.compare_digest` |
| Slack | Signing Secret | HMAC-SHA256 de `v0:timestamp:body` + janela de 5 min contra replay |
| WhatsApp Meta | App Secret | `X-Hub-Signature-256` (HMAC do corpo bruto) + verificação `hub.verify_token` no GET |
| WhatsApp Evolution | segredo configurado no webhook da instância (cabeçalho customizado) | `compare_digest` com o segredo do canal |

Falha de verificação: 401 sem corpo informativo e contador de métricas. O corpo bruto é lido **antes** do parse para a assinatura.

### 7.3 Vínculo seguro de identidade

Hoje: digitar a matrícula grava o telefone no cadastro (AUDIT P0-5). Novo fluxo:

1. Usuário logado abre "Meus canais" no painel e escolhe o canal.
2. O sistema gera um **código de uso único** (6 caracteres, 10 min, armazenado só como hash, máx. 5 tentativas) e mostra instrução ("envie `/vincular ABC123` ao bot" ou, no Telegram, um link `t.me/<bot>?start=<token>`).
3. A mensagem chega pelo transporte autenticado; a engine casa o código, grava `user_channel_addresses.verified_at` e responde confirmando.
4. Mensagens de remetente **não vinculado** recebem apenas instrução de vínculo (sem revelar se o número existe, sem nomes, sem chamados).
5. Desvincular: pelo painel ou `/desvincular`; troca de telefone exige novo código.

Alternativa descartada: código enviado ao e-mail e digitado no chat; funciona, mas exige a infraestrutura de e-mail funcionando e é pior em UX. Matrícula como segundo fator foi descartada: é identificador, não segredo.

---

## 8. D6 — Painel de notificações

Telas (todas por API REST própria, escopo do usuário ou permissão administrativa):

| Tela | Conteúdo | Permissão |
|---|---|---|
| Caixa de entrada | lista paginada de `notifications` do usuário, filtros (lida/não lida, categoria, período), marcar lidas, link para a entidade | autenticado |
| Meus canais e preferências | endereços vinculados, ativar/desativar por canal e categoria, horário de silêncio, fluxo de código (§7.3) | autenticado |
| Entregas | `deliveries` com status por canal (enviado / falhou / pendente / dead), tentativas, erro, evento de origem; filtros por canal, status, período, destinatário | `notifications.manage` |
| Reenvio | botão "reenviar" em `FAILED`/`DEAD` (cria nova entrega ligada ao evento, auditada) e "cancelar" em `PENDING` | `notifications.manage` |
| Regras | CRUD de `notification_rules`, simulação ("se este evento ocorresse, quem receberia por onde") | `notifications.manage` |
| Saúde dos canais | por canal: habilitado, último envio com sucesso, últimas falhas, contagem `PENDING/DEAD`, estado do circuito, botão "testar" (adapter `health()`), heartbeat do worker | `notifications.manage` |

Permissão nova `notifications.manage` (semeada e acrescentada às listas de roles; **não** reaproveitar `system.backup.manage`, como o SMTP faz hoje).

**Tecnologia do painel — correção da recomendação anterior.** A auditoria sugeriu fazer esta tela em HTMX/Jinja como experimento. Revendo, isso exige **sessão por cookie HttpOnly** (hoje o JWT está em `localStorage`, que o SSR não enxerga) e CSRF; é uma mudança de autenticação inteira, fora do escopo deste ADR. Decisão: **Angular agora**, reaproveitando `authGuard`, `permissionGuard` e componentes do `AdminComponent`. A migração para cookie + SSR pode ser um ADR futuro, e quando ocorrer o painel é o candidato natural a ser reescrito (as telas são finas sobre a API).

---

## 9. D7 — Tempo real

Problema: `NotificationConnectionManager` guarda conexões WS por processo; com 4 workers, uma notificação só chega a quem está no mesmo processo (hoje encoberto porque ninguém emite).

| Opção | Prós | Contras | Decisão |
|---|---|---|---|
| **`LISTEN/NOTIFY`** | zero componente novo; mantém 4 workers de API; o worker de notificação (processo separado) consegue alcançar todos os workers de API | 1 conexão dedicada por worker de API; payload ≤ 8 KB (enviar só ids); notificação perdida se a conexão cair | **Escolhida** |
| Reduzir para 1 worker de API | trivial | `bcrypt` (CPU, ~100–300 ms por login) e `gzip`/geração de HTML bloqueiam o loop de eventos de todos; sem aproveitar vários núcleos; não resolve o worker de notificação ser outro processo | descartada |
| Redis pub/sub | padrão da indústria | novo serviço apenas para isto (viola D2) | descartada |
| Polling do front a cada N s | simples e robusto | latência e carga; serve como *fallback* | usado só como rede de segurança |

Funcionamento: o adapter `in_app` (no worker) grava em `notifications` e executa `NOTIFY inbox, '<user_id>:<notification_id>'`. Cada processo de API mantém uma tarefa com `asyncpg` `add_listener('inbox', …)` e empurra para as conexões locais daquele usuário. **Garantia:** o WS é só aceleração; ao conectar/reconectar o cliente busca as não lidas pela REST, então NOTIFY perdido não perde notificação. Aproveitar para tirar o JWT da query string do WS (ticket de curta duração ou primeira mensagem de autenticação) — hoje vai para o log do Nginx.

---

## 10. D8 — Automações e agendador

### 10.1 Agendador

`scheduled_jobs`: `name`, `schedule` (`every:<min>` ou `daily:HH:MM` no fuso do sistema), `enabled`, `next_run_at`, `last_run_at`, `last_status`, `last_error`. O worker consulta a cada ciclo `WHERE next_run_at <= now() FOR UPDATE SKIP LOCKED`, executa a função registrada, recalcula `next_run_at`. Jobs são funções Python registradas num dicionário, como os adapters.

| Opção | Por que |
|---|---|
| **Loop no worker + tabela** | zero dependência, persistente, visível/editável no painel, não duplica com várias réplicas |
| cron do host/`supercronic` chamando CLI | mais um mecanismo fora do banco, sem visibilidade no painel |
| APScheduler | jobs em memória ou store extra; dependência para dois tipos de agenda |
| `pg_cron` | extensão que a imagem `postgres:16-alpine` não traz |
| Celery beat | exige o resto do Celery |

Sem expressão cron completa: `every` e `daily` cobrem os casos abaixo. Se surgir necessidade real, adiciona-se depois.

### 10.2 Automações priorizadas (valor ÷ complexidade)

| # | Automação | Valor | Complexidade | Depende de |
|---|---|---|---|---|
| 1 | **Backup agendado + alerta de falha** (`backup.failed` crítico) | alto: hoje não existe backup automático (AUDIT P1-13) | baixa: job que chama `BackupService.create_backup` | worker, e-mail/in-app |
| 2 | **Estoque abaixo do mínimo** | alto | baixa: emitir em `add_movement` ao cruzar o limite, com marca para não repetir | outbox |
| 3 | **Chamado sem atendimento / SLA** (`warning` e `breached`) | alto | média: definir prazo por prioridade, campo `due_at` no chamado | decisão de SLA (ver §14) |
| 4 | **Garantia vencendo** (30 e 7 dias) | médio | baixa: job diário sobre `warranty_expires` | worker |
| 5 | **Termo não assinado** | médio | média-alta: exige modelar o termo (emissão, assinatura, vínculo à movimentação); hoje não existe no backend | tabela `asset_terms` |
| 6 | **Divergência de inventário** | médio | média: o inventário hoje não calcula divergência | regra de conciliação |
| 7 | Retenção/limpeza (eventos e entregas > 90 dias, backups) | operacional | baixa | worker |

Uma automação só é entregue quando o evento que ela emite existe de fato; não se cria notificação para um fato que o sistema não consegue detectar.

---

## 11. D9 — Custos e operação

> Preços e limites dos provedores mudam; os valores abaixo são ordem de grandeza e **precisam ser conferidos nas tabelas oficiais antes da escolha final**.

| Canal | Custo | Risco / limite | Deploy | Quando cai |
|---|---|---|---|---|
| In-app | zero | — | nenhum | piso garantido; entrega acontece mesmo com os outros fora |
| E-mail (SMTP) | depende do provedor; contas pessoais (Gmail) têm cota diária baixa e podem bloquear, usar SMTP corporativo/transacional | SPF/DKIM/DMARC afetam entrega | configuração no painel | retentativa com backoff; falha visível; alerta ao admin |
| Telegram Bot API | gratuito | ~30 msg/s no total, ~1 msg/s por chat; usuário precisa iniciar a conversa com o bot | só um token; webhook HTTPS público ou *long polling* (sem exposição, bom para rede interna) | idem; circuito |
| Slack (app/bot) | API gratuita; depende do plano do workspace | ~1 msg/s por canal; app precisa ser instalado e aprovado no workspace | token + signing secret; webhook HTTPS ou Socket Mode | idem |
| WhatsApp Evolution (não oficial) | sem custo por mensagem; precisa de um número dedicado e uma sessão pareada | **não oficial: risco real de banimento do número** e de quebra a cada atualização do WhatsApp; sem SLA | container extra (Evolution) compartilhando o Postgres no schema `evolution` | sessão cai e exige novo QR code; as entregas ficam `PENDING`/`DEAD` e o admin é alertado |
| WhatsApp Meta Cloud API (oficial) | cobrança por mensagem, por categoria (conferir a tabela atual); mensagens iniciadas pela empresa fora da janela de 24 h exigem **templates aprovados** | aprovação de conta Business e de templates; conformidade; sem banimento por uso normal | webhook HTTPS público obrigatório, verificação por assinatura | falhas por 4xx explícitos; mais previsível |

**Recomendação de WhatsApp:** Meta Cloud API para qualquer uso que a empresa considere crítico; Evolution apenas se o custo for impeditivo e o risco de banimento for aceito explicitamente (adapter existe para os dois, o roteamento permite usar WhatsApp só como canal opcional com e-mail/in-app como piso). Decisão do cliente no §14.

**O que monitorar** (todos exibidos em "Saúde dos canais" e expostos em `/api/v1/health`): idade da entrega `PENDING` mais antiga, contagem `DEAD`, taxa de falha por canal na última hora, estado do circuito, heartbeat do worker, tamanho de `domain_events` sem `fanned_out_at`. Alertas do próprio hub (`channel.degraded`, `worker` parado) sempre por **in-app + e-mail**, nunca só pelo canal que falhou.

**Retenção:** `deliveries`/`domain_events`/`delivery_attempts` por 90 dias (job); `notifications` lidas por 180 dias; configurável.

**LGPD:** payload mínimo; mensagens externas não devem conter dados sensíveis além de título/identificador e link para o sistema; endereços de canal têm finalidade e base legal registradas na política da empresa.

---

## 12. Plano incremental

Cada fase vira **uma branch e um PR** com commits semânticos; cada uma entrega valor sozinha. Fase 0 é pré-requisito, não parte deste ADR.

| Fase | Entrega | Útil sozinha porque… | Principais itens |
|---|---|---|---|
| **0** | Correções P0/P1 da auditoria (ordem aprovada) | sistema instala e fica seguro | Alembic, secret key, anexos, webhook fechado, etc. |
| **A** | Outbox + worker + `in_app` + `e-mail` + auditoria unificada + backup agendado com alerta | o sino passa a funcionar de verdade; falha de backup avisa | `domain_events`, `deliveries`, `worker`, `channel_configs` (cifrados), regras semeadas, `LISTEN/NOTIFY`, remoção do `Dispatcher` e do envio SMTP síncrono, healthcheck do worker |
| **B** | Painel (Angular) | admin enxerga e trata entregas; usuário configura preferências | telas da §8, permissão `notifications.manage` |
| **C** | Telegram (saída e entrada) + camada conversacional + vínculo por código | primeiro canal externo gratuito; base reutilizável | `ConversationEngine`, `conversation_sessions`, `inbound_messages`, `user_channel_addresses` |
| **D** | WhatsApp refeito sobre a base (Meta e Evolution como adapters) | substitui o código atual inseguro | remoção de `wa_outbox`/`wa_sessions`/webhook antigo; migração de templates |
| **E** | Slack | para equipes que usam Slack | adapter + transporte |
| **F** | Automações restantes | alertas proativos | estoque mínimo, SLA, garantia, termo, inventário, retenção |

Ordem sugerida **validada com ajustes**: (1) o backup agendado entra na fase A, não na F, porque só depende de e-mail/in-app e fecha o P1-13; (2) a camada conversacional sai junto com o **primeiro** canal de entrada (Telegram), evitando refatorar de novo na fase D; (3) automações que dependem de dados ainda inexistentes (termo, SLA, divergência de inventário) esperam o modelo correspondente.

Compatibilidade: o endpoint `POST /integrations/whatsapp/webhook` atual **deixa de ser montado na Fase 0** (substituído por versão autenticada que só enfileira); o `WhatsAppConversationService` migra na Fase D/C.

---

## 13. Consequências

Positivas: eventos nunca se perdem nem dependem de processo vivo; falha de canal deixa de ser silenciosa; um canal novo é um arquivo; automações e painel usam a mesma base; remove três mecanismos paralelos (bus de auditoria, `wa_outbox`, SMTP síncrono).

Negativas / custos:
- Um container novo (`worker`) a operar e monitorar; latência de segundos (poll/NOTIFY) em vez de imediata.
- Semântica at-least-once: duplicatas raras.
- Mais 8 tabelas e uma chave de cifra (`APP_ENCRYPTION_KEY`) cuja perda impede ler segredos de canais (entra no procedimento de backup).
- `core/events.py` muda de comportamento: os pontos de emissão precisam receber a sessão.
- Conflito com ADR-004 que já existe: ele proíbe import de models entre módulos, e o código atual não respeita. O hub só consome `domain_events` (tabela própria) e IDs; **não** importa models de `service_desk`/`assets`. A resolução de audiência (`sector_responsible_attendants`, etc.) usa consultas por ids no módulo `notifications` e é o ponto a vigiar; se ficar acoplada demais, expõe-se uma interface em `identity/organization` (`get_attendants_of_sector(sector_id)`).

Não resolve: o SLA em si, o modelo de termo, a divergência de inventário e a decisão de plataforma do frontend (cookie + SSR).

---

## 14. Decisões que dependem do responsável

1. **WhatsApp:** Meta Cloud API (oficial, pago por mensagem, mais robusto) ou Evolution (grátis, risco de banimento)? Pode-se começar sem WhatsApp.
2. **Painel:** concordo em fazer em Angular agora (e HTMX só depois de migrar a sessão para cookie)?
3. **SLA:** quais prazos por prioridade (resposta e resolução) e se contam em horário comercial, para a automação 3.
4. **Chave de cifra:** aceita introduzir `APP_ENCRYPTION_KEY` (variável obrigatória; guardada fora do repositório e do backup do banco)?
5. **Fuso e silêncio:** `America/Fortaleza` e janela padrão 20h–07h com `critical` ignorando?
6. **Telegram em rede interna:** *long polling* (sem expor webhook, sem HTTPS público) ou webhook (exige domínio/HTTPS)? Sugestão: long polling no início.

---

## 15. Plano de validação (quando houver código)

- Teste de integração com **Postgres real** (não SQLite): evento → `deliveries` → adapter fake → `SENT`; falha transitória → backoff → `DEAD`; reinício do worker no meio; dois workers sem duplicar (`SKIP LOCKED`).
- Teste de contrato dos transportes: assinatura inválida → 401; replay do Slack → 401; mensagem duplicada → 1 execução.
- Teste de vínculo: código errado 5× bloqueia; remetente não vinculado não vê dados.
- Teste de `LISTEN/NOTIFY` com 2 processos de API e 1 worker.
- `alembic upgrade head` em banco vazio no CI (guarda contra P0-1).
