# ADR-017 — SLA de chamados

**Status:** Proposto (2026-10-22). Os prazos iniciais da seção "Valores iniciais" são uma sugestão a confirmar com o usuário; todo o resto vale para a implementação.  
**Data:** 2026-10-22  
**Depende de:** ADR-013 (worker e outbox já existentes)

## Contexto

Chamados não têm prazo nem medição de tempo. A gestão não consegue dizer quantos chamados foram atendidos no prazo, e o atendente não vê o que está vencendo. O worker (`scheduled_jobs`) e o hub de notificações já existem, então SLA não exige fila, Redis ou serviço novo.

## Decisão

SLA é uma **política** ligada à **categoria** do chamado. Categoria sem política = "Não se aplica": o chamado não tem relógio, nunca aparece como atrasado e fica fora dos indicadores. Nenhuma categoria recebe política automaticamente.

### Definições

- **Primeira resposta:** primeira interação *pública* de alguém que não é o solicitante. Nota interna e mensagem automática não contam.
- **Resolução:** passagem para `RESOLVED` (ou `CLOSED`, se nunca houve `RESOLVED`).
- **Atendimento** (`IN_PROGRESS`): informativo; não tem relógio próprio.

### Modelo de dados (migration única, aditiva)

- `sla_calendars` (nome, fuso IANA, horário por dia da semana) e `sla_holidays` (calendário, data, nome).
- `sla_policies` (nome, ativa, calendário, status que pausam, regra de reabertura, % de alerta).
- `sla_policy_targets` (política, prioridade, minutos úteis de primeira resposta e de resolução). Prioridades do sistema: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `ticket_categories.sla_policy_id` (FK nula).
- `ticket_sla_cycles`: um registro por ciclo, com **cópia dos alvos e do calendário** vigentes no início (editar a política depois não muda chamados em andamento), `started_at`, `first_response_due_at`, `resolution_due_at` (UTC), `first_response_at`, `resolved_at`, `paused_at`, minutos restantes, `state` (`RUNNING|PAUSED|MET|BREACHED`). Único `(ticket_id, cycle)`.
- `sla_breaches` (ciclo, tipo `FIRST_RESPONSE|RESOLUTION`, `due_at`, `detected_at`), único `(ciclo, tipo)`.

### Regras

- **Início:** criação do chamado, se a categoria tem política ativa.
- **Pausa:** em status configurados na política (padrão `PENDING`, aguardando o solicitante). Ao pausar guarda os minutos úteis restantes; ao retomar recalcula o vencimento a partir de agora.
- **Reabertura** (`RESOLVED` → aberto): regra da política, `RESTART` (novo ciclo só de resolução, a primeira resposta não se reaplica) ou `CONTINUE`. `CLOSED` continua imutável. `TICKET_REOPEN_DAYS` (configuração hoje sem uso) passa a limitar a reabertura.
- **Mudança de prioridade:** recalcula os prazos do ciclo aberto a partir do início do ciclo, com os alvos da nova prioridade; violações já registradas permanecem.
- **Mudança de categoria:** abre novo ciclo (auditado), mantendo o `started_at` original; categoria sem política encerra o relógio como "Não se aplica".
- **Política editada ou desativada:** vale só para chamados novos.
- **Tempo:** tudo em UTC; cálculo em minutos úteis pelo calendário (`zoneinfo`) com funções puras `add_business_minutes` e `business_minutes_between`, testadas isoladamente (fim do expediente, fim de semana, feriado, limite exato).
- **Concorrência:** transição de status e atualização do ciclo na mesma transação, com `SELECT … FOR UPDATE`; violação idempotente por `UNIQUE` com `ON CONFLICT DO NOTHING`.

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

## Entrega em PRs

1. **P4-S1** modelo + migration + calculadora de tempo útil (funções puras, sem integração).
2. **P4-S2** integração com chamados (ciclo na criação, pausa, retomada, reabertura, mudança de prioridade/categoria); `sla` na resposta da API.
3. **P4-S3** job `sla.check`, violações e alertas.
4. **P4-S4** telas de administração e campo na categoria.
5. **P4-S5** indicadores nas telas de chamados e relatório (substitui o `reports/summary` sem período).

Cada PR com testes e migration validada em PostgreSQL (`upgrade → downgrade → upgrade` com dados).

## Consequências

- Nada muda para quem não cria política: sem política, o comportamento atual é idêntico.
- Mais tabelas e uma migration; o custo por chamado é uma linha de ciclo.
- Calendário de uma única empresa (sistema é single-tenant, ADR-001); calendários por unidade ficam fora desta versão.

## Alternativas descartadas

- **Relógio calculado na leitura (sem tabela de ciclos):** não guarda histórico nem violação, e muda o passado quando a política muda.
- **Fila/serviço dedicado de SLA:** custo operacional sem necessidade; o worker atual dá conta da carga de uma empresa.
- **SLA por prioridade apenas, sem categoria:** não permite "Não se aplica" nem prazos diferentes por tipo de chamado.
