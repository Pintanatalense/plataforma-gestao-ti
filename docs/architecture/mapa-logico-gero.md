# GERO — Mapa Lógico Vivo

**Base:** `Pintanatalense/plataforma-gestao-ti`, `main` @ `e0a6e5c5332ba97a4ce8c35934cd7fdd10910466` (2026-11-08).
**Método:** leitura estática do código extraído de `origin/main` (AST de imports, grep de rotas, tabelas, eventos e testes). **Nenhum teste foi executado.** "Teste protege" = o arquivo existe e descreve a regra, não que passou nesta análise.
**Estado:** v1.0, incorpora a revisão de governança de 2026-11-08 (§7). É um índice de evidências, não fonte de verdade: em divergência com código e testes, vale o código e o mapa é corrigido por PR.
**Caminhos:** `backend/app/…` salvo indicação. Símbolos citados foram conferidos no arquivo. `NV` = não verificado.

Estados: **EXISTE** (código + rota/uso confirmados) · **PARCIAL** · **LEGADO/MORTO** · **PLANEJADO** (sem código).

---

## 1. Como usar (30 segundos)

1. Ache a capacidade na tabela §2 (busque por palavra: `grep -n "palavra" docs/architecture/mapa-logico-gero.md`).
2. Leia **dono**, **contrato reutilizável** e **testes**.
3. Registre no PR: `reutilizar | estender | adaptar | criar`, com a linha do mapa consultada (seção "Reuso e dono das regras" do modelo de PR).
4. Se a coluna "contrato" diz **LACUNA**, não há interface pública segura: estenda o dono, não crie paralelo.

---

## 2. Catálogo de capacidades existentes (validado)

Colunas: dono · onde está · tabelas · consumidores · contrato reutilizável · testes · observação.

| ID | Capacidade | Estado | Dono e código | Tabelas | Fonte de verdade | Consumidores | Contrato reutilizável | Testes que protegem | Observação |
|---|---|---|---|---|---|---|---|---|---|
| CAP-001 | Identidade, perfis, permissões, concessão crítica | EXISTE | `identity/` (`services.py`, `permission_catalog.py`, `critical.py`, `router.py` 24 rotas); autorização em `core/access.py` | `user_accounts`, `roles`, `permissions`, `role_permissions`, `user_roles`, `user_critical_grants`, `password_reset_requests` | Banco (`user_accounts`, `roles`, `user_critical_grants`); permissões definidas em código (`permission_catalog.py`) | todo router, `notifications/audience.py`, `whatsapp` | `core.dependencies.require_permission/require_any_permission`, `core.access.AccessContext` e `has_permission` (admin não recebe permissão crítica por padrão); catálogo único em `identity/permission_catalog.py` | `tests/identity/*` (94), `tests/access_control/test_access_context.py`, `test_permission_split.py`, `test_route_access_snapshot.py` | Novas permissões entram no catálogo; não criar RBAC paralelo |
| CAP-002 | Empresa, unidade, setor, colaborador | EXISTE | `organization/` (`services.py`, `router.py` 21 rotas) | `companies`, `units`, `sectors`, `employees` | Banco (`employees`, `units`, `sectors`, `companies`) | quase todos (FK/relationship) | Modelos `Employee/Unit/Sector` (importados por ~10 módulos); `Employee` 1:1 opcional com `UserAccount` | `tests/organization/test_organization.py` | Cadastro básico, não RH. `Employee.status`: `ATIVO/AFASTADO/DESLIGADO` |
| CAP-003 | Chamados e vinculados (principal/subchamados) | EXISTE | `service_desk/` (`services.py` 1.5k+ linhas, `router.py` 27 rotas, `templates.py`, `idempotency.py`); ADR-026 | `sd_ticket`, `sd_ticket_category`, `sd_ticket_interaction`, `sd_ticket_assets`, `sd_ticket_materials`, `sd_ticket_templates`, `sd_ticket_template_items`, `sd_idempotency_keys` | Banco (`sd_ticket*`) | `sla`, `notifications`, `whatsapp`, `attachments`, `data_transfer` | `ServiceDeskService` (`create_ticket`, `add_children`, `cancel_child`, `replace_child`, `set_child_requirement`, `children_progress`); `Idempotency-Key` em `POST /tickets` e `/tickets/{id}/children` | `tests/service_desk/*` (`test_linked_tickets.py`, `test_ticket_idempotency.py`, `test_ticket_templates.py`, `test_ticket_routing.py`, `test_ticket_creator.py`, `test_ticket_asset_scope.py`, `test_audit_single_write.py`), `tests/test_service_desk.py` | Transição de status é **inline** em `update_ticket` (`services.py:795-800`); não há tabela central de transições |
| CAP-004 | Visibilidade de chamado, notas internas | EXISTE | Regra: `service_desk/access.py::evaluate_ticket_access`; notas: `ServiceDeskService.can_see_internal` (`services.py:176`); escopo: `AccessContext.ticket_scope()` | — | Código (função pura) sobre `sd_ticket` e `AccessContext` | `attachments/access.py`, `whatsapp/router.py`, `notifications/conversation/engine.py` | `evaluate_ticket_access`, `can_see_internal` | `tests/service_desk/test_linked_tickets.py`, `tests/access_control/test_ticket_and_asset_visibility.py` | **Risco conhecido:** `read_all` + `tickets.manage` = atendente de qualquer chamado (`access.py:61`). Ver §5 |
| CAP-005 | SLA de chamados | EXISTE | `sla/` (`service.py::SlaService`, `report.py`, `business_time.py`, `checker`) ; ADR-017 | `sla_policies`, `sla_policy_targets`, `sla_calendars`, `sla_holidays`, `ticket_sla_cycles`, `sla_breaches` | Banco (`sla_policies`, `ticket_sla_cycles`) | `service_desk` (hooks `start/status_changed/canceled/attach`), `notifications` | `SlaService` (`start`, `interaction_added`, `status_changed`, `canceled`, `priority_changed`, `category_changed`, `attach`), `sla_report` | `tests/sla/*` (99) | Todo cálculo de prazo passa por aqui |
| CAP-006 | Cadastro patrimonial de ativos | EXISTE | `assets/` (`services.py::AssetService`, `router.py` 17 rotas); ADR-005 (`technical_specs` JSONB) | `assets`, `asset_categories` | Banco (`assets`) para dados cadastrais e estado atual | `service_desk`, `movements`, `attachments`, `inventory_audit`, `notifications/automations.py` | `AssetService.create_asset/update_asset`, `AssetRepository` (usado por 3 módulos) | `tests/test_assets.py`, `test_assets_lifecycle.py`, `tests/assets/*`, `tests/baseline/test_assets_baseline.py` | `update_asset` altera status/alocação **e** grava movimento (`services.py:95-160`) |
| CAP-007 | Movimentação de ativo (reservar, entregar, devolver, inspecionar) | EXISTE | `movements/services.py::MovementService` (`create_movement`, `reserve_asset`, `cancel_reservation`, `deliver_asset`, `return_asset`, `inspect_asset`) | `asset_movements` | Banco (`asset_movements` = histórico; estado atual em `assets`) | `assets.update_asset`, `service_desk` (8 imports) | `MovementService.*` | `tests/test_assets_lifecycle.py` (6), `test_assets.py` | Ver divergência D-03: duas rotas de mudança de status |
| CAP-008 | Estoque de insumos | EXISTE | `stock/` (`services.py::add_movement` com `with_for_update` em `repository.py:80`) | `stk_categories`, `stk_items`, `stk_movements` | Banco (`stk_items`, `stk_movements`) | `service_desk` (material), `organization`, `notifications` | `StockService.add_movement` | `tests/test_stock.py` (4), `tests/test_stock_concurrency.py` (1, PG real) | Evento `stock.below_minimum` via automação |
| CAP-009 | Inventário periódico (auditoria de inventário) | EXISTE | `inventory_audit/` (`service.py`, `router.py` 7 rotas) | `inventory_audits`, `inventory_audit_items` | Banco (`inventory_audits*`) | frontend | `inventory_audit/service.py` | `tests/test_inventory_audit.py` (2) | Não é trilha de auditoria (CAP-011) |
| CAP-010 | Anexos e download autorizado | EXISTE | `attachments/` (`service.py::AttachmentService`; política em `access.py::ensure_attachment_access`) | `attachments` | Banco (`attachments`) + arquivos em volume | `service_desk` (tickets), `assets` | `ensure_attachment_access` (ponto único; anexo restrito some e dá 404) | `tests/attachments/test_attachments.py`, `test_restricted_attachments.py` | Entidades suportadas: `TICKET`, `ASSET` (`AttachmentEntityType`) |
| CAP-011 | Auditoria imutável com cadeia de hash | EXISTE | `audit/` (`repository.py::AuditRepository.create`, `chain_ddl.py`, `retention.py`, `listener.py`) ; ADR-023 | `audit_logs`, `audit_chain_state` | Banco (`audit_logs`, cadeia de hash) | 8 módulos (`AuditRepository`) | `AuditRepository.create(event_type, entity_type, entity_id, data, user_id)` | `tests/audit/*` (22) | Há **dois** caminhos de gravação: `AuditRepository` direto e `event_bus` → `audit/listener.py` (só `organization` emite nele). Ver D-04 |
| CAP-012 | Notificações, mensagens, canais, agenda | EXISTE | `notifications/` (8,4k linhas; 72 rotas) + `whatsapp/`; ADR-013/019/024/025 | 19 tabelas (`domain_events`, `deliveries`, `notification_rules`, `outbound_messages`, `message_schedules`, `scheduled_jobs`, `job_runs`…) | Banco (`domain_events`, `deliveries`, regras e mensagens) | `service_desk`, `sla`, `identity` (reset de senha), `stock` | **Emitir:** `notifications.outbox.emit_event(session, event_type, entity_type, entity_id, payload, actor_user_id, priority)`; **mensagem direta:** `notifications.direct.enqueue_direct_message`; **manual/agendada:** `notifications.messages.enqueue` | `tests/notifications/*` (298) | Quem emite não conhece canais/destinatários. Não enviar e-mail/WhatsApp direto |
| CAP-013 | Importar/exportar dados | PARCIAL | `data_transfer/` (`export_service.py`, `import_service.py`, 3 rotas, permissão `system.data.export`/`import`) | — | Nenhuma (derivada das tabelas exportadas) | frontend | `ExportService`/`ImportService` por `entity` | `tests/test_data_transfer.py` (4) | **Export de chamados sem escopo e com descrição** (`export_service.py:71-110`). Importador GLPI separado em `assets/glpi_import_*` (CAP-006) |
| CAP-014 | Backup e restauração | EXISTE | `backup/` (`services.py`, 6 rotas); ADR-003 | `db_backups` | Banco (`db_backups`) + arquivos de backup | agenda `backup.daily` | `BackupService` | `tests/test_backup.py` (3), `test_backup_files.py` (4) | Restauração em ambiente limpo: NV |
| CAP-015 | Dashboard atual | PARCIAL | **Só frontend** `frontend/src/app/features/dashboard/dashboard.component.ts` | — | Nenhuma (projeção no navegador) | usuários | Compõe no navegador `TicketService`, `AssetService`, `StockService`, `InventoryService` | `dashboard.component.spec.ts` | **Não há backend de dashboards**; agregados vêm das listas já escopadas |
| CAP-016 | Papéis de banco (owner/app/evolution) | EXISTE | `db_roles.py`; ADR-022 | — | Configuração do cluster e papéis do banco | startup/migrations | `db_roles` | `tests/core/test_database_roles.py` | Infra, citado para evitar reimplementação |
| CAP-017 | Worker, agenda e jobs | EXISTE | `worker.py`, `notifications/job_runner.py`, `jobs.py`; ADR-024 | `scheduled_jobs`, `job_runs`, `worker_heartbeat` | Banco (`scheduled_jobs`, `job_runs`) | todos os jobs (`sla.check`, `stock.low_check`, backup) | `job_runner` + registro em `jobs.py` | `tests/notifications/test_job_runner_pg.py`, `test_schedules*.py` | Novo job entra aqui; não criar scheduler próprio |
| CAP-018 | Provisionamento demo/seed | EXISTE | `core/demo_service.py`, `core/starter_catalog.py`, `seed*.py` | `system_settings` | Nenhuma (provisionamento) | `identity`, `core/demo_router.py` | — | `tests/test_seed_demo.py`, `tests/core/test_reset_all_data.py` | Importa 10 módulos; módulo novo com tabelas precisa entrar no reset |
| CAP-019 | Pasta `access_control/` | **MORTO** | Só `__init__.py`; router comentado em `main.py:183-184` | — | — | — | — | `tests/access_control/` testa `core/access.py`, não esta pasta | Nome enganoso; remover quando houver PR que toque |

Planejado, sem código (não tratar como existente): **localização/situação/disponibilidade de guindastes, restrição operacional, projeção comercial, qualificações/vencimentos de pessoas, integrações externas (Engeman/TOTVS/RH)**. Itens CAP-016 a CAP-019 do v0.1 foram renumerados; o v0.1 listava CAP-016–019 como planejados e agora ficam em §6.

---

## 3. Regras importantes e dono canônico

| Regra | Dono (onde) | Regra reutilizável | Proibição prática |
|---|---|---|---|
| Quem pode ver um chamado | `service_desk/access.py::evaluate_ticket_access` | Receber o escopo de `AccessContext.ticket_scope()` | Reescrever condição de visibilidade em outro módulo |
| Quem vê nota interna / anexo restrito | `ServiceDeskService.can_see_internal`, `attachments/access.py` | Chamar as duas funções | Filtrar `is_internal` à mão |
| Permissão crítica nunca vem do perfil ou de `is_admin` | `core/access.py::has_permission`, `identity/critical.py` | Declarar no catálogo `identity/permission_catalog.py` | Conceder por seed ou migration |
| Visibilidade de ativo | `AccessContext.can_read_asset` | idem | Checar `employee_id` manualmente |
| Mudança de status/alocação de ativo | `AssetService.update_asset` e `MovementService.*` | Passar por um deles | Atualizar `assets.status` direto |
| Baixa/entrada de estoque | `StockService.add_movement` (lock `FOR UPDATE`) | idem | Alterar `stk_items.quantity` direto |
| Prazo, pausa, violação de SLA | `SlaService` | Hooks existentes | Calcular prazo no módulo novo |
| Um evento de negócio vira aviso | `notifications.outbox.emit_event` (mesma transação do negócio) | Registrar `event_type` e regra | Chamar SMTP/WhatsApp direto |
| Trilha de alteração | `AuditRepository.create` na mesma transação | idem | Criar tabela de log própria |
| Criação idempotente | `service_desk/idempotency.py` (`INSERT … ON CONFLICT`) | Copiar o padrão para novas criações em lote | Dedupe em memória |
| Concorrência em contadores/sequência | `with_for_update` (`stock/repository.py:80`, `sla/service.py::_cycles(lock=True)`, ticket principal) | idem | Check-then-act sem lock |
| Job periódico | `notifications/job_runner.py` + `jobs.py` | idem | `asyncio` solto |
| Escopo de dado em export | **LACUNA** (CAP-013) | — | Reaproveitar `ExportService` para dado sensível sem escopo |

---

## 4. Fluxos validados

### FL-01 — Chamado vinculado (EXISTE; ponta a ponta confirmada por código e testes existentes)

`POST /tickets` (`service_desk/router.py`, `require_permission` + `get_access_context`) → `ServiceDeskService.create_ticket` (valida colaborador ativo, roteia por categoria, `route_any_sector`, formulário, `Idempotency-Key`) → grava `sd_ticket` (+ filhos na **mesma transação**, `FOR UPDATE` no principal para `add_children`/encerramento) → `SlaService.start` → `AuditRepository`/auditoria única (`test_audit_single_write.py`) → `emit_event("ticket.created"…, "ticket.children_created")` → worker: `fanout.plan_event` → `resolve_audience` → `deliveries` → `dispatcher` (canais).
**Controles:** permissão no router; visibilidade por `evaluate_ticket_access`; nota/anexo interno por `can_see_internal`; cancelar/dispensar/substituir só pelos setores definidos no ADR-026; 409 em incluir após encerramento.
**Fim:** `RESOLVED/CLOSED` exige zero etapa obrigatória pendente; **nenhum efeito automático em outro domínio**.
**Pontos de entrada alternativos para o mesmo dado:** `whatsapp/router.py:180` (`/tickets/{id}/send`) reutiliza `get_ticket_for_user`; `notifications/conversation/engine.py` (bot) usa `can_read_all`/`ticket_scope`. Ambos respeitam a regra canônica.
**Lacunas:** sem tabela central de transições de status; sem marca de sensibilidade (§5).

### FL-02 — Ativo e movimentação (EXISTE; achado de duplicação de regra)

Caminhos que mudam estado do ativo: (a) `PUT /assets/{id}` → `AssetService.update_asset` (status/unidade/colaborador direto, grava `AssetMovement` se algo mudou, `services.py:95-160`); (b) `POST /movements` e fluxos de chamado → `MovementService.create_movement/reserve/deliver/return/inspect` (valida estados; `movements/services.py:24-216`).
**Achado:** os dois caminhos decidem sobre o mesmo estado. `create_movement` usa `get_asset_for_update` (lock `FOR UPDATE`, `assets/repository.py:45`); `update_asset` usa `get_asset` **sem lock** (`assets/services.py:95`, `repository.py:32`). A regra "estoque/inspeção/baixa não pode ter colaborador" está explícita em `update_asset`; em `create_movement` ela é obtida pelo tipo de movimento (`to_employee_id = None`). Resultado: invariantes parecidas escritas duas vezes e só um caminho protegido contra concorrência.
**Controles:** `assets.read/write/read_own` via `AccessContext.can_read_asset`; baixa (`DECOMMISSIONED`) imutável nos dois caminhos.
**Testes:** `test_assets_lifecycle.py`, `test_assets.py`, `tests/service_desk/test_ticket_asset_scope.py`. Cobertura de **divergência entre os dois caminhos**: NV.

### FL-03 — Notificação (EXISTE; pipeline confirmado)

`emit_event` insere em `domain_events` na transação do negócio e dispara `pg_notify('outbox')` (`notifications/outbox.py`) → worker `fanout.fan_out_batch` (`rule_matches_event` com regras de `notification_rules`, `make_idempotency_key`) → `audience.resolve_audience` (`requester`, `sector_attendants`, `role`, `admins`, `counterpart`, `creator`) → `prefs.allows` (preferências/silêncio) → `deliveries` → `dispatcher` (backoff, ritmo, tentativas, canal alternativo) → status/recibos (`receipts.py`).
**Entradas públicas:** `emit_event` (eventos de domínio), `enqueue_direct_message` (resposta a uma pessoa), `messages.enqueue` (Central de Mensagens manual/agendada).
**Dado sensível:** texto vem de `templates.render` com o payload do evento; se título/descrição entram no payload, vão ao canal. Verificação do conteúdo dos payloads: **NV** (sem decisão sobre confidencialidade).

### FL-04/05 — Guindaste e pendências de colaborador: PLANEJADO (sem código; ver ADR-027 v2)

---

## 5. Divergências, duplicações e documentação defasada

| ID | Achado | Evidência | Gravidade |
|---|---|---|---|
| D-01 | `docs/modules/service-desk.md` marca vínculo com ativo e anexos como *(Futuro)*; ambos existem (`sd_ticket_assets`, `attachments/`, DEC-006) | `docs/modules/service-desk.md:36-37` | Doc defasada |
| D-02 | ADR-026 (nível `internal`) lista `read_all` sem a condição `tickets.manage`/`interactions.internal` | `core/access.py:62-63`, `service_desk/access.py:61` | Doc imprecisa e risco de confidencialidade |
| D-03 | Mudança de status/alocação de ativo por dois caminhos: `update_asset` (sem lock) e `MovementService` (com `FOR UPDATE`) | FL-02 | Duplicação de regra e risco de concorrência (média). **Decisão §7 item 1** |
| D-04 | **Decisão §7 item 2.** Dois barramentos: `core/events.py::event_bus` (in-process, ADR-004 o prevê) usado só por `organization` e pelo `audit/listener.py`; todo o resto usa o outbox (`emit_event`). O comentário em `service_desk/services.py:1549` diz "não emitir também no event_bus" | grep `event_bus` | Convenção divergente do ADR-004 (média) |
| D-05 | ADR-004 diz "12 módulos"; há 16 pastas, 1 morta (`access_control`) | `app/` | Doc defasada |
| D-06 | Export de chamados sem escopo e com descrição | `data_transfer/export_service.py:71-110` | Segurança (alta). **Prioridade registrada §7 item 3** |
| D-07 | `docs/PROJECT_MAP.md` é instantâneo histórico (2026-10) e cita "mortos" que hoje existem | cabeçalho do arquivo | Doc defasada |
| D-08 | Dashboard calcula no navegador a partir de 4 serviços; não há backend | `dashboard.component.ts` | Ponto de atenção para `dashboards` futuro |
| D-09 | Pasta `tests/access_control/` testa `core/access.py` e catálogo; o nome sugere módulo que não existe | `tests/access_control/*` | Baixa |

### Dependências entre domínios (A responsabilidade indevida / B justificada / C dívida gradual)
Resumo (detalhe no plano técnico §3): 120 imports de `models`/`repository` cruzados, 102 fora de `core/seed/cli`. **B:** `organization/identity` como núcleo de pessoas; `audit.repository` transversal; provisionamento. **C:** `service_desk→assets/movements.repository` (8, tardios); ciclos `assets↔movements`, `sla↔service_desk`, `notifications↔service_desk`. **A:** `core→10 módulos` (`demo_service`, `starter_catalog`) para módulos novos; export sem escopo (D-06).

---

## 6. Dez pontos com maior risco de duplicação ao iniciar Operacional (por impacto)

1. **Permissões novas** fora do catálogo (`identity/permission_catalog.py`) → perdem risco/crítica e o teste de snapshot. Reutilizar CAP-001.
2. **Quem vê o quê**: reescrever visibilidade em vez de `AccessContext`. Reutilizar CAP-004 e CAP-001.
3. **Aviso/mensagem** enviados direto em vez de `emit_event`. Reutilizar CAP-012.
4. **Trilha de alteração** própria em vez de `AuditRepository`. Reutilizar CAP-011.
5. **Equipamento duplicando `Asset`** (tag, categoria, unidade, responsável). Reutilizar CAP-006 por FK opcional; não copiar campos patrimoniais.
6. **Status do equipamento** misturando situação operacional, restrição e disponibilidade; `AssetStatus.MAINTENANCE` já existe com outra semântica (TI). Ver D-03.
7. **Segundo motor de processos** (tarefas/etapas) em vez de chamados vinculados. Reutilizar CAP-003.
8. **Prazo/vencimento** calculado em módulo próprio. Reutilizar `business_time`/`SlaService` para dias úteis; para vencimento de requisitos não há dono hoje: LACUNA.
9. **Importação de planilha** própria; hoje existem `data_transfer` e o importador GLPI. Estender `ImportService` com nova `entity`, sem terceiro importador.
10. **Job periódico** (ex.: previsão vencida) fora do `job_runner`. Reutilizar CAP-017.

---

## 7. Decisões de governança (revisão GPT, 2026-11-08)

1. **Estado de ativos.** Transições de status, localização e responsável serão centralizadas **futuramente** num serviço canônico, tendo `MovementService` como base; `AssetService` fica com dados cadastrais. Antes de qualquer alteração: levantar todas as transições, concorrência, efeitos colaterais e testes. **Não refatorar agora.** Até lá, código novo não altera `assets.status`, `unit_id` nem `employee_id` fora dos dois caminhos existentes.
2. **Eventos.** Para novos eventos de domínio que exigem persistência e entrega assíncrona, o padrão é o outbox (`emit_event`). O barramento em memória (`core/events.py`) não é eliminado sem análise de consumidores (hoje: `organization`, `audit/listener.py`). Contratos síncronos continuam permitidos quando apropriados.
3. **Exportação.** Correção de escopo e confidencialidade (D-06) é **prioridade de segurança, anterior ao uso corporativo de dados sensíveis**. Enquanto aberta, não usar `data_transfer` para dados de RH/saúde ou chamados confidenciais.
4. **Vencimentos.** O domínio dono da exigência define situação e validade. Exigências de colaboradores: Pessoas e Qualificações (a criar, mínimo). Exigências técnicas de equipamento: domínio do equipamento. Notificações apenas comunicam. Fecha a lacuna do item 8 da §6.
5. **Este mapa** é documento único em `docs/architecture/mapa-logico-gero.md`. Toda capacidade traz: estado, dono/responsável, regras, contratos, consumidores, testes e fonte de verdade.
6. **Governança leve.** Checklist de prevenção de duplicação na proposta de PR. **Sem novas ferramentas nem bloqueios de CI** nesta primeira incorporação.
7. **Uso.** Referência obrigatória no planejamento de funcionalidades novas; atualizado no mesmo PR que alterar capacidade ou contrato. Vale após a aprovação do PR de incorporação e a atualização do `AGENTS.md`.

---

## 8. Não verificado nesta rodada
- Execução de qualquer teste, build ou migration.
- Conteúdo dos payloads dos eventos (confidencialidade em FL-03).
- Frontend além do dashboard (telas por capacidade).
- Restauração de backup em ambiente limpo.
- Se as 72 rotas de `notifications` estão todas protegidas como o snapshot de rotas indica (arquivo `tests/access_control/route_access_snapshot.json` existe; não o auditei linha a linha).
- Capacidades internas de `notifications` (templates, push, telegram, slack, conversação): listadas como um bloco (CAP-012), sem sub-catálogo.
