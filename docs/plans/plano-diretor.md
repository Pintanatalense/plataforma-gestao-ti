# Plano Diretor — Profissionalização e Evolução da Plataforma de Gestão de TI

> **Histórico.** Fases 1–4 concluídas (#11–#63); substituído pelo [Plano de Evolução](plano-evolucao.md) em 2026-10-25.
> **Status original:** plano aprovado em 2026-10-21. Execução em PRs independentes, um por vez; nenhum merge, migration em ambiente real ou mudança de arquitetura sem autorização do responsável. Requisitos de origem: [diretriz-engenharia.md](diretriz-engenharia.md).
> Base: 3 auditorias de leitura (backend/infra, frontend, governança) + verificação direta dos achados mais graves (marcados ✔ = confirmado por mim lendo o código; os demais vêm dos relatórios e serão reconfirmados com teste antes de cada correção).

## Context

O sistema (FastAPI + SQLAlchemy async + Alembic + PG16 · Angular 22 · Nginx · Docker Compose) funciona nos fluxos testados (backend 377 testes, frontend 110, CI verde), mas foi gerado por IA com documentação não confiável e sem governança de engenharia. Você pediu uma etapa estruturada de estabilização, qualidade funcional e duas capacidades novas (SLA e recuperação de senha por e-mail), com decisões fundamentadas e entregas verificáveis.

**PR #11** (`fix/review-glpi-import-e-estoque-categorias`): aberto, `MERGEABLE`, checks `backend-tests` e `frontend-tests` **verdes**, sem revisão. Já cobre: endurecimento da importação GLPI (série duplicada, JSON inválido, nomes repetidos), índice único de `serial_number` no model, rota/menu de categorias de estoque, Etapa 4b do roteiro. **Este plano não duplica nada disso.** Recomendo integrá-lo primeiro (precisa da sua autorização).

---

## A. Diagnóstico técnico

**Stack real:** Python 3.12 (imagem; dev local roda 3.14) · FastAPI 0.142 · SQLAlchemy 2.1 · pydantic 2.13 · Alembic 1.20 · asyncpg · python-jose (HS256) + bcrypt · Angular 22.2 / TS 6 / Vitest · Postgres 16 · Nginx 1.27 · uv + `uv.lock`. 21 migrations, cabeça única.

### Defeitos confirmados (por prioridade)

| # | Severidade | Defeito | Evidência |
|---|---|---|---|
| 1 | **Crítica** | `POST /system/demo/seed-test` cria `admin@teste.local` (superadmin) com senha fixa `Teste@2026`, sem trava de ambiente, exigindo só `system.backup.manage`. Sem nenhum teste de `/system/demo` ✔ | `core/demo_router.py:87-103`, `seed_test.py:42,294` |
| 2 | **Alta** | Escalada de privilégio: `create_user`/`update_user` aceitam `is_admin` e `role_ids` com só `identity.users.create/update`; sem proteção do último admin ✔ | `identity/services.py:202-231` |
| 3 | **Alta** | Sessões sobrevivem à troca/reset de senha e à desativação até 8 h (JWT sem `jti`/versão); teste fixa esse comportamento; troca não zera lockout | `identity/services.py:247-263`, `tests/identity/test_auth_hardening.py:77-91` |
| 4 | **Alta** | `POST /notifications/email/test` usa a senha SMTP armazenada com `host` informado pelo chamador → exfiltração das credenciais por quem tem `system.backup.manage` ✔; alteração de SMTP não gera auditoria | `email_service.py:143-155`, `email_router.py:54-57` |
| 5 | **Alta** | Testes `pg`/`migrations` **nunca rodam no CI** (`TEST_DATABASE_URL` não definido ✔); CI não roda ruff, mypy, `alembic check`, build Docker nem auditoria de dependências | `ci.yml:46-50` |
| 6 | **Média** | Falha de carga vira "lista vazia"/"tudo certo" (Dashboard, listas de chamados/ativos/estoque/inventário, backups, anexos); telas de detalhe ficam em branco; Admin/SMTP mantém padrões fixos com Salvar habilitado | relatório frontend §2 |
| 7 | **Média** | Frontend lê `err.error.detail` (60 usos) mas o backend só envia `error.message` → mensagens reais do servidor nunca aparecem | `core/exceptions.py:134-195` |
| 8 | **Média** | Logo nunca é gravada: `update_company` ignora `logo_url` ✔ | `organization/services.py:51-58` |
| 9 | **Média** | Drift models × migrations (6 itens; migration certa em 4, model certo em 2); `alembic check` nunca roda | relatório backend §8 |
| 10 | **Média** | Coluna "Integridade SHA-256" sempre "N/A" (`sha256_hash` × `checksum_sha256`) | `admin.service.ts:56` |
| 11 | **Média** | Backup: anexos/logo fora do dump, sem off-site, sem teste de restauração, `make backup` incompatível com `make restore`, restore não para o worker, `ATTACHMENT_MAX_SIZE_MB` não chega ao container | `Makefile`, `restore-backup.sh`, `docker-compose.yml:48-56` |
| 12 | **Média** | Docs enganosas: Evolution API/Angular 17-18/endpoints de backup inexistentes/`container_name` inexistente/eventos de auditoria inexistentes (`user.login`, `backup.*`, `ip_address`) | `docs/01,05,09,10`, `Oque_tem_gestao_ti.md` |
| 13 | **Baixa** | Reset de senha na UI usa senha fixa `temporaria-123`; ações destrutivas sem `error` handler; upload de anexo falha mas anuncia sucesso | `user-list.component.ts:77`, `ticket-create.component.ts:199` |
| 14 | **Baixa** | Governança: sem proteção de `main`, CODEOWNERS, dependabot, templates, SECURITY/CONTRIBUTING, tags; 10 branches mescladas abertas; 3 identidades de autor; `ghcr.io/astral-sh/uv:latest` | relatório governança §4 |
| 15 | **Baixa** | Frontend: sem `strict`/ESLint; interceptor só trata 401; Google Fonts por CDN; `index.html` sem `no-cache`; SPA sem CSP/HSTS | relatório frontend §1 |

### A confirmar durante a execução (hipóteses)
Vínculo de ativo a chamado sem checar escopo do setor · solicitante edita `asset_ids`/`custom_fields` · permissões presas ao JWT (até 8 h) · esgotamento de conexões (4×30 vs `max_connections`=100) · `/docs` e `/health` públicos · `X-Forwarded-For` forjável · módulo residual `backend/app/whatsapp/` · `/tests` da raiz fora do CI · duplicação de `dev` deps no `pyproject.toml`.

### Funcionalidades ausentes (contratos já existentes no backend)
| Capacidade | Backend | Lacuna |
|---|---|---|
| Perfil institucional/logo | `GET/POST/PATCH /organization/company`, `POST /company/logo`, `GET /company/public` | tela inexistente; logo não persiste (#8); login mostra "Gestão de TI" fixo |
| Auditoria | `GET /audit`, `/audit/{tipo}/{id}` (`audit.read`) | tela inexistente; schema sem nome/e-mail do usuário, sem total/filtros/teto de `limit`; **não audita** login, usuários/perfis, senhas, empresa, backup, SMTP |
| Relatório de chamados | `GET /tickets/reports/summary` (dict sem schema, carrega tudo) | tela inexistente; sem período; sem métrica de tempo/SLA |
| Verificar backup | `GET /system/backups/{id}/verify` | sem botão; lê arquivo inteiro na RAM |

---

## B. Stack oficial (a registrar em ADR-014)

**Consolidar, não trocar.** Nenhuma tecnologia nova só por tendência.

| Camada | Oficial | Observação |
|---|---|---|
| Backend | Python **3.12** (fixar também em dev/CI via `.python-version`), FastAPI, SQLAlchemy 2 async, Alembic, pydantic-settings, `uv` | alinhar dev (3.14) ao container |
| Banco | PostgreSQL 16 | SQLite só em testes unitários |
| Frontend | Angular 22 standalone + Material, Vitest | adotar `strictTemplates` gradualmente; ESLint + Prettier no CI |
| Auth | JWT HS256 + bcrypt, **com versão de sessão** (ver P2-3) | `python-jose` pouco mantido: avaliar troca por `PyJWT` (ADR-016, baixo risco) |
| Infra | Docker Compose, Nginx, imagens com **tag fixa** (uv incluído) | digest opcional |
| Filas/tarefas | outbox `domain_events` + worker próprio (já existente) | **sem** Celery/Redis; SLA e reset reaproveitam |

**Exceção a registrar:** o `CLAUDE.md` global prefere Django + HTMX/Alpine; este projeto é FastAPI + Angular, em repositório próprio (`Pintanatalense`), fora de `ECOSYSTEM.md`. ADR-014 documenta a exceção, o custo (já reconhecido em `AUDIT.md` §4.1) e a decisão de manter. Também decidir titular da licença (`Pintanatalense` × HeduInfo/InfraNuvem) e identidade de autor do Git.

**ADRs novos:** 014 stack oficial · 015 importação GLPI (converter `docs/plans/importacao-inventario-glpi.md`) · 016 sessão e revogação · 017 SLA · 018 recuperação de senha. Corrigir status do ADR-013 (fases A–G concluídas) e DEC-012 (sem status/data).

---

## C. Roadmap priorizado

Esforço: **S** ≤ ½ dia · **M** 1–2 dias · **L** 3–5 dias. Cada PR: branch `fix|feat|docs|ci|chore/...`, commits semânticos, testes + evidência na descrição, rollback = revert.

### Fase 1 — Diagnóstico e governança (só docs/config, risco baixo)
| PR | Escopo | Esf. | Aceite |
|---|---|---|---|
| **#11** | Integrar o PR existente | — | **precisa da sua autorização**; CI verde ✔ |
| P1-1 `docs: plano diretor + ADRs 014/015` | commitar `.gitignore` (regra do `INVENTARIO_MODELO.xml`) e `docs/plans/` **saneado** (links `file:///` → relativos; cabeçalho "modo planejamento" → vira este plano; GLPI → ADR-015); ignorar `*.sql.gz`, `pre-restore-*`, `*.pem` | S | nenhum arquivo sensível rastreado (`git ls-files`); links válidos |
| P1-2 `docs: corrigir documentação enganosa` | `01,05,09,10`: remover Evolution, Angular 22, endpoints/containers reais; banner "histórico" em `AUDIT.md`/`PROJECT_MAP.md`; mover `Oque_tem_gestao_ti.md`, `STATUS_PENDENCIAS.md`, `ROADMAP.md` para `docs/archive/` **(apagar? decisão sua)**; ADR-013 status | M | cada afirmação chave conferida contra o código (tabela no PR) |
| P1-3 `chore: .github` | `CODEOWNERS`, template de PR/issue, `dependabot.yml` (pip, npm, docker, actions), `SECURITY.md`, `CONTRIBUTING.md` (branches/commits/revisão) | S | arquivos válidos; dependabot abre PRs |
| P1-4 `chore(spec): .spec/` | `spec-init` conforme metodologia global; fases deste plano viram specs `001…006` | S | estrutura criada; decisão sua se adotar já |
| *Config GitHub (você)* | proteção da `main` (PR + checks obrigatórios), `delete_branch_on_merge`, limpar 10 branches mescladas | — | não consigo aplicar sem sua ação/plano do repo |

### Fase 2 — Estabilização (segurança → integridade → infra)
| PR | Escopo | Esf. | Aceite / testes |
|---|---|---|---|
| P2-1 `fix(security): superfícies perigosas` | `seed-test`: desabilitar por padrão (só com `ENABLE_QA_SEED=true`) ou remover; SMTP `test`: nunca reutilizar senha guardada se `host/porta/usuário` mudarem; auditar alteração/teste de SMTP; `docs/openapi` desligáveis por env | M | testes de negação por permissão e por ambiente; `/system/demo` ganha testes |
| P2-2 `fix(identity): escalada de privilégio` | só admin concede/retira `is_admin`; atribuir perfil não pode conceder permissão que o próprio ator não tem; proteger último admin (desativar/excluir/rebaixar) | M | testes: ator sem privilégio → 403; último admin → 409 |
| P2-3 `feat(auth): revogação de sessões` (ADR-016) | `user_accounts.token_version` (migration), claim `tv` no JWT, comparação em `get_token_payload` (já consulta o banco por requisição → custo zero); incrementa em troca/reset/desativação; troca zera lockout; nginx `limit_req` em `/identity/login`; inverter o teste que fixa o comportamento antigo | M | token antigo → 401 após troca; migration testada com dados; sem regressão |
| P2-4 `fix(db): drift models × migrations` | models: `index=True` (`is_demo`, `ticket_id`), `ondelete` em `db_backups`; importar `SystemSetting` no `env.py`; 1 migration (`ix_stk_categories_is_active`, remover unicidade duplicada de `wa_templates.code` **após conferir dados**); `alembic check` limpo | M | upgrade/downgrade/upgrade em PG com dados; `alembic check` sem diferenças |
| P2-5 `ci: pg-tests + alembic check` | job com `TEST_DATABASE_URL` (banco `*_test`), `alembic check`, build das imagens, `pip-audit`/`npm audit` (informativo), `permissions: contents: read`, actions fixadas | M | testes `pg`/`migrations` passam no CI |
| P2-6 `ci: ruff gate` | corrigir violações de ruff e ligar como bloqueante; `mypy` em modo baseline (sem `strict` global de imediato) | M | ruff verde; mypy não regride |
| P2-7 `fix(infra): backup/restore/compose` | repassar `ATTACHMENT_MAX_SIZE_MB`; restore para o worker; `make backup` gzip + volumes (anexos/logo) compatível com `make restore`; fixar `uv` e imagens; reescrever `docs/05`; script de teste de restauração em banco descartável | M | restauração ponta a ponta demonstrada em ambiente limpo |
| P2-8 `fix(org): persistir logo` | `update_company` grava `logo_url`; teste de persistência | S | `/company/public` devolve a URL |
| P2-9 `chore: limpeza` | `/tests` da raiz → mover/remover; módulo `whatsapp/` residual (após conferir); dev-deps duplicadas; `__init__.py` faltantes | S | CI verde |

### Fase 3 — Qualidade funcional
| PR | Escopo | Esf. | Aceite |
|---|---|---|---|
| P3-1 `feat(frontend): base de estados` | componente `<app-load-state>` (carregando / erro + "Tentar novamente" / vazio, projeção de conteúdo) e helper único `apiErrorMessage()` (extraído de `rules.component.ts:26`: `error.message`, 422 `details`, rede, 403, 429); interceptor global p/ 5xx/0/429 e 401 com "sessão expirada" + `returnUrl`; piloto no Dashboard | M | specs do componente e do interceptor (hoje só `should create`) |
| P3-2 | aplicar em **Dashboard + listas** (chamados, ativos, estoque, inventário) e detalhes (chamado, estoque, inventário) | M | teste por página: falha de API ≠ lista vazia |
| P3-3 | aplicar em **Organização/Identidade** (troca `detail`→helper; estados vazios; `error` em reset/exclusão; fim da senha fixa) | M | idem |
| P3-4 | **Admin** (SMTP não pode salvar sem carregar a config real; backups; `checksum_sha256`; botão Verificar), **anexos**, **ticket-create** (falha de anexo) , login (429/lockout) | M | idem |
| P3-5 `feat: perfil institucional` | tela empresa/logo + logo/nome no login (`/company/public`) | M | depende de P2-8 |
| P3-6 `feat: auditoria` | backend: expor usuário, total, filtros, teto de `limit`; auditar login/logout/falha, usuários/perfis/permissões, senhas, empresa, backup, SMTP; tela com filtros | L | eventos de `docs/09` passam a existir de fato; doc corrigida |
| P3-7 `chore(frontend): qualidade` | ESLint + Prettier no CI; `strictTemplates` primeiro, `strict` depois, por etapas; `index.html` `no-cache`; fontes/ícones locais (ambiente sem internet) | M | CI bloqueante sem regressão de build |
| P3-8 `docs: inventário de páginas` | `docs/` com critérios objetivos por página (rota/permissão, contrato validado, carregando/erro/vazio/retry, spec de comportamento, roteiro, pendências) **com evidência** — substitui o % informal | S | cada linha aponta teste/commit |
| *Relatório de chamados* | **adiado para a Fase 4** (SLA): a tela nasce já com indicadores de SLA, evitando retrabalho | — | — |

### Fase 4 — Novas capacidades
Ordem sugerida: **recuperação de senha antes do SLA** (menor, reaproveita P2-3, nasce desligada); SLA em seguida. Ajustável se preferir o inverso — não há dependência entre eles.

**Recuperação de senha:** P4-R1 backend (tabela, endpoints, e-mail, auditoria, gating) · P4-R2 administração (ativar/“homologado” no cartão SMTP) · P4-R3 telas (`Esqueci minha senha`, `Redefinir`).
**SLA:** P4-S1 ADR-017 + modelo + calculadora pura · P4-S2 integração com chamados · P4-S3 job + alertas + violações · P4-S4 admin (políticas/calendários/categoria) · P4-S5 indicadores nas telas + relatório de chamados.

### Fase 5 — Consolidação
Logging estruturado + request id + nível por env (hoje o backend não configura logging) · `/health` detalhado só autenticado · headers Nginx (HSTS sob HTTPS, CSP do SPA, `no-cache` do `index.html`, `server_tokens off`) · `max_connections`/pool coerentes · DR documentado (RPO/RTO, off-site, **guardar `APP_ENCRYPTION_KEY`**) · `CHANGELOG` + tags/releases (`v0.x`) + notas de upgrade · homologação (roteiro completo em ambiente limpo e em base antiga populada) · decidir `PyJWT` e demais dependências.

---

## D. Proposta de SLA (ADR-017) — aprovação antes de implementar

**Definições (sem ambiguidade):**
- **Primeira resposta:** primeira interação *pública* de alguém que não é o solicitante, com o chamado sob responsabilidade da TI (nota interna e mensagens automáticas **não** contam).
- **Atendimento:** mudança para `IN_PROGRESS`. Só informativo na v1 (sem relógio próprio).
- **Resolução:** passagem para `RESOLVED` (ou `CLOSED`, se nunca houve `RESOLVED`).

**Ausência de SLA:** `ticket_categories.sla_policy_id` **NULL = "Não se aplica" (padrão)**. Chamado dessa categoria não tem ciclo de SLA; a API devolve `sla.state = NOT_APPLICABLE`; nunca é "atrasado" e fica fora dos indicadores.

**Modelo de dados (migration única, aditiva):**
- `sla_calendars` (nome, `timezone` IANA, horário semanal por dia) · `sla_holidays` (calendário, data, nome).
- `sla_policies` (nome, descrição, `is_active`, calendário, status que pausam [padrão `PENDING`], regra de reabertura `RESTART|CONTINUE`, % de alerta [padrão 80]).
- `sla_policy_targets` (política, `priority` nullable = padrão, minutos de 1ª resposta, minutos de resolução). *Prioridade entra aqui porque o impacto de “Crítica” varia dentro da mesma categoria; custo de esquema pequeno.*
- `ticket_categories.sla_policy_id` (FK nullable).
- `ticket_sla_cycles` — **um registro por ciclo** do chamado: `ticket_id`, `cycle`, `policy_id`, **cópia (snapshot) dos alvos e do calendário**, `started_at`, `first_response_due_at`, `resolution_due_at` (UTC `timestamptz`), `first_response_at`, `resolved_at`, `paused_at`, `remaining_*_minutes`, `state` (`RUNNING|PAUSED|MET|BREACHED`). Único `(ticket_id, cycle)`.
- `sla_breaches` (histórico: ciclo, tipo `FIRST_RESPONSE|RESOLUTION`, `due_at`, `detected_at`) com único `(ciclo, tipo)`.

**Regras:**
- **Início:** criação do chamado (ou mudança para categoria com política, ver abaixo). **Fim:** primeira resposta / resolução.
- **Pausa:** status em `pause_statuses` (padrão `PENDING`, aguardando o solicitante). Ao pausar guarda minutos úteis restantes; ao retomar recalcula `due_at = somar_minutos_úteis(agora, restante)`.
- **Reabertura** (`RESOLVED/CLOSED → aberto`): `RESTART` abre novo ciclo só de resolução (a primeira resposta não se reaplica); `CLOSED` segue imutável como hoje. `TICKET_REOPEN_DAYS` (config morta) passa a limitar reabertura.
- **Política editada:** vale **só para chamados novos** (snapshot preserva os prazos já aplicados). **Categoria do chamado alterada:** novo ciclo explícito, auditado, mantendo `started_at` original *(a confirmar por você)*.
- **Tempo:** tudo em UTC; cálculo em minutos úteis com `zoneinfo` do calendário; função pura `add_business_minutes(inicio, minutos, calendario)` e `business_minutes_between(...)`.
- **Concorrência:** transição de status e atualização do ciclo na **mesma transação**, com `SELECT … FOR UPDATE` no ciclo; violação idempotente por `UNIQUE` + `INSERT … ON CONFLICT DO NOTHING`.

**Processamento:** **sem fila nova.** Prazos são calculados na transição (síncrono, no serviço de chamados). Um job `sla.check` (`every:5`) no worker existente marca violações e dispara alertas de proximidade; reaproveita `scheduled_jobs`, `automation_marks` e o hub de notificações (regras para responsável/gestão). Demonstrado que não precisa de microsserviço/Redis.

**Administração:** telas *Políticas SLA* (CRUD, ativar/desativar, alvos por prioridade) e *Calendários* (horário + feriados); campo “SLA” no formulário de categoria (padrão **Não se aplica**); permissão nova `service_desk.sla.manage`.

**Indicadores (futuro dashboard/relatório):** cumprimento = `MET/(MET+BREACHED)` por período/categoria/prioridade; tempo médio de 1ª resposta e de resolução em minutos úteis; backlog em risco. Tudo derivável das tabelas acima (fatos persistidos, sem recálculo a posteriori).

**Testes:** limites de horário (fim do expediente, fim de semana, feriado), pausa/retomada, vencimento exato no limite, reabertura, troca de política/categoria, ausência de política, corrida de dois eventos simultâneos, fuso/UTC.

---

## E. Proposta de recuperação de senha (ADR-018) — nasce **desabilitada**

**Gating:** configuração `password_reset.enabled=false` (tabela `system_settings`). Só pode ser ligada por administrador quando o SMTP está habilitado **e** o último teste de envio passou (“homologado”). Desligado, os endpoints respondem 404 e a UI não exibe o link (`GET /identity/password-reset/status`).

**Fluxo:**
1. `POST /identity/password-reset/request {email}` → sempre `202` com mensagem idêntica (existindo ou não), tempo de resposta equalizado; envio em background.
2. Token: 32 bytes aleatórios (`secrets.token_urlsafe`), **só o hash SHA-256 é guardado** (`password_reset_tokens`: usuário, hash, `expires_at` = 30 min, `used_at`, IP). Novo pedido invalida os anteriores. Link `…/reset-password?token=…` (página remove o token do histórico e envia `Referrer-Policy: no-referrer`).
3. `POST /identity/password-reset/confirm {token, new_password}` → valida hash/validade/uso único, aplica a política de senha, grava, marca usado, zera lockout e `must_change_password`, **incrementa `token_version`** (encerra todas as sessões — PR P2-3), audita.
4. **Abuso:** limites por e-mail (3/h) e por IP (10/h) contados na tabela de tokens/auditoria; resposta continua 202.
5. **SMTP fora do ar:** pedido retorna 202; falha registrada em auditoria (`password_reset.send_failed`), sem retentativa em rajada; token expira naturalmente.
6. **Segurança:** TLS/STARTTLS com validação de certificado (hoje o `send_smtp_raw` aceita “nenhuma segurança” — para reset exigir TLS); credenciais continuam Fernet; **tokens/senhas nunca em log nem em auditoria** (mascaramento no logger).
7. **E-mail:** reutiliza `send_smtp_raw` via `asyncio.to_thread` e `app_base_url`; template transacional próprio (o `enqueue_direct_message` atual grava `title=""`, não serve).

**Alternativa descartada:** passar pelo outbox do hub (retentativas, mas guarda o link no banco por mais tempo e exige adaptar o canal). Reavaliar se o SMTP corporativo for instável.

**Testes (SMTP simulado, sem servidor real):** token expirado/reusado/forjado, enumeração (corpo e tempo), limites, desabilitado→404, sessões revogadas, SMTP indisponível, vazamento zero em logs, política de senha.

---

## F. Governança do repositório

- **Branches/commits/PR:** `tipo/escopo-curto`; Conventional Commits em português; PR pequeno e coeso (não misturar refatoração + migration + feature); template de PR com testes executados, riscos, rollback.
- **Revisão:** `CODEOWNERS`; `main` protegida (PR obrigatório + `backend-tests`, `frontend-tests`, novos jobs); deletar branch ao mesclar.
- **CI alvo:** ruff · mypy (baseline) · pytest (SQLite + PG) · `alembic upgrade` + `alembic check` · ng lint/test/build · build Docker · auditoria de dependências (informativa) · dependabot.
- **Migrations:** uma por PR, aditivas quando possível, testadas com dados (upgrade→downgrade→upgrade) e com `alembic check`.
- **Docs:** fonte única; ADR por decisão; `docs/` corrigidos; inventário de páginas com evidência; `.spec/` conforme sua metodologia.
- **Dependências:** `uv.lock`/`package-lock.json` obrigatórios; imagens e actions com versão fixa; `.env.example` sem segredo.
- **Estrutura do backend:** manter por domínio (alinhada ao padrão); divergências conhecidas (`core/` com demo/starter_catalog, `services.py` vs `service.py`, `repository.py` no papel de `selectors`) registradas em ADR em vez de refatoração em massa.

---

## G. Plano de execução

1. Você aprova este plano e as **decisões abaixo**.
2. Você autoriza o merge do **PR #11**.
3. Fase 1 → 2 → 3 → 4 → 5, **um PR por vez**, cada um com: resumo, testes executados e resultado, limitações, riscos residuais, próximos passos.
4. Itens de planejamento formal (SLA, reset) têm ADR aprovado **antes** do primeiro commit de código.
5. Nenhum merge, migration em ambiente real ou mudança de arquitetura sem sua autorização.

### Decisões que dependem de confirmação do responsável (item a item)
1. Merge do PR #11.
2. Manter FastAPI + Angular como stack oficial (exceção ao Django/HTMX do `CLAUDE.md`) e titular da licença/identidade de autor.
3. `seed-test`: **desabilitar por padrão** (quebra o fluxo de QA atual) ou remover.
4. Revogação de sessões via `token_version` (recomendado) e, opcionalmente, ler permissões do banco a cada requisição para acabar com o atraso de até 8 h.
5. Docs obsoletas: arquivar em `docs/archive/` (recomendado) ou apagar.
6. Adotar `.spec/` já (P1-4).
7. SLA: alvos por prioridade; pausa só em `PENDING`; reabertura `RESTART`; regra ao trocar categoria; calendário padrão (horário comercial) — valores de prazo ficam **configuráveis e vazios** (você define depois).
8. Reset de senha: validade 30 min, limites 3/h e 10/h, “homologado” como pré-condição, reset antes do SLA.
9. Config do GitHub (proteção de `main` etc.) — feita por você.

## Riscos do plano
Migrations em base populada (mitigação: teste upgrade/downgrade com dados em cada PR) · mudança de sessão desloga todos uma vez (avisar) · ligar `ruff`/`strict` gera volume de ajuste (faseado) · SLA é a maior fonte de bordas (por isso ADR + calculadora pura antes da integração) · nenhuma integração real (Telegram/Meta/Slack/FCM, SMTP corporativo) validada ainda.

## Verificação (como cada entrega será provada)
- Backend: `uv run pytest` (SQLite) + suíte `pg`/`migrations` contra Postgres 16 descartável; `alembic upgrade head`, `downgrade -1`, `upgrade head` em base com dados; `alembic check`.
- Frontend: `ng test --watch=false` e `ng build`; spec por página cobrindo falha de API ≠ vazio.
- Segurança: testes de negação (permissão/ambiente), token antigo→401, enumeração de contas, ausência de segredo em logs.
- Infra: `docker build` das imagens; restauração ponta a ponta em ambiente limpo; roteiro `docs/12` executado.
- CI verde (todos os jobs) antes de qualquer pedido de merge.
