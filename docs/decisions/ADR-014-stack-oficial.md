# ADR-014 — Stack oficial da plataforma

**Status:** Aceito (proposto em 2026-10-21; itens marcados "a confirmar" dependem de decisão do responsável)  
**Data:** 2026-10-21  

## Contexto

O projeto foi construído com apoio de IA e acumulou documentação divergente do código (versões de Angular, integrações removidas, comandos inexistentes). A auditoria de 2026-10-21 levantou o que está **de fato** em uso, a partir de `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `package-lock.json`, `Dockerfile`s e `docker-compose*.yml`.

## Decisão

**Consolidar a stack existente. Nenhuma tecnologia nova entra por preferência ou tendência.** Mudanças futuras exigem ADR própria.

| Camada | Oficial | Versões de referência (lock) | Observação |
|---|---|---|---|
| Linguagem backend | Python **3.12** | imagem `python:3.12-slim` | fixar também em dev e CI (`.python-version`); hoje o desenvolvimento local roda 3.14 |
| API | FastAPI, Starlette, pydantic v2, pydantic-settings | 0.142 / 1.7 / 2.13 / 2.15 | |
| Dados | SQLAlchemy 2 async, asyncpg, Alembic | 2.1 / 0.31 / 1.20 | migrations versionadas; cabeça única |
| Banco | PostgreSQL **16** | `postgres:16-alpine` | SQLite apenas em testes unitários |
| Autenticação | JWT HS256 (`python-jose`) + bcrypt | 3.5 / 5.0 | evolução em ADR-016 (versão de sessão); troca por `PyJWT` a avaliar |
| Segredos | Fernet (`cryptography`) via `APP_ENCRYPTION_KEY` | 50.0 | credenciais de integrações cifradas no banco |
| Tarefas assíncronas | outbox `domain_events` + worker próprio (`python -m app.worker`) | — | **sem** Celery/Redis; ver ADR-013 |
| Frontend | Angular 22 (standalone) + Angular Material, RxJS 7, TypeScript 6 | 22.2.1 | `strictTemplates` e ESLint adotados de forma gradual |
| Testes | pytest (+ pytest-asyncio), Vitest | — | SQLite em memória por padrão; suíte `pg`/`migrations` contra PostgreSQL |
| Servidor web | Nginx 1.27 (serve o build do Angular e faz proxy de `/api`) | `nginx:1.27-alpine` | HTTPS opcional (`docker-compose.https.yml`) |
| Empacotamento | Docker + Docker Compose v2, `uv` | — | imagens com **tag fixa**; hoje `ghcr.io/astral-sh/uv:latest` precisa ser fixada |

### Componentes e responsabilidades

- **backend (API):** regras de negócio, autorização por permissão, auditoria.
- **worker:** despacho do outbox de notificações, jobs agendados (alertas de estoque/garantia, backup diário).
- **postgres:** única fonte de verdade; anexos e logo ficam em volumes (não no banco, ADR-003).
- **nginx:** entrega do SPA, proxy da API e do WebSocket, cabeçalhos de segurança.

### Dependências transitórias ou a substituir

- `python-jose` (pouco mantido; arrasta `ecdsa`): avaliar `PyJWT` — baixo risco, só HS256 é usado.
- Google Fonts / Material Symbols por CDN: servir localmente (ambientes sem internet).
- Dependências de desenvolvimento duplicadas em `pyproject.toml` (`optional-dependencies` e `dependency-groups`): consolidar em uma só.

## Exceção ao padrão global do autor

O padrão pessoal do autor (`CLAUDE.md` global) prefere Django + HTMX/Alpine e “sem SPAs salvo necessidade comprovada”. Este produto é FastAPI + Angular, em repositório próprio, e **não faz parte do ecossistema Hedú** (`ECOSYSTEM.md`). A decisão é **manter** a stack atual: reescrever custaria mais que o benefício e o sistema já está funcional. O custo de manter duas stacks (já apontado em `docs/AUDIT.md`) fica registrado aqui.

**A confirmar pelo responsável:** titular da licença (`LICENSE.md` cita `Pintanatalense`; a marca é HeduInfo/InfraNuvem) e identidade de autor do Git (hoje três variações).

## Consequências

- Documentação e `README` passam a citar estas versões; documentos divergentes são corrigidos ou arquivados.
- O CI deve refletir a stack (lint, tipos, testes em PostgreSQL, build das imagens).
- Atualizações de dependências entram por PR (dependabot), com testes.
