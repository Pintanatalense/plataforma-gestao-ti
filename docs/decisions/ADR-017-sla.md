# ADR-017 — SLA de chamados

**Status:** Aceito; **implementado em parte**. P4-S1 (tabelas e cálculo de horas úteis, `backend/app/sla/`) foi entregue em 2026-10-23 (#51); P4-S2 (relógio nos chamados) e P4-S3 (job `sla.check`, violações e alertas) estão prontos. P4-S4 (telas) e P4-S5 (indicadores) estão pendentes. Por decisão do usuário (2026-10-26), o SLA é concluído antes da prova de conceito do Plano de Evolução. Os prazos da seção "Valores iniciais" continuam sendo sugestão a confirmar com o usuário.  
*Status anterior: Proposto (2026-10-22), revisado após revisão independente.*  
**Data:** 2026-10-22  
**Depende de:** ADR-013 (worker e outbox já existentes)

## Contexto

Chamados não têm prazo nem medição de tempo. A gestão não consegue dizer quantos chamados foram atendidos no prazo, e o atendente não vê o que está vencendo. O worker (`scheduled_jobs`) e o hub de notificações já existem, então SLA não exige fila, Redis ou serviço novo.

## Decisão

SLA é uma **política** ligada à **categoria** do chamado. Categoria sem política = "Não se aplica": o chamado não tem relógio, nunca aparece como atrasado e fica fora dos indicadores. Nenhuma categoria recebe política automaticamente.

### Definições

- **Solicitante** é o colaborador do chamado (`Ticket.requester_id`, um `Employee`). O autor de uma interação é um `UserAccount`; ele é o solicitante quando `author.employee_id == ticket.requester_id`.
- **Primeira resposta:** primeira `TicketInteraction` com `is_internal = false` cujo autor **não** é o solicitante (`employee_id` nulo ou diferente). Notificações automáticas não geram interação e não contam. Interações também são criadas por `update_ticket` quando a mudança de status leva `notes` (`services.py:316-323`): essas contam como públicas. O ciclo é atualizado no ponto de criação da interação (`add_interaction` e `update_ticket`), no serviço, sem trigger de banco. Limitação aceita: quem abre o próprio chamado não "responde" a ele.
- **Resolução:** passagem para `RESOLVED` (ou `CLOSED`, se nunca houve `RESOLVED`).
- **Atendimento** (`IN_PROGRESS`): informativo; não tem relógio próprio.
- **Chamado sempre nasce `OPENED`** (`create_ticket`) e o criador é sempre o solicitante; o relógio começa na criação. Se um dia houver abertura "em nome de" outra pessoa, o solicitante continua sendo `requester_id`.

### Modelo de dados (migration única, aditiva)

- `sla_calendars` (nome, fuso IANA, horário por dia da semana) e `sla_holidays` (calendário, data, nome).
- `sla_policies` (nome, ativa, calendário, status que pausam, regra de reabertura, % de alerta).
- `sla_policy_targets` (política, prioridade, minutos úteis de primeira resposta e de resolução). Prioridades do sistema: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `ticket_categories.sla_policy_id` (FK nula).
- `ticket_sla_cycles`: um registro por ciclo, com **cópia dos alvos e do calendário** vigentes no início (editar a política depois não muda chamados em andamento), `started_at`, `first_response_due_at`, `resolution_due_at` (UTC), `first_response_at`, `resolved_at`, `paused_at`, minutos restantes, `paused_minutes` acumulados, `state` (`RUNNING|PAUSED|MET|BREACHED|SUPERSEDED`). Único `(ticket_id, cycle)`.
- `sla_breaches` (ciclo, tipo `FIRST_RESPONSE|RESOLUTION`, `due_at`, `detected_at`), único `(ciclo, tipo)`.

### Regras

Tudo que o ciclo precisa (alvos, calendário, regra de reabertura, % de alerta e status de pausa) é **copiado para o ciclo** no início; depois disso nada é lido da política. Por isso editar ou desativar uma política só vale para chamados novos, e o job e os alertas seguem para ciclos abertos mesmo com a política inativa (`sla.check` não filtra por política ativa).

- **Início:** criação do chamado, se a categoria tem política ativa.
- **Pausa:** em status configurados na política; só `PENDING` (padrão) e `IN_PROGRESS` podem ser configurados, nunca `OPENED` (o relógio não pode nascer pausado). Ao pausar guarda os minutos úteis restantes; ao retomar recalcula o vencimento a partir de agora e acumula `paused_minutes`.
- **Vencimento no limite:** viola quando `agora > due_at` (estritamente); resolver exatamente em `due_at` conta como cumprido.
- **Reabertura:** hoje não existe regra no código (qualquer transição fora de `CLOSED` é aceita). Passa a ser definida como `RESOLVED → {OPENED, IN_PROGRESS, PENDING}`. Passados `TICKET_REOPEN_DAYS` dias de `resolved_at`, a transição é rejeitada (422), exceto para quem tem `service_desk.sla.manage`; isto muda o comportamento da API e entra no P4-S2. `CLOSED` continua imutável.
  - `RESTART`: abre novo ciclo só de resolução (a primeira resposta não se reaplica); o anterior fica como está.
  - `CONTINUE`: o ciclo volta a `RUNNING`, preservando violações já registradas e os minutos consumidos; `resolved_at` é limpo e o anterior vai para a auditoria. Uma violação de resolução registrada permanece (único `(ciclo, tipo)`), então o resultado final é `BREACHED`.
- **Mudança de prioridade:** recalcula o vencimento do ciclo aberto com os alvos da nova prioridade, descontando o que já foi consumido: `restante = max(0, novo_alvo - consumido)`, em que `consumido` são os minutos úteis decorridos fora de pausa (`paused_minutes` evita contar pausas antigas). Em ciclo `PAUSED` só os minutos restantes são ajustados; não há vencimento até retomar. Se a nova prioridade já estourou, a violação é registrada na hora da troca, com `due_at` retroativo calculado. Violações já registradas permanecem.
- **Mudança de categoria:** o ciclo atual passa a `SUPERSEDED` (auditado) e um novo parte do `started_at` original com os alvos da nova política, descontadas as pausas acumuladas; pode nascer já vencido, e então a violação é registrada na hora. Violações do ciclo antigo ficam nele. Ciclos `SUPERSEDED` não entram em `MET/(MET+BREACHED)`. Categoria sem política encerra o relógio como "Não se aplica". Só atendente do setor muda categoria (`services.py:279`), então a troca é auditável.
- **Tempo:** tudo em UTC; cálculo em minutos úteis pelo calendário (`zoneinfo`) com funções puras `add_business_minutes` e `business_minutes_between`, testadas isoladamente (fim do expediente, fim de semana, feriado, limite exato).
- **Concorrência:** transição de status e atualização do ciclo na mesma transação, com `SELECT ... FOR UPDATE`; violação idempotente por `UNIQUE` com `ON CONFLICT DO NOTHING`.

### Processamento

Sem fila nova. Prazos são calculados na transição, dentro do serviço de chamados. Um job `sla.check` (a cada 5 minutos) no worker existente marca violações e dispara o alerta de proximidade (`% de alerta`), reaproveitando `scheduled_jobs`, `automation_marks` e o hub de notificações (responsável e gestão).

### Administração e permissão

Telas "Políticas SLA" (CRUD, ativar/desativar, alvos por prioridade) e "Calendários" (horário e feriados); campo "SLA" no formulário de categoria (padrão "Não se aplica"). Permissão nova `service_desk.sla.manage`.

### Valores iniciais (sugestão, a confirmar)

Calendário padrão: segunda a sexta, 08:00–18:00, fuso `America/Sao_Paulo`, sem feriados. Uma política "Padrão" **criada inativa** e sem vínculo com categoria, para o administrador ligar quando quiser:

| Prioridade | Primeira resposta | Resolução |
|---|---|---|
| `CRITICAL` | 30 min | 4 h |
| `HIGH` | 1 h | 8 h |
| `MEDIUM` | 4 h | 24 h |
| `LOW` | 8 h | 48 h |

(minutos/horas **úteis**). Alerta de proximidade em 80%.

### Indicadores

Cumprimento = `MET / (MET + BREACHED)` por período, categoria e prioridade; tempo médio de primeira resposta e de resolução em minutos úteis; chamados em risco (acima do % de alerta). Tudo vem dos fatos persistidos nos ciclos e nas violações, sem recalcular o passado.

## Registro de implementação — P4-S2 (2026-10-26)

Decisões tomadas ao integrar com os chamados (o texto acima continua valendo):

- **Resultado do ciclo:** `BREACHED` quando há **qualquer** violação registrada (primeira resposta ou resolução); `MET` só sem nenhuma. Violação de primeira resposta não muda o estado enquanto o ciclo corre (continua `RUNNING`), só aparece em `breaches`.
- **Retroativo:** ao trocar prioridade ou categoria, se o alvo novo já estourou o vencimento é o instante em que o consumo atingiu o alvo (`início + alvo + minutos pausados`), a violação é registrada na hora e **nunca é apagada** (voltar a uma prioridade folgada não a remove).
- **Categoria com a mesma política:** não abre ciclo novo (os prazos já são os certos). Categoria nova com política em chamado que nunca teve relógio: o ciclo parte da **criação** do chamado.
- **Pausa:** o relógio para em minutos **úteis**; resolver um chamado pausado não é violação, por mais longa que seja a pausa. Chamado reaberto direto para um status de pausa nasce pausado.
- **Reabertura (`TICKET_REOPEN_DAYS`):** vale para **todos** os chamados (com ou sem SLA); a data da resolução vem do ciclo ou, sem ciclo, da auditoria (`ticket.closed` com status `RESOLVED`). Fora do prazo a API responde **422** (`ValidationException`). Como a permissão `service_desk.sla.manage` só nasce no P4-S4 (telas de administração), **por enquanto só administradores** reabrem fora do prazo; o P4-S4 troca isso pela permissão.
- **Primeira resposta** conta no ponto de criação da interação, inclusive a nota de um `PATCH` de status; a nota interna e o próprio solicitante não contam.
- **API:** `GET/POST/PATCH /tickets` devolvem `sla` (`NOT_APPLICABLE` sem política ativa ou sem alvo para a prioridade).
- **Tudo ou nada:** o SLA roda na transação do chamado; se o cálculo falhar, a alteração do chamado também não é gravada (erro 500, nada pela metade). Escolha deliberada, para o relógio nunca divergir do chamado.
- **Chamado encerrado** (`RESOLVED`/`CLOSED`) nunca ganha relógio por troca de categoria. A janela de reabertura é checada **antes** de qualquer campo ser alterado.
- **Pendências conhecidas (menores):** dois pedidos simultâneos de troca de categoria num chamado sem ciclo podem colidir no único `(ticket_id, cycle)` (um deles falha com 500 e pode repetir); no ciclo reaberto por `RESTART` o intervalo "resolvido" entre ciclos conta como consumido numa troca de categoria posterior; a suíte desta etapa roda em SQLite — a validação em PostgreSQL (`FOR UPDATE`, datas com fuso) fica para o CI do PR.
- **Fora desta etapa (P4-S3):** o job `sla.check`, os alertas de proximidade e o registro de violações de chamados que ninguém tocou.

## Registro de implementação — P4-S3 (2026-10-27)

- **Job `sla.check`** (a cada 5 minutos, `app/sla/checker.py`): ciclo `RUNNING` com prazo vencido (`agora > vencimento`) ganha a violação, com o mesmo único `(ciclo, tipo)` das transições. Ciclo pausado não tem prazo e fica de fora; política desativada não para ciclos abertos.
- **Alerta de proximidade:** `ticket.sla_warning` quando faltam `100 - %` do alvo da prioridade (padrão: passou de 80%), **uma vez por prazo** (`first_response_warned_at`/`resolution_warned_at`). A troca de prioridade rearma o alerta. `%` fora de 1–99 desliga o alerta.
- **Aviso de violação:** `ticket.sla_breached` para **toda** violação ainda não avisada (`sla_breaches.notified_at`), venha do job ou de uma transição (ex.: primeira resposta atrasada). A migration marca as violações antigas como avisadas.
- **Quem recebe** (regras semeadas, editáveis em Notificações): alerta → atendente responsável; sem responsável → atendentes do setor (`payload_equals: {"assigned": false}`); violação → responsável, atendentes do setor e o perfil "Gestão".
- **Concorrência:** os ciclos e as violações são lidos com `FOR UPDATE SKIP LOCKED`; um chamado sendo alterado na mesma hora fica para a execução seguinte. Evento no outbox e marca de aviso gravam na mesma transação.
- **Lote:** até 500 ciclos e 500 avisos por execução (o resto vai na próxima).

## Entrega em PRs

1. **P4-S1** modelo + migration + calculadora de tempo útil (funções puras, sem integração).
2. **P4-S2** integração com chamados (ciclo na criação, pausa, retomada, reabertura, mudança de prioridade/categoria); `sla` na resposta da API.
3. **P4-S3** job `sla.check`, violações e alertas.
4. **P4-S4** telas de administração e campo na categoria.
5. **P4-S5** indicadores nas telas de chamados e relatório (substitui `GET /tickets/reports/summary`, hoje sem período).

Cada PR com testes e migration validada em PostgreSQL (`upgrade → downgrade → upgrade` com dados).

## Consequências

- Nada muda para quem não cria política: sem política, o comportamento atual é idêntico.
- Mais tabelas e uma migration; o custo por chamado é uma linha de ciclo.
- Calendário de uma única empresa (sistema é single-tenant, ADR-001); calendários por unidade ficam fora desta versão.

## Alternativas descartadas

- **Relógio calculado na leitura (sem tabela de ciclos):** não guarda histórico nem violação, e muda o passado quando a política muda.
- **Fila/serviço dedicado de SLA:** custo operacional sem necessidade; o worker atual dá conta da carga de uma empresa.
- **SLA por prioridade apenas, sem categoria:** não permite "Não se aplica" nem prazos diferentes por tipo de chamado.
