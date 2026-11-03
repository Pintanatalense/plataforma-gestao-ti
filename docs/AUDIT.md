# AUDIT — Plataforma de Gestão de TI

> **Documento histórico (instantâneo de 2026-10-15/21).** Descreve o repositório antes das fases A–G e do PR de endurecimento da importação GLPI; os achados abertos não foram reconciliados com o estado atual. Para o diagnóstico vigente e o plano atual, veja `docs/plans/plano-evolucao.md`.

> Base: commit `a544af7` (main). Auditoria de 2026-10-15. Mapa de referência: `docs/PROJECT_MAP.md`.
> **Como validei:** stack real via Docker Compose numa cópia isolada do commit (projeto `gtiaudit`, volumes e portas próprios; nenhum container/volume existente foi tocado), scripts de API contra Nginx (`:18080`) e `pytest` do backend.
> Marcadores: **(exec)** = reproduzi na stack ou no pytest; **(lido)** = confirmado só no código; **(inf)** = dedução sem confirmação.
> Desvios do compose original na cópia de teste (para poder continuar após o P0-1): removi `container_name`, remapeei portas, e usei `alembic upgrade heads`. Nada disso foi alterado no repositório.
> **Não auditado a fundo:** `data_transfer/import_service.py` (injeção/validação de CSV), `seed_demo.py`, a UI Angular (fora de grep de sinks e leitura de fluxos), carga/performance real, Evolution/Meta com provedor real, SMTP real.

---

## 0. Status após a Fase 0 (branch `fix/phase-0-hardening`)

Validado na stack real (instalação do zero, `docker compose up --build`) e na suíte (`pytest`). O corpo deste documento permanece como foi escrito na auditoria, com o estado **antes** das correções.

| Item | Status | Observação |
|---|---|---|
| P0-1 Alembic duas cabeças | **Corrigido** | revisão de união + teste de cabeça única + `alembic upgrade head` no CI; upgrade a partir de `c2a8f41e9b03` validado |
| P0-2 Path traversal em anexos | **Corrigido** | enum fechado, nome UUID, caminho conferido, tipo/assinatura/tamanho, autorização por entidade, container não-root |
| P0-3 JWT forjável / chave padrão | **Corrigido** | `SECRET_KEY` obrigatória (≥ 32, sem "CHANGE-ME"); usuário verificado no banco a cada request |
| P0-4 Restore trava o sistema | **Corrigido** | restore saiu da API; `scripts/restore-backup.sh` validado (inclui falha sem aplicar). Achado extra: cliente `pg_dump` 17 gerava dumps que o PG 16 não restaura → imagem usa `postgresql-client-16` |
| P0-5 Webhook aberto | **Corrigido** | `X-Webhook-Secret`, sem eco de resposta, sem vínculo por matrícula (vínculo com código fica para a Fase C do ADR-013) |
| P1-1 Auditoria duplicada | **Corrigido** (tickets) | `organization` ainda usa o bus; unifica no outbox |
| P1-2 Estoque sem lock | **Corrigido** | 40 saídas paralelas → saldo 0; teste `pg` |
| P1-3 Anexos de ativo | **Corrigido** | junto de P0-2 |
| P1-4 XSS no termo | **Corrigido** | `html.escape`; logo agora só PNG/JPEG |
| P1-5 / P1-6 rotas abertas | **Corrigido** | teste de contrato percorre o OpenAPI |
| P1-7 provedor MOCK padrão | **Corrigido** | padrão `NONE` (desabilitado); MOCK marca "simulada" |
| P1-8 revogação / lockout / troca de senha | **Corrigido, com limite** | usuário desativado perde acesso na hora; permissões ainda vêm do token (≤ 8 h); lockout 5 falhas/15 min; troca de senha imposta no servidor |
| P1-9 `/audit` e permissões fantasmas | **Corrigido** (`audit.read`); `service_desk.tickets.create/read` seguem sem uso |
| P1-10 seed sobrescreve perfis | **Corrigido** | perfis existentes preservados; seed não duplica empresa renomeada |
| P1-11 setup ignora nome | **Corrigido** | |
| P1-12 bind mount do código | **Corrigido** | volumes nomeados; override de dev separado |
| P1-13 backup incompleto/sem agenda | **Aberto** | anexos/logo fora do dump; sem agendamento (Fase A do ADR-013) |
| P1-14 fila WhatsApp sem worker | **Aberto** | Fase A/D do ADR-013 |
| P1-15 ciclo de ativos por chamado | **Corrigido** | escopo do chamado + corpo tipado |
| P1-16 FK do autor no WhatsApp | **Corrigido** | |
| P1-17 portas expostas | **Corrigido** | só o Nginx publica porta |
| **Novo (achado na Fase 0)** | Corrigido | `can_read_all` era concedido a todo técnico (`tickets.manage`), tornando inútil o isolamento por setor; agora só `read_all`/admin |
| **Novo** | Corrigido | `npm ci` falhava (ERESOLVE) por `@angular/cdk` 22.2.2 vs. Material 22.2.1 → o build de imagem e o CI do frontend quebravam |
| P2-1…P2-22 | **Aberto** | exceto: P2-1 parcial (usuário não-root), P2-18/P2-20 parcial (CI roda migration) |

---

## 0.1 Status após a Fase A (branch `feat/phase-a-notification-core`)

Hub de notificações do ADR-013 (outbox + worker + in-app + e-mail + backup agendado). Validado em PostgreSQL real e na stack Compose.

| Item | Status | Observação |
|---|---|---|
| P1-13 backup sem agenda | **Parcial** | backup diário às 02:00 (fuso `America/Fortaleza`) pelo worker, com alerta crítico de falha; **anexos e logo continuam fora do dump** |
| P1-14 fila WhatsApp sem worker | **Aberto** | `wa_outbox` segue sem consumidor; sai na Fase D (substituída por `deliveries`) |
| P1-1 auditoria do `organization` no bus | **Aberto** | tickets já gravavam uma vez; a unificação da auditoria como consumidor do outbox **não foi feita** na Fase A (o bus segue só para auditoria) |
| P2-12 senha SMTP em texto puro | **Corrigido** | `channel_configs` + Fernet (`APP_ENCRYPTION_KEY`); migration cifra a senha antiga |
| Achado 1.6 (notificações nunca criadas) | **Corrigido** | chamado novo/atribuído/status/resposta geram entregas; nota interna nunca chega ao solicitante (DEC-012, teste) |
| Achado 1.6 (WS com 4 workers) | **Corrigido** | `LISTEN/NOTIFY` entre worker e APIs (teste `pg`) |
| **Novo** | Corrigido | `backend/Dockerfile` instalava as dependências sem o `uv.lock` (versões soltas); uma release do SQLAlchemy sem wheel quebrou o build. Agora instala do lock |

---

## 1. Reconferência dos 8 problemas da revisão anterior

| # | Problema | Status | Evidência |
|---|---|---|---|
| 1 | Backup "falso" com `SUCCESS` sem `pg_dump` | **Corrigido (geração); restore quebrado** | Imagem instala `postgresql-client` (`backend/Dockerfile:30`); sem binário levanta e grava `FAILED` (`backup/services.py:93-103,153`). **(exec)** `POST /system/backups/generate` gerou `.sql.gz` real, `verify` retornou `is_valid=true`. Mas o **restore via API trava** (P0-4). |
| 2 | Anexos em `/app/uploads`, ignora `ATTACHMENT_STORAGE_PATH`/volume | **Aberto** | `attachments/service.py:11`. **(exec)** arquivos em `/app/uploads/asset/<id>/…` (bind mount `./backend/uploads` no host); `/data/attachments` (volume `attachments_data`) vazio. `ATTACHMENT_*` sem nenhum uso. `core/demo_service.py:180` apaga em outro caminho. |
| 3 | `verify_entity_access` só protege `TICKET`; `entity_type` livre; sem validação de tipo/tamanho | **Aberto, pior que o descrito** | **(exec)** Solicitante enviou anexo a um ativo (201), outro Solicitante listou, baixou e **apagou** (204). `entity_type="../../../tmp/pwn"` retornou 201 e o arquivo foi gravado em `/tmp/pwn/<id>/….txt` **fora de `uploads`**, com o container rodando como root (`id -u`=0). `.exe` de 30 MB aceito; HTML servido como `text/html`. |
| 4 | Webhook sem autenticação; vínculo só por matrícula | **Aberto** | **(exec)** `POST /integrations/whatsapp/webhook` sem header: 200 e a **resposta do bot volta no corpo HTTP**. Número arbitrário foi vinculado ao colaborador de matrícula `200` só digitando `200`, e o bot passou a tratá-lo como esse colaborador. `webhook_secret` gravado e nunca lido (`grep`: só `models.py:29`, `router.py:186`, `schemas.py:44`). |
| 5 | Termo detectado por nome de arquivo, sem vínculo | **Aberto** | Lógica só no frontend (`asset-detail.component.ts:148-163`: `termo/cautela/assinado/responsabilidade` ou qualquer `.pdf`). **(exec)** o backend aceita qualquer anexo `ASSET` e não registra emissão/assinatura/vínculo com colaborador ou movimentação. |
| 6 | Dispatcher nunca chamado; WebSocket em memória com 4 workers | **Aberto** | `WhatsAppNotificationDispatcher`: zero referências. `create_notification`: zero chamadores. **(exec)** abrir chamado e atribuir não gerou nenhuma notificação (0 para solicitante e atendente). WS mantém `dict` por processo e `--workers 4` (`backend/Dockerfile:38`); hoje irrelevante porque ninguém emite. |
| 7 | Logo em `/app/static`; `/static` inexistente no Nginx | **Aberto** | **(exec)** `GET :18080/static/logo.html` devolve o `index.html` do SPA (fallback); só `:18000/static/…` (porta da API, exposta) serve o arquivo. Logo aceita qualquer extensão: `logo.html` enviado com 200 e servido como `text/html`. |
| 8 | HTML do termo sem escape; `SECRET_KEY` padrão aceito; Postgres exposto | **Aberto (3 de 3)** | **(exec)** nome de ativo `<script>alert(1)</script>Dell` aparece cru no termo; valores de `technical_specs` idem (`assets/services.py:188-190,349`). **(exec)** token HS256 forjado com a chave padrão do compose (`CHANGE-ME-IN-PRODUCTION`), `sub` aleatório e `is_admin=true`, deu **200** em `/audit`, `/identity/users` e `/system/backups`. **(exec)** Postgres acessível no host com `postgres:postgres` (`docker-compose.yml:29-30`). |

Novos itens que **derrubam** itens antigos: nenhum. Corrigido de verdade: só o 1 (parcialmente).

---

## 2. Novas fragilidades

Esforço: **B**aixo (< 0,5 dia), **M**édio (0,5–2 dias), **A**lto (> 2 dias).

### P0 — perda de dados, falha explorável, bloqueio de produção

**P0-1. Instalação limpa não sobe: duas cabeças no Alembic**
- Descrição: `a1b2c3d4e5f6` e `g7b8c9d0e1f2` têm o mesmo `down_revision = f6a7b8c9d0e1`.
- Impacto: o entrypoint (`set -e` + `alembic upgrade head`, `docker-entrypoint.sh:5`) falha, o container reinicia em loop e o Nginx responde 502. Qualquer instalação nova ou ambiente restaurado está bloqueado. Quem tem banco já migrado não percebe.
- Evidência **(exec)**: log `Multiple head revisions are present`; `alembic heads` lista `b2c3d4e5f6a7` e `g7b8c9d0e1f2`.
- Correção: migration de merge (`alembic merge heads`) ou reordenar `g7b8…` para depois de `b2c3…`; testar `upgrade head` em Postgres vazio no CI.
- Esforço: B.

**P0-2. Path traversal / escrita arbitrária de arquivo no upload**
- Descrição: `entity_type` livre vira diretório (`attachments/service.py:28`: `os.path.join(UPLOADS_DIR, entity_type.lower(), …)`); extensão vem do nome enviado; qualquer usuário autenticado passa (`verify_entity_access` ignora tipos ≠ `TICKET`).
- Impacto: escrita de arquivo com conteúdo e extensão controlados em qualquer diretório gravável pelo processo (root no container; bind mount do host em `./backend`, ou seja, escrita dentro do código-fonte, que é executado, `docker-compose.yml:59`). Caminho para execução de código com um simples Solicitante.
- Evidência **(exec)**: arquivo criado em `/tmp/pwn/…`.
- Correção: `entity_type` como enum fechado (`TICKET`, `ASSET`, …), nome de arquivo no disco só `uuid` sem extensão do cliente, `resolve()` + checagem de que o caminho final fica sob a raiz, validação de MIME/tamanho (usar as configs que já existem), `USER` não-root.
- Esforço: B–M.

**P0-3. JWT forjável com a `SECRET_KEY` padrão; sem validação de usuário no banco**
- Descrição: a chave default é aceita em qualquer ambiente (`config.py:35`, compose `:50`); o backend confia no payload (`dependencies.py:20-32`), então `is_admin=true` com `sub` inexistente funciona.
- Impacto: controle total (backups com todos os dados, usuários, WhatsApp). Basta o sistema subir sem `.env` ajustado, o que o `.env.example` e o README encorajam (cópia literal).
- Evidência **(exec)** na seção 1, item 8.
- Correção: falhar na inicialização se `SECRET_KEY` for o default ou curta (< 32), sem default no compose; carregar o usuário (e seu `is_active`) por request ou ao menos cache curto com `token_version`.
- Esforço: B (chave) + M (validação por request).

**P0-4. Restore via API trava o sistema**
- Descrição: `restore_backup` executa `psql` com `--clean` (DROP/CREATE) enquanto a própria requisição e outros workers mantêm sessões abertas no mesmo banco; há também o `FOR UPDATE`/locks de outras conexões. Sem `ON_ERROR_STOP`, sem janela de manutenção, sem backup prévio, tudo em memória (`backup/services.py:205-259`).
- Impacto: a requisição nunca responde, o DDL espera locks, e **logins e demais requests ficam bloqueados** (`pg_stat_activity` mostrou `ALTER TABLE … DROP CONSTRAINT` e um `SELECT user_accounts` em `wait_event_type=Lock`). Foi preciso reiniciar o backend. Se o restore falha no meio (psql não aborta), o banco fica meio restaurado, sem aviso.
- Evidência **(exec)** + **(exec)** restore manual com o backend parado funcionou (estado do momento do backup, 1 linha `ERROR` ignorada pelo psql).
- Correção: remover o restore da API (procedimento documentado/CLI com app parado), ou fazer em container/serviço separado com `pg_restore`/`psql -v ON_ERROR_STOP=1 --single-transaction`, backup de segurança automático antes e pós-verificação. Incluir anexos/logo no backup.
- Esforço: M.

**P0-5. Webhook do WhatsApp sem autenticação (vazamento + sequestro de vínculo)**
- Descrição: ver seção 1, item 4. Quem conhece a URL envia mensagens "como" qualquer telefone, lê as respostas (nomes de colaborador, títulos e status de chamados), abre chamados e grava telefone no cadastro de um colaborador a partir da matrícula (`conversation_service.py:110-117`; matrículas são sequenciais/descobríveis).
- Impacto: acesso não autenticado a dados de chamados, personificação de colaboradores, spam de chamados. LGPD.
- Evidência **(exec)**.
- Correção: validar segredo/assinatura (Evolution `apikey` / HMAC da Meta) com `hmac.compare_digest`; não devolver `reply` no corpo; vínculo por código de verificação enviado a um canal já confiável (e-mail corporativo) e não só matrícula; limite de tentativas.
- Esforço: M.

### P1 — funcionalidade quebrada ou enganosa, risco operacional relevante

**P1-1. Auditoria duplicada** — `_record_audit_event` grava direto **e** emite no bus, cujo listener grava de novo (`service_desk/services.py:824-851`, `audit/listener.py`). **(exec)** `ticket.created` aparece 2× no histórico e 2× em `audit_logs`. Impacto: linha do tempo do chamado e relatórios com eventos em dobro; os testes passam porque não executam o lifespan. Correção: só um caminho (emitir no bus). Esforço: B.

**P1-2. Perda de atualização no estoque** — `add_movement` lê o item sem lock (`stock/services.py:116`, `stock/repository.py:69`). **(exec)** 40 saídas simultâneas de 1 unidade sobre saldo 40: 40 respostas `200`, 40 movimentos gravados, **saldo final 38** (esperado 0). Correção: `SELECT … FOR UPDATE` (já feito para ativos) ou `UPDATE … SET quantity = quantity - :q WHERE quantity >= :q`. Esforço: B.

**P1-3. Anexos de ASSET lidos/apagados por qualquer autenticado; XSS por HTML** — ver 1.3. Download devolve o `content_type` enviado pelo cliente (`attachments/router.py:97-101`). Correção junto de P0-2: autorização por tipo de entidade (ativos: `assets.read`/dono), `Content-Disposition: attachment`, `nosniff`. Esforço: M.

**P1-4. XSS no termo de responsabilidade** — **(exec)** HTML cru no termo (`assets/services.py:188-190,323-349`). O frontend abre o termo como Blob (`asset.service.ts:139-147`); blob herda a origem da app, então script executa com acesso ao `localStorage` onde está o JWT (`auth.service.ts:56,72`). Quem tem `assets.write` ataca quem imprime o termo (admins). Correção: `html.escape` em tudo interpolado (ou Jinja2 com autoescape). Esforço: B.

**P1-5. `POST /whatsapp/tickets/{id}/send` aberto a qualquer autenticado** — **(exec)** Solicitante enviou mensagem arbitrária ao WhatsApp do solicitante de **outro** chamado (200, `SENT`) e a mensagem foi gravada como interação pública. Endpoints `GET /templates` e `POST /templates/{id}/preview` sem sequer autenticação **(exec: 200 sem token)**. Correção: `require_permission` + `get_ticket_for_user`. Esforço: B.

**P1-6. `GET /tickets/categories` sem autenticação** — **(exec)** 200 sem token (teste marcado `xfail`, `R1`). Esforço: B.

**P1-7. Provedor `MOCK` por padrão marca mensagens como `SENT`** — `get_config` cria `provider="MOCK", is_enabled=True` (`conversation_service.py:37`); o adapter só loga. **(exec)** outbox mostrou `SENT`, 0 tentativas, sem nenhum envio real. Painel verde sem entrega. Correção: padrão `NONE/desabilitado`, status distinto para mock. Esforço: B.

**P1-8. Sem revogação nem validação de usuário no token** — **(exec)** usuário excluído continua com `GET /tickets` 200 até o token expirar (8 h); login dele já falha. `must_change_password` não é imposto no backend **(exec: 200)**. Sem rate limit/lockout **(exec: 30 senhas erradas seguidas, todas 401, login legítimo depois 200)**. Junto de P0-3. Esforço: M.

**P1-9. Perfil `Gestão` não acessa a auditoria; permissões fantasmas** — `/audit` exige `"admin"` (`audit/router.py:26,36`) que não existe; **(exec)** Gestão → 403 apesar de ter `audit.read`. `service_desk.tickets.create/read` e `audit.read` nunca são exigidas. Esforço: B.

**P1-10. `seed.py` sobrescreve roles a cada start** — sincroniza permissões de `Administrador/Solicitante/Atendente/Gestão/Admin` (`seed.py:123-225`) pelo entrypoint: personalizações feitas na tela de perfis somem a cada restart. E o `|| true` (`docker-entrypoint.sh:8`) esconde falha do seed. Esforço: B.

**P1-11. Setup ignora o nome da empresa e quebra sem seed** — `Company(corporate_name=…)` (`identity/services.py:129,136`). **(exec)** após `setup` com `company_name="Minha Empresa XYZ"`, `/organization/company/public` continua "Empresa Padrão"; **(exec pytest)** 2 testes de setup falham com `TypeError`. Esforço: B.

**P1-12. Bind mount `./backend:/app` em "produção"** — a imagem não é a unidade de deploy; anexos/logo/`__pycache__` caem dentro do repositório do host; `--build` não garante o que roda. Correção: remover o mount (ou mover para `docker-compose.override.yml` de dev), volumes nomeados para `/data/attachments`, `/app/static`. Esforço: B.

**P1-13. Backup incompleto, sem agendamento e no mesmo host** — só banco; anexos e logo fora; nada agenda ou alerta falha; `BACKUP_RETENTION_DAYS` inerte. Segredos (SMTP, `api_key`) vão em claro no dump. Esforço: M.

**P1-14. Fila do WhatsApp sem worker** — **(lido)** `process_outbox` só roda quando alguém clica ou envia outra mensagem; itens `PENDING` por cooldown/limite ficam parados; sem `SKIP LOCKED` (dois workers podem enviar o mesmo item). Esforço: M (resolvido pela Fase 3).

**P1-15. Ciclo de ativos por chamado sem escopo/permissão de ativo** — `reserve/deliver/return/inspect` exigem só `is_technician` e leem o chamado com `repo.get_ticket` direto (`service_desk/services.py:498+`), sem `get_ticket_for_user` nem `assets.write`; `Atendente` não tem `assets.write`, mas entrega ativos por esta rota. Body como `dict` cru (`router.py:339+`), `uuid.UUID(...)` inválido vira 500. Esforço: B.

**P1-16. WhatsApp: interação de colaborador sem `UserAccount` viola FK** — usa `employee.id` como `author_id` (`conversation_service.py:296`), que é FK para `user_accounts.id`. **(inf)** erro em Postgres. Esforço: B.

**P1-17. Postgres e API expostos no host com credenciais padrão** — **(exec)**. Esforço: B (remover `ports` ou ligar a 127.0.0.1).

### P2 — dívida técnica, manutenção, inconsistência

| # | Item | Evidência | Esforço |
|---|---|---|---|
| P2-1 | `Dockerfile`: `--trusted-host` (desliga verificação TLS do pip), usuário root, sem `HEALTHCHECK` na imagem | `backend/Dockerfile:17,19` | B |
| P2-2 | Pool 20+10 × 4 workers pode exceder `max_connections=100` | `database.py:23-25`, `Dockerfile:38` (inf) | B |
| P2-3 | Healthcheck só `SELECT 1`; 200 mesmo em `degraded`; sem checar disco/volumes/migração | `main.py:96-117` | B |
| P2-4 | Logs sem formato nem nível configurados; sem correlação de request; sem métricas | `logging` default | M |
| P2-5 | Erros engolidos: `except … pass` em 7 pontos (remoção de arquivo, retenção de backup, WS, detecção demo, envio WA) e `except Exception` + log em notificação/auditoria | `backup/services.py:91,317,328`, `notifications/services.py:44`, `service_desk/services.py:208`, `whatsapp/router.py:603`, `attachments/service.py:85` | B |
| P2-6 | Sem paginação: todas as listagens retornam tudo; `PaginatedResponse` sem uso; relatório gerencial carrega todos os chamados em memória | `service_desk/services.py` `get_tickets_summary_report` | M |
| P2-7 | `lazy="selectin"` em 15 relações (carrega usuário/colaborador em cascata), `get_user_context` faz 2 queries por request, histórico itera `log.user_name` | models | M |
| P2-8 | Poucos índices: 13 `index=True` para dezenas de FKs (`sd_ticket.requester_id/assignee_id/responsible_sector_id/status`, `asset_movements.asset_id`, `stk_movements.item_id` sem índice) | `models.py` (lido) | B |
| P2-9 | CORS `allow_methods/headers=["*"]` com credenciais; sem `Content-Security-Policy`/HSTS; `X-XSS-Protection` obsoleto | `main.py:63-69`, `nginx.conf:63-66` | B |
| P2-10 | Token JWT em `localStorage` e na query do WebSocket (vai para log de acesso do Nginx) | `auth.service.ts:72`, `notifications.service.ts:48` | M |
| P2-11 | IP do cliente de `X-Forwarded-For` sem proxy confiável | `dependencies.py:59-72` | B |
| P2-12 | SMTP/WhatsApp: segredos em texto no banco; SMTP reaproveita `system.backup.manage` | `email_service.py:83`, `email_router.py` | M |
| P2-13 | Transações: repositórios e routers commitam por conta própria; `NotificationRepository.create` comita dentro de fluxo maior | `notifications/repository.py:17`, `service_desk/router.py` | M |
| P2-14 | Concorrência: criação de usuário/email/tag sem tratamento de `IntegrityError` (condição de corrida vira 500); `setup` público tem corrida entre duas chamadas simultâneas na instalação (inf) | `identity/services.py`, `assets/services.py:54` | B |
| P2-15 | Idempotência: nenhum endpoint de escrita aceita chave de idempotência (duplo clique abre 2 chamados/2 movimentos) | geral | M |
| P2-16 | Órfãos: `entity_id` de anexo/auditoria sem FK; exclusão lógica de ativo/chamado deixa anexos no disco; `demo clean` apaga no caminho errado | 4.1 do mapa | M |
| P2-17 | LGPD: documentos de colaborador (termos assinados) em disco sem criptografia, sem política de retenção/descarte, acessíveis a qualquer autenticado; matrícula+telefone expostos pelo webhook | — | M |
| P2-18 | Módulos/código morto: `access_control`, `Dispatcher`, `pagination`, `check_registry.py`, `seed_service_desk.py`, configs inertes, `tests/` da raiz | mapa §1 | B |
| P2-19 | `alembic/env.py` não importa `settings_model`/`access_control`: autogenerate tende a propor `drop_table system_settings` | `alembic/env.py:20-32` (inf) | B |
| P2-20 | CI não roda lint, build de imagem nem `alembic upgrade head`; testes `pg`/`migrations` pulados sem `TEST_DATABASE_URL`; CI não detectaria P0-1 | `ci.yml` | B |
| P2-21 | Lógica de negócio no frontend (termo assinado por nome) e tipos `dict` crus em rotas | 1.5, P1-15 | B |
| P2-22 | Fuso: `datetime.now()` sem tz no termo (`assets/services.py:196`); CSV import com fallback `latin-1` silencioso | — | B |

---

## 3. Validação de funções

Ambiente: stack Docker (Postgres 16, 4 workers, Nginx) e `pytest` do backend. Resultado do pytest local: **117 passed, 4 failed, 1 xfailed**. As falhas: 2× `setup` (P1-11) e 2× `test_backup` (o `DATABASE_URL` de teste aponta para Postgres e `pg_dump` não existe na máquina de desenvolvimento; os testes dependem do ambiente, não mockam nem usam o dump SQLite que o serviço prevê).

| Fluxo (mapa §6) | Funciona? | Como testei | Resultado |
|---|---|---|---|
| 6.1 Login/JWT | Sim, com ressalvas | API + token forjado | login OK; sem revogação, sem rate limit, `must_change_password` não imposto, chave padrão forjável (P0-3, P1-8) |
| 6.2 Setup inicial | Parcial | API + pytest | cria admin e loga; **nome da empresa ignorado**; 2 testes falham (P1-11) |
| 6.3 Chamado (abrir, atribuir, interagir, histórico) | Sim | API | abre, atribui, PATCH de status OK; escopo de leitura entre solicitantes correto (403 em anexo de chamado alheio); histórico com evento duplicado (P1-1) |
| 6.4 Ativo + termo | Parcial | API | ativo criado e termo gerado; sem vínculo termo↔movimentação/colaborador, assinatura só no front, XSS (P1-4) |
| 6.5 Anexos | Funciona e é inseguro | API | upload/list/download/delete OK; autorização, traversal, tipo/tamanho e local (P0-2, P1-3) |
| 6.6 Estoque | **Não é confiável sob concorrência** | 40 requisições paralelas | saldo 38 em vez de 0 (P1-2). Saída simples funciona |
| 6.7 Inventário | Funciona como registro | leitura + testes | não gera divergências nem ajusta nada; é um checklist |
| 6.8 Backup/restore | Gera OK, restore API **não** | API + restore manual | P0-4 |
| 6.9 WhatsApp (entrada/saída) | Parcial / inseguro | webhook e envio por API, provedor MOCK | máquina de estados responde; vínculo e envio inseguros; provedor real **não testado** |
| 6.10 Notificação in-app | **Não funciona** | API | nenhuma notificação criada pelo sistema (0) |
| Boot com migrations | **Não funciona** | `docker compose up` | P0-1 |

### 3.1 Os testes testam comportamento real?

- **Banco diferente do real:** tudo roda em SQLite em memória com `Base.metadata.create_all` (`tests/conftest.py:62-66`). Não cobre Alembic (P0-1 passa despercebido), `FOR UPDATE`, JSONB real, concorrência nem restore.
- **Lifespan não executa:** `ASGITransport` não dispara o `lifespan`, então o listener de auditoria nunca é registrado nos testes; a duplicação (P1-1) e o histórico completo não são exercitados.
- **Provedor falso por padrão:** o WhatsApp roda com `MockWhatsAppAdapter` que sempre retorna `True`; os testes confirmam o fluxo, não a entrega.
- **Baselines "legacy_behavior" e `xfail`:** `tests/baseline/*` fixam comportamento atual (por exemplo categorias sem auth) como xfail documentado, útil, mas não corrigido.
- **E2E de pé forçado:** `test_e2e_lifecycle.py` valida "notificação push" no ciclo, o que só passa porque o teste insere a `Notification` direto no banco (`test_e2e_lifecycle.py:235-242`); o sistema não a cria.
- **Pastas vazias:** `tests/{access_control,assets,movements,service_desk,stock,inventory_audit}/` contêm só `__init__.py` (os testes reais ficam soltos na raiz de `tests/`).

### 3.2 Testes que faltam (mínimo útil, sem cobertura excessiva)

1. **Migrations em Postgres vazio** (`alembic upgrade head` + `alembic check` sem diff) no CI. Pegaria P0-1 e P2-19.
2. **Anexos:** `entity_type` inválido → 422; usuário sem permissão no ativo → 403; arquivo fora da raiz impossível.
3. **Estoque concorrente** (`pytest.mark.pg`): N saídas paralelas nunca deixam saldo negativo nem incorreto.
4. **Webhook:** sem segredo → 401/403; vínculo exige código.
5. **Auth:** chave padrão rejeitada no boot; usuário desativado perde acesso; endpoints sem auth listados por um teste que percorre `app.routes` e falha se uma rota não-pública não tiver dependência de auth (teste de contrato barato, pegaria P1-5/P1-6).
6. **Restore:** teste de integração com Postgres descartável (gera, altera, restaura, confere).
7. **Auditoria com lifespan real** (um evento = uma linha).

---

## 4. Aderência aos seus padrões

| Critério | Situação | Evidência | Ação |
|---|---|---|---|
| Simplicidade, modularidade, baixo acoplamento | **Parcial** | Pastas por módulo e camadas existem, mas: 78 imports `from app…` dentro de funções em 14 arquivos (fuga de ciclo), models importando models de outros módulos (`organization/models.py:22` ← `stock`, `assets/models.py:21` ← `organization`), `service_desk` conhece `assets`, `movements`, `stock`, `audit`, `notifications`; `attachments` importa `service_desk`; routers com SQL | Definir fronteiras: módulos conversam por `services` ou eventos; `TYPE_CHECKING` + `relationship("Nome")` em string elimina importações cruzadas de models |
| Sem overengineering, sem abstração desnecessária | **Parcial** | Excesso onde não importa: máquina anti-ban elaborada com fila e jitter (`queue_service.py`), `core/pagination.py`, `Dispatcher`, `check_registry`, `access_control`, modo demo com 1.900 linhas (`seed_demo.py` 1420 + `demo_service.py` 469) e hard delete em massa. Falta onde importa: outbox sem worker, sem locks | Remover o morto; o modo demo vale um script separado, não código de produção com `is_demo` em 12 tabelas |
| Dependências mínimas, open source, self-hosted, Docker simples e atualização previsível | **Parcial** | Poucas libs Python (13). Mas: frontend não é construído pelo Compose (README omite); bind mount do código; `--trusted-host`; instalação nova quebra (P0-1); sem versão fixada de imagem Python/uv no Dockerfile (CI usa `uv.lock`, a imagem usa `pip install .` sem lock → builds diferentes) | Multi-stage com build do Angular no Dockerfile do Nginx; usar `uv.lock` na imagem; remover o mount |
| Clareza, `snake_case`, inglês, comentários úteis | **Atende (majoritariamente)** | Código em inglês, docstrings em PT. Comentários de tarefa e de "justificativa" em excesso (ex.: `conversation_service.py:283-287` bloco morto com `stmt_u` não usado) | Limpeza pontual |
| Documentação: poucos arquivos, fonte única, decisões com contexto, nada morto | **Não atende** | 28 arquivos `.md` (1.981 linhas fora este mapa), três descrições de arquitetura, dois manuais, `STATUS_PENDENCIAS` × `ROADMAP`, 13 `DEC-` citados e só 7 documentados, várias afirmações falsas (mapa §10) | Ver proposta na seção 5 |
| Git: 1 mudança lógica por commit, commits semânticos, branches | **Não atende** | Só `main`; commits gigantes de múltiplos assuntos (`44d5d0a`, `67a27b3`, `61214be`); mensagens semânticas, mas mistas PT/EN; sem PRs | Branch por fase, 1 PR, commits pequenos; proteger `main` |
| Qualidade: arquitetura → funcionalidade → testes | **Não atende** | Funcionalidade declarada "concluída" que não executa (notificações, instalação limpa, restore); testes passam sobre premissas (SQLite, mock) | Validar fluxo em Postgres antes de declarar pronto |
| Frontend (ver 4.1) | **Parcial** | Angular 22 + Material, zoneless, 129 arquivos | Ver abaixo |

### 4.1 Angular se justifica?

Honestamente, **hoje não por necessidade técnica, e a troca não compensa agora**.

- O produto é um sistema administrativo com formulários, listas e painéis. O que Angular dá de diferencial (SPA com estado rico, tempo real intenso, offline) quase não é usado: a única parte realmente "viva" é o sino de notificações (que nem recebe eventos) e o chat do chamado. Isso é exatamente o perfil de **SSR + HTMX/Alpine** (sua preferência, `Django Templates + HTMX`), com menos código, menos dependências e menos superfície de XSS.
- Custo real de manter para um desenvolvedor solo: o README diz Angular 18 e o `package.json` está em **22** (major a cada ~6 meses, com `ng update` obrigatório), TypeScript 6, Vite 8 e Vitest 5; segurança do token em `localStorage`; dois ambientes de build (Node + Python); CI com Chrome headless; regras de autorização duplicadas (guards no front, deveres no backend, e a regra do termo no front). Material traz bastante CSS/JS por tela.
- Por que **não** reescrever agora: 129 arquivos funcionais, 32 testes unitários, as telas existem e o backend FastAPI devolve JSON (um SSR exigiria novo backend de views). Reescrever consumiria semanas e não corrige nenhum dos P0/P1.
- Recomendação: **congelar a versão do Angular** (parar o ritmo de upgrades), construir o frontend dentro do Compose (build multi-stage) e **não adicionar telas novas pesadas** em Angular. O painel de notificações da Fase 3 pode ser a primeira tela feita em HTMX/Jinja (rotas `/ui/...` no próprio FastAPI) como experimento de baixo custo, e só então decidir migrar o resto por módulo (decisão a validar com você, ADR próprio).

---

## 5. Consolidação documental proposta

Fonte única da verdade, 4 arquivos vivos + decisões:

| Manter | Substitui |
|---|---|
| `docs/PROJECT_MAP.md` (estado técnico) | `docs/system-overview.md`, `docs/architecture/overview.md`, `docs/01-arquitetura-do-sistema.md`, `docs/modules/*.md` |
| `docs/AUDIT.md` (dívida e riscos) | `STATUS_PENDENCIAS.md`, parte de `ROADMAP.md` |
| `README.md` enxuto (instalar, atualizar, backup, link para o mapa) | `docs/02`, `08`, `10`, `05` |
| `docs/decisions/` (ADR numerados, só os que existirem de fato) | `ADR-001…005`, `DEC-006`, `DEC-012` + novas |
| `docs/manual-do-usuario.md` (um só) | `docs/user-guide.md`, `docs/06-manual-de-utilizacao.md` |

Remover: `ROADMAP.md` (log de datas vira `git log`), `docs/03, 04, 07, 09` (fundir o que for verdadeiro no README e no manual). Isso vai ocorrer em PR próprio, depois da sua aprovação.

---

## 6. Ordem de execução recomendada (P0/P1)

1. **P0-1** merge das cabeças Alembic + teste de `upgrade head` no CI. *(B; destrava tudo)*
2. **P0-3** recusar `SECRET_KEY` padrão; sem default no compose. *(B)*
3. **P1-17 + P1-12** retirar portas do Postgres/API do host; remover bind mount; volumes para dados. *(B)*
4. **P0-2 + P1-3** anexos: enum de tipos, caminho seguro, autorização por entidade, limites; usuário não-root. *(B–M)*
5. **P0-5 + P1-5 + P1-6** webhook autenticado e sem eco; permissões nas rotas WhatsApp; categorias com auth; teste de contrato de rotas sem auth. *(M)*
6. **P1-4** escapar HTML do termo. *(B)*
7. **P0-4 + P1-13** restore fora da API (procedimento seguro) + backup de anexos/logo + agendamento com alerta. *(M)*
8. **P1-2** lock no estoque. *(B)*
9. **P1-1** auditoria em um só caminho. *(B)*
10. **P1-8 + P1-9 + P1-10 + P1-11** revogação/validação de usuário, rate limit, permissões fantasmas, seed não-destrutivo, setup com nome da empresa. *(M)*
11. **P1-7, P1-14, P1-15, P1-16** MOCK explícito, fila com worker, escopo do ciclo de ativos, FK do autor no WhatsApp. *(parte vira a Fase 3)*
12. P2 em lotes; consolidação documental (seção 5).

---

## 7. Como reproduzir (resumo)

```
git archive a544af7 | tar -x -C /tmp/gtiaudit && cd /tmp/gtiaudit
cp -r <frontend/dist já construído> frontend/dist     # o Compose não constrói o frontend
echo SECRET_KEY=CHANGE-ME-IN-PRODUCTION > .env
docker compose -p gtiaudit up -d --build               # backend entra em loop: "Multiple head revisions"
```
Os roteiros de API usados (login por perfil, anexos, estoque concorrente, webhook, backup/restore) ficaram no scratchpad da sessão e podem ser convertidos nos testes da seção 3.2 quando você aprovar as correções.

---

## Nota — Fases B e C

- **P0-5 / vínculo por matrícula (WhatsApp):** o novo fluxo seguro existe para o Telegram (código de uso único). O WhatsApp só ganha o mesmo vínculo na Fase D.
- **WebSocket com JWT na URL:** corrigido (ticket de 60 s).
- **Erro de validação com `field_validator` customizado devolvia 500:** corrigido no handler global.
- **Não validado numa stack Docker real nas Fases B e C** (Docker Desktop indisponível na máquina de desenvolvimento): cobertura por testes automatizados (backend com `httpx.MockTransport` para a Bot API) e CI; falta exercitar um bot real e o WebSocket via Nginx.

## Nota — Fase D

- **P0-5 (webhook do WhatsApp) / P1-14 (fila WhatsApp sem worker) / P1-16:** **resolvidos de vez** — o bot, a fila e o webhook antigos foram removidos; o canal agora é a Meta Cloud API no hub, com assinatura HMAC, vínculo por código, fila com retentativa e painel.
- Código morto removido: `whatsapp/{adapter,conversation_service,queue_service,notification_dispatcher}.py`, serviço `evolution-api` do Compose, ~600 linhas de UI de "anti-ban/outbox" no painel administrativo.
- **Não validado contra a Meta real** nem em stack Docker (Docker Desktop indisponível); coberto por testes com a Graph API simulada.
