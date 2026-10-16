# PROJECT_MAP — Plataforma de Gestão de TI

> Mapa operacional do repositório. Base: commit `a544af7` (branch `main`, 2026-10-14).
> **Fonte de verdade = código.** Cada afirmação foi conferida lendo o arquivo citado (`caminho:linha`).
> Marcadores: **(exec)** = confirmado executando; **(inf)** = inferido, não confirmado.
> Quando o código diverge de README/ROADMAP/docs, vale o código — ver seção 10.
> Falhas e riscos detalhados ficam em `docs/AUDIT.md` (Fase 2); aqui só o que muda como se navega ou edita o sistema.

---

## 1. Visão geral

Service desk + patrimônio (ativos) + estoque de insumos + inventário periódico, **single tenant** (uma `Company`), com bot de WhatsApp. Backend FastAPI (Python 3.12) com SQLAlchemy 2.0 async; frontend Angular SPA; PostgreSQL 16; Nginx; Docker Compose.

### Perfis (roles semeadas em `backend/app/seed.py:163-225`)

| Role | Pode (resumo) |
|---|---|
| `Solicitante` | abrir/acompanhar os próprios chamados; ver os próprios ativos (`assets.read_own`) |
| `Atendente` | Solicitante + atender chamados do setor (`service_desk.tickets.manage`), notas internas, ler ativos/estoque |
| `Gestão` | Atendente + ver todos os chamados, relatórios, inventário, leitura de organização, exportar CSV |
| `Admin` | Gestão + escrever ativos/estoque/organização/usuários/perfis |
| `Administrador` | todas as permissões; o 1º usuário (setup) também recebe a flag `is_admin=True`, que ignora qualquer checagem de permissão (`core/dependencies.py:75-88`) |

Usuário sem `Employee` vinculado não abre chamado (`service_desk/router.py:206`).

### Módulos

| Estado | Módulo | Observação |
|---|---|---|
| **Ativo** | `core` (config, events, exceptions, security, demo), `organization`, `identity`, `service_desk`, `assets`, `movements`, `stock`, `inventory_audit`, `attachments`, `notifications` (REST + WS + e-mail), `audit`, `data_transfer`, `backup`, `whatsapp` | montados em `app/main.py:122-168` |
| **Morto** | `access_control` | só `__init__.py`; router comentado em `main.py:143-144`, models comentados em `alembic/env.py:27`. ROADMAP o marca ✅ |
| **Morto (parcial)** | `NotificationService.create_notification` (`notifications/services.py:52`) | **nenhum chamador** em `app/`; o sino do header nunca recebe notificação gerada pelo sistema |
| **Morto** | `WhatsAppNotificationDispatcher` (`whatsapp/notification_dispatcher.py`) | zero referências em `app/` e `tests/` |
| **Morto** | `core/pagination.py` (`PaginatedResponse`, `get_pagination_params`) | zero usos; todas as listagens retornam array sem paginação |
| **Morto** | `app/check_registry.py`, `backend/seed_service_desk.py`, `tests/` na raiz (3 scripts contra `http://localhost`) | scripts avulsos; os de raiz não rodam no CI |
| **Morto** | Configs `ATTACHMENT_STORAGE_PATH`, `ATTACHMENT_MAX_SIZE_MB`, `ATTACHMENT_ALLOWED_TYPES`, `TICKET_REOPEN_DAYS`, `BACKUP_RETENTION_DAYS` | definidas em `config.py`, nunca lidas pelo fluxo real (ver seção 8) |
| **Planejado (só doc/UI)** | Contas e acessos (MOD-09), notificações multicanal | ver `docs/AUDIT.md` e ADR da Fase 3 |

Frontend: 129 arquivos em `frontend/src`, rotas lazy em `frontend/src/app/app.routes.ts`. Sem módulo de notificações dedicado além do sino em `core/layout/header`.

---

## 2. Arquitetura

### 2.1 Containers e requisição

```mermaid
flowchart LR
  B[Browser SPA Angular] -->|":80"| N[nginx 1.27]
  N -->|"/ -> arquivos estáticos<br/>bind mount frontend/dist"| FS[(frontend/dist/.../browser)]
  N -->|"/api/ (HTTP + WS)"| A["backend: uvicorn --workers 4<br/>FastAPI app.main:app"]
  A -->|"asyncpg, pool 20+10 por worker"| P[(postgres:16)]
  A -->|"escrita direta"| U["/app/uploads (anexos)<br/>/app/static (logo)"]
  A -->|"/data/backups"| BV[(volume backups_data)]
  A -->|"pg_dump / psql (subprocess)"| P
  A -->|"SMTP 10s timeout"| SMTP[(servidor SMTP externo)]
  A -.->|"HTTP httpx, opcional"| EVO["evolution-api (profile evolution)"]
  EVO -.->|"POST webhook, sem auth"| A
  EVO --- P
  B -. "WebSocket /api/v1/notifications/ws?token=" .-> A
```

Fatos que o diagrama não mostra:

- Nginx só roteia `/api/` (`nginx/nginx.conf:22`), `/ws/` (`:39`, **não usado**: o WS real é `/api/v1/notifications/ws`) e `/` com fallback SPA (`:54-60`). **Não há `/static`**: `/static/logo.*` cai no `index.html`.
- `backend` e `postgres` também publicam portas no host (`docker-compose.yml:29-30` e `:54-55`), contornando o Nginx.
- `./backend:/app` é **bind mount** (`docker-compose.yml:59`): o código que roda é o do host, não o da imagem; `COPY . .` do Dockerfile (`backend/Dockerfile:27`) fica sombreado.
- 4 workers uvicorn (`backend/Dockerfile:38`) × pool 20+10 (`app/database.py:23-25`) = até 120 conexões; o default do Postgres é `max_connections=100` (inf).
- Estado em memória por worker: `NotificationConnectionManager.active_connections` (`notifications/services.py:15-46`), `lru_cache` de settings.

### 2.2 Camadas por módulo

Padrão declarado e seguido pela maioria: `models.py → schemas.py → repository.py → services.py → router.py`.

```
router (FastAPI Depends, permissão) -> service (regra de negócio) -> repository (SQLAlchemy select/flush) -> models
```

Transação: `get_db` (`app/database.py:41-58`) faz `commit` ao fim da request e `rollback` em exceção.

### 2.3 Onde o padrão é violado

| Violação | Evidência |
|---|---|
| Router com regra de negócio e SQL | `service_desk/router.py:32-70` (`get_user_context` faz `select(Employee)`); `whatsapp/router.py` inteiro (CRUD de templates/config/outbox sem service) |
| Router decide autorização por `payload` manual em vez de `require_permission` | `service_desk/router.py:32-70`, `assets/router.py:77-99,121-149`, `attachments/router.py:23-52` |
| Service chama `repo.session` (quebra o encapsulamento) | `assets/services.py:171,177,183` |
| Repository faz `commit` (fronteira de transação no lugar errado) | `notifications/repository.py:17,45,55`; `backup/services.py:81,102`; `whatsapp/queue_service.py:241` |
| Router também faz `commit` (duplica `get_db`) | `service_desk/router.py:100,119,218,243,293,324,357,386,411,441` |
| Acoplamento cruzado de módulos e import dentro de função para fugir de ciclo | 78 imports `from app...` indentados em 14 arquivos (ex.: `service_desk/services.py:195,415,507-510`; `attachments/router.py:34-35`; `main.py:122-168`) |
| Model importa model de outro módulo no topo | `organization/models.py:22` (`StockItem`), `assets/models.py:21` (`Employee, Unit`), `identity/models.py:19` |
| Dois caminhos de auditoria gravando o mesmo evento | `service_desk/services.py:824-851`: grava direto em `AuditRepository` **e** emite no `event_bus`, cujo listener global (`audit/listener.py:11-28`) grava de novo (duplicação provável; confirmar em runtime, a suíte não executa o lifespan) |
| Módulos sem service/repository | `whatsapp` (parte), `backup` (service sem repository), `data_transfer`, `core/demo_*` |

---

## 3. Mapa de módulos

Prefixo global `API_V1_PREFIX=/api/v1` (`config.py:28`). Permissão: `P:x` = `require_permission("x")`; `JWT` = qualquer token válido; `ctx` = regra manual no corpo; `—` = **sem autenticação**.

| Módulo | Responsabilidade | Arquivos principais | Tabelas |
|---|---|---|---|
| `core` | settings, engine, JWT/bcrypt, exceções, event bus, mixins, modo demo | `config.py`, `database.py`, `core/{security,dependencies,events,exceptions,soft_delete,timestamps,settings_model,demo_service,demo_router}.py` | `system_settings` |
| `organization` | empresa, unidades, setores, colaboradores, logo | `organization/{models,router,services,repository}.py` | `companies`, `units`, `sectors`, `employees` |
| `identity` | setup inicial, login, usuários, perfis, permissões | `identity/{models,router,services,repository}.py` | `user_accounts`, `roles`, `permissions`, `user_roles`, `role_permissions` |
| `service_desk` | chamados, categorias com form dinâmico, interações, materiais, ciclo de ativos por chamado, histórico, relatório | `service_desk/{models,router,services,repository}.py` | `sd_ticket`, `sd_ticket_category`, `sd_ticket_interaction`, `sd_ticket_materials`, `sd_ticket_assets` |
| `assets` | categorias e ativos (JSONB `technical_specs`), termo de responsabilidade | `assets/{models,router,services,repository}.py` | `asset_categories`, `assets` |
| `movements` | máquina de estados do ativo + histórico | `movements/services.py:24-152` | `asset_movements` |
| `stock` | insumos por unidade, categorias, movimentos | `stock/{models,router,services,repository}.py` | `stk_categories`, `stk_items`, `stk_movements` |
| `inventory_audit` | inventário periódico (cabeçalho + itens conferidos) | `inventory_audit/{models,router,service,repository}.py` | `inventory_audits`, `inventory_audit_items` |
| `attachments` | upload/download/exclusão em disco, polimórfico | `attachments/{models,router,service,repository}.py` | `attachments` |
| `notifications` | in-app (REST+WS), e-mail SMTP | `notifications/{models,services,router,repository,email_service,email_router}.py` | `notifications`; config SMTP em `system_settings` |
| `audit` | trilha de eventos (listener do event bus) | `audit/{models,listener,repository,services,router}.py` | `audit_logs` |
| `data_transfer` | export/import CSV | `data_transfer/{router,export_service,import_service}.py` | — |
| `backup` | `pg_dump`/restore, retenção, SHA-256 | `backup/{models,router,services}.py` | `db_backups` |
| `whatsapp` | adapters (Mock/Evolution/Meta), máquina de estados, outbox anti-ban, templates | `whatsapp/{adapter,conversation_service,queue_service,router,models,template_service}.py` | `wa_configs`, `wa_sessions`, `wa_templates`, `wa_outbox` |

### 3.1 Endpoints

**organization** (`/organization`)

| Método | Rota | Permissão |
|---|---|---|
| GET/POST/PATCH | `/company` | `P:organization.company.read` / `.create` / `.update` |
| POST | `/company/logo` | `P:organization.company.update` (`organization/router.py:55`) |
| GET | `/company/public` | **—** (intencional: login/sidebar) |
| GET/POST, GET/PATCH/DELETE `{id}` | `/units` | `P:organization.units.read|create|update` (DELETE usa `update`) |
| idem | `/sectors` | `P:organization.sectors.*` |
| GET | `/employees/me/details` | `JWT` |
| GET/POST, GET/PATCH/DELETE `{id}` | `/employees` | `P:organization.employees.*` |

**identity** (`/identity`) — `identity/router.py`

| Método | Rota | Permissão |
|---|---|---|
| GET | `/setup/status` | **—** |
| POST | `/setup` | **—** (só funciona com 0 usuários) |
| POST | `/login` | **—** (form OAuth2) |
| GET | `/me` | `JWT` |
| POST | `/me/password` | `JWT` |
| GET | `/permissions` | `P:identity.roles.read` |
| GET/POST/GET{id}/PATCH/DELETE | `/users` | `P:identity.users.read|create|update` |
| PATCH | `/users/{id}/password` | `P:identity.users.update` |
| GET/POST/GET{id}/PATCH/DELETE | `/roles` | `P:identity.roles.read|create|update` |

**service_desk** (`/tickets`) — `service_desk/router.py`. **Nenhuma rota usa `require_permission`**; a autorização é `ctx` (`get_user_context`, `:32-70`) derivada do JWT:

| Método | Rota | Regra |
|---|---|---|
| GET | `/categories` | **— (sem auth)** `:78` (xfail documentado em `tests/baseline/test_service_desk_baseline.py`) |
| POST/PATCH | `/categories`, `/categories/{id}` | `ctx.is_technician` |
| GET | `` | escopo por `can_read_all` / setor+atribuído+autor / só autor |
| GET | `/reports/summary` | `ctx.can_view_reports` (`is_admin` ou `service_desk.reports.read`) |
| GET | `/{id}` , `/{id}/history` | `get_ticket_for_user` (`services.py:79-119`) |
| POST | `` | exige `employee_id` |
| PATCH | `/{id}` | técnico do setor/atribuído **ou** solicitante (só RESOLVED/CLOSED) |
| POST | `/{id}/interactions` | `get_ticket_for_user`; nota interna exige técnico/`interactions.internal` |
| POST | `/{id}/materials` | `is_technician` (baixa estoque via `StockService`) |
| POST | `/{id}/assets/{asset_id}/reserve|deliver|return|inspect` | `is_technician` **sem** checar escopo do chamado nem `assets.write` (`services.py:498+` usa `repo.get_ticket` direto); body é `dict` cru (`router.py:339,368,397,422`) |

**assets** (`/assets`) — `assets/router.py`

| Método | Rota | Permissão |
|---|---|---|
| GET/POST/PUT/DELETE | `/categories[/{id}]` | `P:assets.read` / `P:assets.write` |
| GET | `` | `P:assets.read` |
| GET | `/me` | `JWT` |
| GET | `/{id}` | `assets.read` **ou** `assets.read_own` + dono (manual, `:77-99`) |
| POST/PUT | `` , `/{id}` | `P:assets.write` |
| GET | `/{id}/responsibility-statement` | idem GET `/{id}` (HTML gerado na hora) |

**movements** (`/movements`) — `P:assets.read` (GET `/asset/{id}`), `P:assets.write` (POST `/`, `/{id}/reserve|cancel-reservation|deliver|return|inspect`). **stock** (`/stock`) — `P:stock.read|write` em categorias, itens e `/movements`. **inventory** (`/inventory`) — `P:inventory.read` (GET) / `P:inventory.write` (POST, PATCH, itens).

**attachments** (`/attachments`) — `attachments/router.py`

| Método | Rota | Autorização |
|---|---|---|
| POST | `` (multipart: `file`, `entity_type`, `entity_id`) | `JWT` + `verify_entity_access` |
| GET | `?entity_type=&entity_id=` | idem |
| GET | `/{id}/download` | idem (usa `entity_type` do registro) |
| DELETE | `/{id}` | idem |

`verify_entity_access` só avalia a regra quando `entity_type == "TICKET"` (`:33`); admin passa direto (`:30`); qualquer outro `entity_type` passa sem checagem.

**notifications** — `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` (`JWT`, escopo do usuário); `WS /notifications/ws?token=` (JWT na query string, `notifications/router.py:57-76`); `GET|PUT /notifications/email/config`, `POST /notifications/email/test` com `P:system.backup.manage` (permissão reaproveitada).

**audit** — `GET /audit`, `GET /audit/{entity_type}/{entity_id}` com `P:admin` (`audit/router.py:26,36`). `"admin"` **não existe** em `seed.py`; só passa via flag `is_admin`. A permissão `audit.read` do seed nunca é exigida.

**system** — `POST /system/export` `P:system.data.export`; `POST /system/import/analyze|execute` `P:system.data.import`; `POST /system/backups/generate`, `GET /system/backups`, `GET .../{id}/verify`, `POST .../{id}/restore`, `DELETE .../{id}` `P:system.backup.manage`; `GET .../{id}/download` `P:system.backup.download`; `GET /system/demo/status` `P:system.data.export`; `GET /system/demo/preview-clean`, `POST /system/demo/clean`, `POST /system/demo/seed` `P:system.backup.manage`.

**whatsapp** (`/integrations/whatsapp`) — `whatsapp/router.py`

| Método | Rota | Permissão |
|---|---|---|
| POST | `/webhook` | **—** (`webhook_secret` gravado mas nunca verificado; resposta devolve o texto do bot, `:80`) |
| GET/PATCH | `/config`; GET `/status`, `/qrcode`; POST `/emergency-pause`, `/test-send` | `P:integrations.whatsapp.manage` |
| GET | `/templates`; POST `/templates/{id}/preview` | **—** sem permissão (`:258`, `:366`; `get_db` só abre sessão) |
| POST/PUT/DELETE | `/templates[/{id}]` | `P:integrations.whatsapp.manage` |
| GET/POST | `/outbox`, `/outbox/stats`, `/outbox/process`, `/outbox/{id}/cancel|retry` | `P:integrations.whatsapp.manage` |
| POST | `/tickets/{id}/send` | só `JWT` (`:511-515`): qualquer usuário autenticado, qualquer chamado |

### 3.2 Dependências entre módulos (quem importa quem)

```
service_desk -> organization, identity(repo), stock(service), assets/movements(repo+service), audit(repo), notifications(email)
whatsapp     -> service_desk(service), organization, identity(models), core
attachments  -> service_desk(service) (só para TICKET), identity(repo)
assets       -> movements(models/repo), organization(models)
movements    -> assets(models/repo)          # ciclo assets<->movements resolvido com imports tardios
organization -> stock(models)                # Unit.stock_items
core/demo    -> quase todos (limpeza em cascata manual)
```

### 3.3 Eventos

`core/events.py`: `EventBus` in-process, síncrono, handlers em sequência; falha de handler é logada e engolida (`:115-122`).

| Emissor | Eventos | Consumidor |
|---|---|---|
| `service_desk/services.py:824` | `ticket.created`, `ticket.status_changed`, `ticket.closed`, `ticket.priority_changed`, `ticket.assigned`, `ticket.interaction_added`, `ticket.material_added`, `ticket.asset_reserved|delivered|returned|inspected` | só `audit.listener` (`subscribe_all`, registrado em `main.py:41`) |
| `organization/services.py:227` | 1 evento | idem |
| `identity/services.py` | importa o bus, sem emissão relevante | — |

Nenhum evento de ativos, movimentos, estoque, backup, WhatsApp ou inventário.

---

## 4. Modelo de dados

```mermaid
erDiagram
  companies ||--o{ units : company_id
  units ||--o{ sectors : unit_id
  units ||--o{ employees : unit_id
  sectors ||--o{ employees : sector_id
  employees ||--o| employees : manager_id
  employees ||--o| user_accounts : "employee_id UNIQUE"
  user_accounts }o--o{ roles : user_roles
  roles }o--o{ permissions : role_permissions

  sd_ticket_category ||--o{ sd_ticket : category_id
  sectors ||--o{ sd_ticket_category : default_sector_id
  employees ||--o{ sd_ticket : requester_id
  user_accounts ||--o{ sd_ticket : assignee_id
  sectors ||--o{ sd_ticket : "origin_sector_id, responsible_sector_id"
  units ||--o{ sd_ticket : origin_unit_id
  sd_ticket ||--o{ sd_ticket_interaction : ticket_id
  user_accounts ||--o{ sd_ticket_interaction : author_id
  sd_ticket ||--o{ sd_ticket_materials : "ticket_id CASCADE"
  stk_items ||--o{ sd_ticket_materials : "stock_item_id CASCADE"
  sd_ticket }o--o{ assets : "sd_ticket_assets CASCADE"

  asset_categories ||--o{ assets : category_id
  units ||--o{ assets : unit_id
  employees ||--o{ assets : employee_id
  assets ||--o{ asset_movements : asset_id
  sd_ticket |o--o{ asset_movements : "ticket_id SET NULL"
  user_accounts ||--o{ asset_movements : author_id

  stk_categories ||--o{ stk_items : category_id
  units ||--o{ stk_items : unit_id
  stk_items ||--o{ stk_movements : item_id
  user_accounts ||--o{ stk_movements : author_id

  units ||--o{ inventory_audits : unit_id
  user_accounts ||--o{ inventory_audits : auditor_id
  inventory_audits ||--o{ inventory_audit_items : audit_id
  assets |o--o{ inventory_audit_items : asset_id
  stk_items |o--o{ inventory_audit_items : stock_item_id

  user_accounts ||--o{ notifications : user_id
  user_accounts |o--o{ audit_logs : user_id
  user_accounts |o--o{ attachments : "uploaded_by_id SET NULL"
  user_accounts |o--o{ db_backups : created_by_id

  employees |o--o{ wa_sessions : "employee_id SET NULL"
  sd_ticket |o--o{ wa_sessions : "current_ticket_id SET NULL"
  sd_ticket |o--o{ wa_outbox : "ticket_id SET NULL"
  wa_templates |o--o{ wa_outbox : "template_id SET NULL"
```

### 4.1 Vínculos polimórficos (sem FK)

| Tabela | Colunas | Valores | Consequência |
|---|---|---|---|
| `attachments` | `entity_type` (string livre) + `entity_id` (UUID) | front usa `TICKET`, `ASSET`; comentário cita `TICKET_INTERACTION` (`attachments/models.py:24`) | sem integridade; `entity_type` vira nome de pasta (`attachments/service.py:28`) |
| `audit_logs` | `entity_type` + `entity_id` | `"ticket"` (minúsculo) e outros | histórico de chamado lê `entity_type == "ticket"` (`service_desk/services.py:710`) |
| `notifications` | `entity_type`, `entity_id` opcionais | — | — |
| `inventory_audit_items` | `item_type` (`ASSET`/`STOCK`) + duas FKs nulas | — | nada impede ambas nulas ou ambas preenchidas |

### 4.2 Exclusão

| Estratégia | Onde |
|---|---|
| `SoftDeleteMixin` (`is_active` + `deleted_at`, `core/soft_delete.py`) | `UserAccount`, `Company`, `Unit`, `Sector`, `Employee`, `Asset`, `AssetCategory`, `Attachment`, `StockCategory`, `InventoryAudit` |
| `is_active` próprio, sem `deleted_at` | `TicketCategory` (`service_desk/models.py:32`) |
| Sem exclusão lógica | `Ticket`, `StockItem` (existe `DELETE` em `stock/router.py:88`), `Notification`, `WhatsAppTemplate` (`session.delete`, `whatsapp/router.py:361`), `DatabaseBackup` |
| Hard delete em massa | `core/demo_service.py:190-228` (tudo com `is_demo=True`), retenção de backups (`backup/services.py:318`) |

`Attachment.soft_delete` só preenche `deleted_at` (`attachments/repository.py:36-39`) e a consulta filtra por `deleted_at`; o mixin também define `is_active`, que fica `True`.

Cascatas **no banco** (FK `ondelete`): `sd_ticket_assets`, `sd_ticket_materials` (`stock_item_id` CASCADE: apagar item de estoque apaga o consumo registrado), `user_roles`, `role_permissions`; `SET NULL`: `asset_movements.ticket_id`, `attachments.uploaded_by_id`, tabelas `wa_*`. Cascatas **só no ORM**: `Ticket.interactions/materials`, `Unit.sectors/stock_items`, `Company.units`, `InventoryAudit.items`, `StockItem.movements`.

Convenção de dados: PK `UUID` (`uuid.uuid4`), timestamps UTC `TimestampMixin` (`core/timestamps.py`), status e tipos como `String` (não Enum de banco) com valores em `StrEnum` quando existe (`AssetStatus`, `MovementType`), JSONB para specs/form/contexto, flag `is_demo` em quase toda entidade de negócio.

---

## 5. Onde ficam as coisas importantes

"Sobrevive a `up --build`" assume o `docker-compose.yml` atual (bind mount `./backend:/app`).

| Item | Caminho no container | Volume / mount | Sobrevive a `up --build` | Entra no backup |
|---|---|---|---|---|
| Banco | `/var/lib/postgresql/data` | volume `postgres_data` | sim | é o objeto do backup |
| **Anexos (real)** | `/app/uploads/<tipo>/<id>/<uuid>.<ext>` (`attachments/service.py:11`) | **cai no bind mount `./backend/uploads` do host** | sim (host); some se o diretório do repo for apagado/clonado de novo | **não** |
| Anexos (esperado por config/compose/docs) | `/data/attachments` (`ATTACHMENT_STORAGE_PATH`) | volume `attachments_data` | volume existe mas **fica vazio** | não |
| Termos de responsabilidade | **não são armazenados**: HTML gerado na hora (`assets/services.py:160`); o "termo assinado" é um anexo `ASSET` qualquer | — | — | — |
| Logo | `/app/static/logo.<ext>` (`organization/router.py:56-72`), URL `/static/...` no banco | bind mount `./backend/static` | sim (host) | **não** (só o `logo_url` no banco) |
| Backups | `/data/backups/backup_gestao_ti_<ts>.sql.gz` (`BACKUP_STORAGE_PATH`) | volume `backups_data` | sim | n/a; mesmo host/volume do banco |
| Configuração (env) | `Settings` em `config.py`, `.env` na raiz (não versionado) | — | `.env` fica no host | não |
| Configuração (banco) | `system_settings` (chaves `system_mode`, `smtp_config`), `wa_configs` | `postgres_data` | sim | sim (dentro do dump) |
| Segredos de integração | senha SMTP em texto puro no JSONB de `system_settings` (`notifications/email_service.py:83`); `wa_configs.api_key` e `webhook_secret` em texto puro (`whatsapp/models.py:27-29`); `WhatsAppConfigResponse` (`whatsapp/schemas.py:18`) não devolve esses dois campos | `postgres_data` | sim | sim, em claro, dentro do `.sql.gz` |
| Segredo JWT | `SECRET_KEY` (env) | — | `.env` | não |
| Logs | stdout/stderr do container (`logging` sem configuração central); sem arquivo | `docker logs` | perdidos ao recriar o container | não |
| Migrations | `backend/alembic/versions/` (12 revisões, cabeça `g7b8c9d0e1f2`) | no repo | sim | n/a |
| Seed | `backend/app/seed.py` (permissões, roles, categorias de estoque, templates WA, empresa "Empresa Padrão"); `seed_demo.py` (1420 linhas) e `core/demo_service.py` (demo) | no repo | sim | n/a |
| Sessões WhatsApp (Evolution) | `/evolution/instances` + schema `evolution` no mesmo Postgres | volume `evolution_instances` | sim | o schema `evolution` entra no `pg_dump` do banco inteiro |

---

## 6. Fluxos críticos

### 6.1 Login e JWT
1. SPA: `features/auth/login` → `core/auth/auth.service.ts:68` `POST /identity/login` (form-urlencoded).
2. `identity/router.py` `login` → `IdentityService.authenticate` (`identity/services.py:44`) → `IdentityRepository.get_user_by_email` filtra `is_active` (`identity/repository.py:35-41`) → `verify_password` (bcrypt, trunca em 72 bytes, `core/security.py:24-56`).
3. `_issue_token` (`services.py:61`) assina HS256 com `sub`, `roles`, `permissions[]`, `is_admin`, `must_change_password`; expiração `JWT_EXPIRATION_HOURS=8`.
4. SPA guarda o token em `localStorage` (`auth.service.ts:56,72`) e `jwt.interceptor.ts` injeta `Authorization: Bearer`; 401 → `logout()`.
5. Backend valida só assinatura/expiração (`core/dependencies.py:20-32`): **não consulta o banco**. Desativar usuário, mudar role ou `is_admin` só vale no próximo login (até 8 h). `must_change_password` é imposto apenas pelo guard do frontend.
6. IP do login vem de `X-Forwarded-For` sem validação de proxy confiável (`dependencies.py:59-72`). Não há rate limit nem bloqueio.

### 6.2 Setup inicial
`GET /identity/setup/status` → `POST /identity/setup` (`identity/services.py:84`). Só cria se `count_users()==0`. Modo `DEMO` chama `DemoManagementService.seed_demo_data`; modo limpo tenta criar `Company(corporate_name=…)`, mas o model só tem `name` (`organization/models.py:31`). Com `seed.py` já rodado, a empresa existe e o ramo `elif` apenas seta atributos inexistentes (`identity/services.py:136`, no-op). **(exec)** `test_setup_creates_first_admin_and_logs_in` e `test_setup_creates_admin_role_when_seed_missing` falham com `TypeError`.

### 6.3 Chamado: abertura e ciclo de vida
Abrir: `POST /tickets` → `ServiceDeskService.create_ticket` (`service_desk/services.py:147`): valida categoria ativa e `form_schema` (obrigatórios/opções), resolve `responsible_sector_id` (categoria → setor padrão), marca `is_demo` se `system_mode=DEMO`, associa `asset_ids`, grava, registra `ticket.created`.
Estados: `OPENED → IN_PROGRESS ⇄ PENDING → RESOLVED → CLOSED`. A única trava é "CLOSED não volta" (`services.py:299-300`); `TICKET_REOPEN_DAYS` não é usado. Solicitante só pode PATCH para RESOLVED/CLOSED (`:271-279`).
Interação: `add_interaction` (`:367`) respeita `is_internal`; depois dispara e-mail dentro de `try/except` que engole falha (`:412-428`).
Histórico: `get_ticket_history` (`:686`) monta a linha do tempo de `audit_logs` (`entity_type="ticket"`); notas internas filtradas por permissão.

### 6.4 Atribuição de ativo + termo de responsabilidade
1. Direto: `POST /movements/{asset_id}/deliver` ou `POST /movements/` (`ASSIGNMENT`) → `AssetMovementService.create_movement` (`movements/services.py:24`), que usa `get_asset_for_update` (`SELECT … FOR UPDATE`, `assets/repository.py:45-48`), valida a máquina de estados e grava `AssetMovement` + atualiza o ativo na mesma transação. Via chamado: `POST /tickets/{id}/assets/{aid}/deliver` → mesmo serviço com `ticket_id`.
2. Alternativa que ignora a máquina de estados: `PUT /assets/{id}` com `status`/`employee_id` (`assets/services.py:91-158`) cria movimento por inferência.
3. Termo: `GET /assets/{id}/responsibility-statement` devolve HTML (`assets/services.py:160-389`); nome do colaborador, specs e nome do ativo são interpolados **sem escape** (`:188-190, 323-349`). Nada é persistido; não há registro "termo emitido" nem "termo assinado".
4. "Assinado" = anexo `ASSET` cujo nome contenha `termo/cautela/assinado/responsabilidade` ou termine em `.pdf` — lógica **no frontend** (`asset-detail.component.ts:148-163`). O backend não sabe.

### 6.5 Upload e download de anexo
`attachments.service.ts` → `POST /attachments` (multipart) → `verify_entity_access` → `AttachmentService.upload_file` (`attachments/service.py:19-60`): cria `uploads/<entity_type.lower()>/<entity_id>/`, nome `uuid4 + extensão do filename do cliente`, grava em chunks de 1 MB, **sem limite de tamanho nem validação de tipo/extensão**, persiste `content_type` do cliente. Download: `FileResponse(filename=…, media_type=<cliente>)` (`attachments/router.py:97-101`). Delete: remove o arquivo (erro engolido, `service.py:83-87`) e soft delete. Limite real = 100 MB do Nginx (`nginx.conf:19`).

### 6.6 Movimentação de estoque
`POST /stock/movements` → `StockService.add_movement` (`stock/services.py:116`): `get_item` **sem lock** (`stock/repository.py:69-77`), confere saldo, altera `quantity`, grava `StockMovement`. Duas saídas concorrentes (4 workers) podem sobrescrever uma à outra (lost update). Consumo via chamado usa o mesmo caminho (`service_desk/services.py:471`). `min_quantity` só alimenta alerta visual do dashboard; nada é emitido.

### 6.7 Inventário
`POST /inventory` cria cabeçalho (`OPENED`); `PATCH` muda status (preenche `start_date`/`end_date`); itens são adicionados e conferidos manualmente (`inventory_audit/service.py`). **Fechar o inventário não gera divergência, ajuste de estoque nem alteração de ativo**; é apenas registro. Itens não são pré-populados a partir de ativos/estoque da unidade.

### 6.8 Backup e restore
Gerar: `POST /system/backups/generate` → `BackupService.create_backup` (`backup/services.py:46`): `pg_dump --clean --if-exists` via subprocess (imagem agora instala `postgresql-client`, `backend/Dockerfile:30`), gzip, SHA-256, grava em `/data/backups`, registra `db_backups`, aplica retenção por **quantidade** (`BACKUP_MAX_KEEP=15`; `BACKUP_RETENTION_DAYS` não é usado). Sem `pg_dump` (nem `docker`) falha com `FAILED` e `BusinessRuleException` (`:105-153`).
Restore: `POST /system/backups/{id}/restore` (`:205`): valida hash, descomprime **tudo em memória**, executa `psql` sem `ON_ERROR_STOP` e com o app conectado; checa só o `returncode`. Sem backup prévio automático, sem restaurar anexos/logo. Backups entram no modo demo: `clean_demo_data` gera/usa um backup recente antes de apagar (`core/demo_service.py:126-147`).
Backup automático/agendado: **não existe** (nenhum scheduler no projeto). **(exec)** `tests/test_backup.py` (2 testes) falha nesta máquina: `DATABASE_URL` de teste aponta para Postgres e `pg_dump` não existe.

### 6.9 WhatsApp — recebida e enviada
Recebida: Evolution → `POST /integrations/whatsapp/webhook` (**sem auth**, `whatsapp/router.py:57`) → extrai telefone/texto (`:64-76`) → `WhatsAppConversationService.process_incoming_message` (`conversation_service.py:42`): sessão por telefone (`wa_sessions`), identifica `Employee.phone`; se não achar, pergunta a **matrícula** e grava o telefone no colaborador (`:110-117`) — sem segundo fator. Estados: `IDLE`, `AWAITING_REGISTRATION_LINK`, `AWAITING_CATEGORY`, `AWAITING_TITLE`, `AWAITING_DESCRIPTION`, `AWAITING_INTERACTION_TICKET`, `AWAITING_INTERACTION_MSG`. Cria chamado / consulta / interage via `ServiceDeskService`. A resposta é enviada pelo adapter **direto** (não passa pela outbox) e também retornada no corpo HTTP (`router.py:80`). Se o colaborador não tem `UserAccount`, a interação usa `employee.id` como `author_id` (`conversation_service.py:296`), que referencia `user_accounts.id` (FK) — **(inf)** viola a FK em Postgres.
Enviada: `POST /integrations/whatsapp/tickets/{id}/send` → `WhatsAppQueueService.enqueue_message` → grava `TicketInteraction` pública → `process_outbox(max_batch=5, skip_sleep=True)` inline (`router.py:575-603`). `process_outbox` (`queue_service.py:111`) aplica limite/min, cooldown, presença "digitando", jitter, retentativas (3, backoff 30 s × tentativa). **Não existe worker**: o que ficar `PENDING` (cooldown, rate limit, falha) só sai se alguém chamar `/outbox/process` ou enviar outra mensagem. Sem `FOR UPDATE SKIP LOCKED`: dois workers podem pegar o mesmo item.
O `Dispatcher` automático (status/atribuição) nunca é chamado (seção 1).

### 6.10 Notificação in-app
Modelo `notifications` + `NotificationService.create_notification` (grava, commita no repositório e empurra pelo WS). Nada o chama. O front (`core/services/notifications.service.ts:48`) abre `ws(s)://host/api/v1/notifications/ws?token=…` e lista via REST. `manager` é um dict em memória do processo; com `--workers 4` um evento só chegaria ao cliente conectado ao mesmo worker (inf, hoje irrelevante porque ninguém emite). E-mail é o único canal realmente disparado (nova interação no chamado, `service_desk/services.py:412-428`).

---

## 7. Autorização

### 7.1 Como a permissão chega ao backend
JWT (`identity/services.py:61-77`) carrega `permissions[]` e `is_admin`. `get_token_payload` (`core/dependencies.py:20`) decodifica; `require_permission(x)` (`:75-88`) libera se `is_admin` ou `x in permissions`. Não há consulta ao banco por request.

Limitações: sem revogação (logout só apaga o token do `localStorage`); mudança de role/ativação vale no próximo login (≤ 8 h); sem refresh token; token também vai na query string do WebSocket (aparece em logs de acesso); `SECRET_KEY` tem default fraco aceito em qualquer ambiente (`config.py:35`) e o compose repete `CHANGE-ME-IN-PRODUCTION` (`docker-compose.yml:50`).

### 7.2 Matriz perfil × permissão (seed)
`S`=Solicitante `A`=Atendente `G`=Gestão `Ad`=Admin `Ʌ`=Administrador (todas).

| Permissão | S | A | G | Ad | Ʌ | Exigida por (backend) |
|---|---|---|---|---|---|---|
| `service_desk.tickets.create` / `.read` | ✓ | ✓ | ✓ | ✓ | ✓ | **ninguém** (só o frontend) |
| `assets.read_own` | ✓ | ✓ | ✓ | ✓ | ✓ | `GET /assets/{id}`, termo |
| `service_desk.tickets.manage` | | ✓ | ✓ | ✓ | ✓ | `ctx.is_technician` (service_desk, attachments) |
| `service_desk.interactions.internal` | | ✓ | ✓ | ✓ | ✓ | `ctx.can_internal_notes` |
| `assets.read`, `stock.read` | | ✓ | ✓ | ✓ | ✓ | assets/movements GET; stock GET |
| `service_desk.tickets.read_all` | | | ✓ | ✓ | ✓ | `ctx.can_read_all` |
| `service_desk.reports.read` | | | ✓ | ✓ | ✓ | `/tickets/reports/summary` |
| `inventory.read` / `.write` | | | ✓ | ✓ | ✓ | `/inventory` |
| `audit.read` | | | ✓ | ✓ | ✓ | **ninguém** (o endpoint exige `"admin"`) |
| `organization.*.read`, `system.data.export` | | | ✓ | ✓ | ✓ | organization GET; `/system/export`, `/system/demo/status` |
| `assets.write`, `stock.write`, `organization.*.create|update`, `identity.users.*`, `identity.roles.*` | | | | ✓ | ✓ | respectivos routers |
| `system.data.import`, `system.backup.manage`, `system.backup.download`, `integrations.whatsapp.manage` | | | | | ✓ | respectivos routers; `backup.manage` também protege SMTP e `/system/demo/*` |

Roles são editáveis em runtime (`/identity/roles`); o `seed.py` **sobrescreve** as permissões de `Administrador`, `Solicitante`, `Atendente`, `Gestão` e `Admin` a cada start (`seed.py:123-225`, executado pelo entrypoint), apagando customizações nesses perfis.

### 7.3 Pontos onde a regra não é só "permissão"
- Chamados: escopo por setor responsável / atribuído / solicitante (`service_desk/services.py:79-119`).
- Ativos: `assets.read_own` + dono (`assets/router.py:90-99`).
- Anexos: só `TICKET` valida (seção 3.1).
- WhatsApp `/tickets/{id}/send`, `/templates` (GET/preview), `GET /tickets/categories`: abertos a qualquer autenticado (ou a anônimos, no caso de categorias).

---

## 8. Configuração e deploy

### 8.1 Variáveis de ambiente

| Variável | Padrão | Origem | Obrigatória em produção? |
|---|---|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `gestao_ti` / `postgres` / `postgres` | compose `:26-28` | **sim** (senha) |
| `DB_PORT`, `API_PORT`, `HTTP_PORT` | `5432`, `8000`, `80` | compose | recomendável não publicar 5432/8000 |
| `DATABASE_URL` | montada no compose a partir das `POSTGRES_*` | compose `:49` | derivada |
| `SECRET_KEY` | `CHANGE-ME-IN-PRODUCTION` (compose) / `CHANGE-ME-IN-PRODUCTION-USE-STRONG-RANDOM-KEY` (`config.py:35`) | env | **sim**; nada impede subir com o padrão |
| `DEBUG` | `false` | env | não |
| `JWT_ALGORITHM`, `JWT_EXPIRATION_HOURS` | `HS256`, `8` | `config.py` | não |
| `CORS_ORIGINS` | JSON fixo no compose (`localhost:4200`, `localhost`) | compose `:53` | **sim** (hostname real) |
| `ATTACHMENT_STORAGE_PATH` | `/data/attachments` | compose + config | **sem efeito** (ignorada) |
| `ATTACHMENT_MAX_SIZE_MB`, `ATTACHMENT_ALLOWED_TYPES` | `100`, lista de 6 MIME | `config.py:40-49` | **sem efeito** |
| `BACKUP_STORAGE_PATH`, `BACKUP_MAX_KEEP` | `/data/backups`, `15` | `config.py:55,57` | efetivas |
| `BACKUP_RETENTION_DAYS`, `TICKET_REOPEN_DAYS` | `30`, `3` | `config.py` | **sem efeito** |
| `DATABASE_ECHO`, `API_V1_PREFIX`, `APP_NAME`, `APP_VERSION` | — | `config.py` | não |
| `EVOLUTION_*` (`PORT`, `SERVER_URL`, `API_KEY`) | `8084`, `http://localhost:8084`, `CHANGE-EVOLUTION-API-KEY-IN-PRODUCTION` | compose, só no profile `evolution` | sim, se usar WhatsApp |
| SMTP, WhatsApp (URL/chave/instância) | — | **banco** (`system_settings`, `wa_configs`), não env | via painel Admin |

`.env.example` cobre só 8 variáveis; `CORS_ORIGINS` e `SECRET_KEY` fraco passam sem erro.

### 8.2 Build e subida
- **Frontend não é construído pelo Compose.** O Nginx monta `./frontend/dist/plataforma-gestao-ti/browser` (`docker-compose.yml:82`) lido do host; é preciso `npm ci && npm run build` (`make fe-install fe-build`) antes de `up`. `README.md` omite esse passo. Angular `^22.2` (zoneless, commit `07f7c10`), Angular Material, Vitest.
- **Backend:** `backend/Dockerfile` (multi-stage, Python 3.12-slim, `pip install .` com `--trusted-host`, `postgresql-client`). Sem usuário não-root, sem `HEALTHCHECK` na imagem (existe no compose, `:63-68`).
- **Entrypoint** `backend/docker-entrypoint.sh`: `alembic upgrade head` → `python -m app.seed || true` (falha do seed é silenciada, `:8`) → `exec uvicorn … --workers 4`.
- **Migrations:** `alembic/env.py` importa os models à mão (`:20-32`) e **não importa** `app/core/settings_model.py` nem `access_control`; `alembic revision --autogenerate` tende a propor `drop_table system_settings` (inf). Testes não usam Alembic: `Base.metadata.create_all` em SQLite (`tests/conftest.py:62-66`); testes `pg`/`migrations` ficam *skipped* sem `TEST_DATABASE_URL`.
- **Healthcheck:** `GET /api/v1/health` verifica só `SELECT 1` (`main.py:96-117`); retorna 200 mesmo `degraded`. Nginx sem healthcheck e `depends_on` sem `service_healthy`.
- **CI** (`.github/workflows/ci.yml`): `uv sync --frozen && pytest` no backend; `npm ci`, `ng test`, `ng build` no frontend. Sem lint, sem build de imagem, sem teste de migration.
- **Atualização:** `git pull && docker compose up -d --build` reconstrói a imagem, mas como o código vem do bind mount, a imagem não é a unidade de deploy (inf: um `git pull` sem rebuild já atualiza o código ao reiniciar).

---

## 9. Convenções do código (as que existem de fato)

**Criar módulo novo** (padrão de `stock/`, `attachments/`):
1. `backend/app/<modulo>/{__init__,models,schemas,repository,services,router}.py`.
2. Model: `class X(Base, TimestampMixin[, SoftDeleteMixin])`, `id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)`, `__tablename__` com prefixo curto (`sd_`, `stk_`, `wa_`).
3. Repository recebe `AsyncSession`, usa `select()` e `flush()`; **não** commita (o `get_db` commita). Hoje há exceções (seção 2.3), não copiar.
4. Service recebe repository(ies) no `__init__`; lança `AppException` (abaixo).
5. Router: `APIRouter()`, dependência `get_xxx_service(db=Depends(get_db))`, permissão com `dependencies=[Depends(require_permission("modulo.recurso.acao"))]`.
6. **Registrar o router** em `app/main.py:_mount_routers` (import dentro da função, `include_router(..., prefix=...)`).
7. **Registrar o model** em `alembic/env.py:20-32` (import `# noqa: F401`) e, para os testes, basta ser importado via `app.main`.
8. Permissões novas: acrescentar em `seed.py:permissions_data` **e** nas listas de roles (`solicitante_codes`, `atendente_codes`, `gestao_codes`, `admin_local_codes`); o `Administrador` recebe todas automaticamente.
9. Frontend: `core/services/<x>.service.ts` (URL relativa `/api/v1/...`), `features/<x>/...` com `loadComponent`, `permissionGuard('<perm>')` em `app.routes.ts`, item no `sidebar.component.ts`.

**Migration:** `make migration MSG="..."` (autogenerate dentro do container) e `make migrate`. Os ids das revisões não são padronizados (hash do Alembic misturado com ids manuais `a1b2c3d4e5f6`…`g7b8c9d0e1f2`); cadeia linear, 1 head. Postgres-only (JSONB); revisar o autogenerate (ver 8.2).

**Exceções:** levantar `NotFoundException(entity, id)`, `ConflictException`(409), `ForbiddenException`(403), `UnauthorizedException`(401), `ValidationException`(422), `BusinessRuleException`(400), `StateTransitionException`(400) de `core/exceptions.py`. Formato de resposta: `{"error": {"code", "message", "details"}}` (`core/exceptions.py:134-194`). Nem sempre respeitado: `HTTPException` direto em `attachments`, `inventory_audit`, `whatsapp` (resposta `{"error": {code: "HTTP_ERROR"...}}` pelo handler Starlette, mas o frontend lê `err.error.detail` em alguns pontos).

**Paginação:** não há. `page/pageSize` existe em `core/pagination.py` sem uso; notificações usam `limit/offset` próprios (`notifications/router.py:28-29`), outbox `limit` (`le=200`).

**Timestamps/IDs:** UTC, `DateTime(timezone=True)`, `TimestampMixin` com `onupdate`. `datetime.now()` sem timezone aparece no termo (`assets/services.py:196`).

**Soft delete:** `SoftDeleteMixin.soft_delete()`; **cada repository** deve filtrar `is_active`/`deleted_at` (o mixin não aplica filtro global). Inconsistente entre módulos (4.2).

**Eventos/auditoria:** para registrar histórico, chamar `event_bus.emit(Event(...))` e deixar o `audit.listener` gravar; **não** gravar também direto no `AuditRepository` (hoje `service_desk` faz os dois).

**Idioma:** código e tabelas em inglês; mensagens ao usuário, docstrings e comentários em português. `snake_case` no Python, `camelCase` apenas em `pageSize`.

**Testes:** `backend/tests/<modulo>/` (alguns vazios) + `test_*.py` soltos em `backend/tests/`; fixtures em `conftest.py` e `factories.py`; SQLite em memória. Marcadores `pg`, `migrations`, `legacy_behavior` (`pyproject.toml:37-41`).

**Git:** só `main` + `origin/main`; commits grandes e multi-assunto (ex.: `44d5d0a`, `67a27b3`); mensagens semânticas misturando PT e EN.

---

## 10. Divergências documentação × código

| # | Documento diz | Código mostra |
|---|---|---|
| 1 | README: Frontend "Angular 18" | `frontend/package.json`: Angular `^22.2`, TypeScript `~6.0`, Vitest |
| 2 | ROADMAP: MOD-09 Contas/Acessos ✅ (backend, frontend e testes) | `app/access_control/` só tem `__init__.py`; sem router/model/tela |
| 3 | ROADMAP/STATUS: "MOD-11 Notificações ✅", sino em tempo real | nada cria notificações (`create_notification` sem chamadores); só existe e-mail |
| 4 | STATUS item 14: `Notification Dispatcher` dispara alertas ao atribuir/mudar status | classe sem nenhuma referência; não é invocada |
| 5 | docs 01/02/10, compose e `.env`: anexos em `/data/attachments` (volume `attachments_data`) | gravados em `/app/uploads` (`attachments/service.py:11`); `ATTACHMENT_STORAGE_PATH` ignorada. `core/demo_service.py:180` apaga em outro caminho (`attachment_storage_dir`) |
| 6 | STATUS: "diretório protegido contra acesso público" para backups; backup consistente e "restauração via terminal" | restore existe como API (`POST …/restore`); o backup só contém o banco (anexos/logo fora); sem agendamento |
| 7 | STATUS: "Suíte executada com 100% de sucesso" / "92 aprovados" | **(exec)** 117 passed, 4 failed, 1 xfailed: 2 falhas de `setup` (`corporate_name`), 2 de backup (`pg_dump` ausente no ambiente) |
| 8 | STATUS: Admin com "35 permissões", `Gestão` "13", `Atendente` "7" | seed atual: 3 permissões nunca exigidas; contagens por role diferem (`gestao_codes` tem 17) |
| 9 | docs/ROADMAP: perfis `Gestor`, `Técnico`, `Colaborador` | roles reais: `Administrador`, `Admin`, `Gestão`, `Atendente`, `Solicitante` |
| 10 | ROADMAP: endpoint `/inventory-audits` | rota real `/api/v1/inventory` (`main.py:140-141`) |
| 11 | STATUS: auditoria exige `audit.read` (implícito pelo perfil Gestão) | endpoint exige `"admin"` (`audit/router.py:26`); Gestão não consegue ver |
| 12 | nginx.conf cabeçalho: `/ws/*` → WebSocket | o WS usa `/api/v1/notifications/ws`; bloco `/ws/` é morto |
| 13 | docker-compose cabeçalho: "Nginx: proxy reverso + static files" e README "make migrate / make seed" manuais | Nginx não serve `/static` do backend; migrate/seed rodam no entrypoint (e `README` omite o build do frontend) |
| 14 | docs: segurança "SECRET_KEY obrigatório" (docs/09) e `ADR-003` "arquivos fora do banco" | `SECRET_KEY` default aceito; ADR-003 vale (arquivos em disco), mas fora de qualquer volume/backup |
| 15 | Código e docs citam `DEC-001…DEC-013` (ex.: `core/events.py` → DEC-013, `soft_delete.py` → DEC-004) | só existem `ADR-001..005`, `DEC-006` e `DEC-012` em `docs/decisions/`; as demais decisões não têm arquivo |
| 16 | README: lista de módulos termina em MOD-12 | existem MOD-13 (`data_transfer`), MOD-14 (`backup`), MOD-15 (`whatsapp`) sem doc de módulo em `docs/modules/` (só assets, movements, service-desk, core) |
| 17 | Evolution API: `api_url` default do model `http://evolution-api:8080` (`whatsapp/models.py:26`) | compose publica/anuncia `8084` (`docker-compose.yml:96,98`); porta interna do serviço não é configurada (inf: pode não casar) |

Documentação redundante (para consolidar na Fase 2): `docs/system-overview.md` × `docs/architecture/overview.md` × `docs/01-arquitetura-do-sistema.md`; `docs/user-guide.md` × `docs/06-manual-de-utilizacao.md`; `STATUS_PENDENCIAS.md` × `ROADMAP.md`.

---

## 11. Como manter este arquivo

| Se mudar… | Atualizar seção |
|---|---|
| `main.py` (router montado/removido), nova pasta em `app/` | 1, 3 |
| `docker-compose.yml`, `Dockerfile`, `nginx.conf`, entrypoint | 2.1, 5, 8 |
| `config.py` ou `.env.example` | 8.1 |
| Qualquer `models.py` ou migration | 4, 5 |
| Router: rota, permissão ou escopo | 3.1, 7 |
| `seed.py` (permissões/roles) | 7.2 |
| `core/dependencies.py`, `core/security.py`, `identity/services.py` (token) | 6.1, 7.1 |
| Fluxos de chamado, ativo, anexo, estoque, backup, WhatsApp, notificação | 6 |
| Novo evento no `event_bus` ou novo listener | 3.3 |
| Nova convenção ou padrão adotado | 9 |
| Docs/README/ROADMAP alterados ou removidos | 10 |

Regras: atualizar o mapa **no mesmo commit** da mudança; citar `arquivo:linha` ao incluir afirmação técnica (revisar as linhas após refatorações); marcar **(exec)**/**(inf)**; ao corrigir um item da seção 10, apagar a linha em vez de riscá-la.
