# Como contribuir

Documentação em português; código (variáveis, funções, tabelas, endpoints) em inglês.
O plano de evolução está em [`docs/plans/plano-diretor.md`](docs/plans/plano-diretor.md); as decisões de arquitetura,
em [`docs/decisions/`](docs/decisions/).

## Fluxo

1. Uma mudança lógica = **um PR pequeno e coeso**, em branch própria a partir da `main`:
   `fix/…`, `feat/…`, `docs/…`, `ci/…`, `chore/…`. Não misture refatoração extensa, migration e funcionalidade independente.
2. Commits semânticos em português (`feat(escopo): …`, `fix(escopo): …`, `docs: …`, `ci: …`, `chore: …`, `test: …`).
3. Mudança significativa de arquitetura, de dados ou de segurança começa por uma **ADR** (ou proposta aprovada) **antes** do código.
4. Abra o PR com o modelo (`.github/pull_request_template.md`): problema, o que muda, **evidência** de validação,
   limitações e rollback. "Compila" ou "a tela aparece" não é validação.
5. O PR só entra na `main` com **CI verde** e **revisão** (code owner). Nada de commit direto na `main`.

## Qualidade mínima

| Verificação | Comando |
|---|---|
| Testes do backend (SQLite, rápido) | `cd backend && uv run pytest` |
| Testes do backend em PostgreSQL (inclui `pg` e `migrations`) | `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test` e `docker compose -f docker-compose.test.yml up -d` (ver `docs/11-base-de-testes-e-homologacao.md`) |
| Lint do backend | `cd backend && uv run ruff check app tests alembic` |
| Models × migrations | `cd backend && uv run alembic upgrade head && uv run alembic check` |
| Scripts de operação | `shellcheck scripts/*.sh` |
| Frontend | `cd frontend && npm ci && npm run test -- --watch=false && npm run build` |

Regras que o CI faz cumprir: `ruff` sem achados (regras de defeito), `alembic check` sem diferença, `shellcheck` limpo,
testes em SQLite **e** PostgreSQL, imagens Docker construindo.

## Banco de dados

- Uma migration por PR; **testar com dados**: `alembic upgrade head` → `downgrade -1` → `upgrade head`.
- Alterou um model? A migration correspondente vai junto (`alembic check` reprova o PR se faltar).
- Nunca rode testes contra um banco que não seja descartável (o guarda `backend/tests/_guard.py` exige nome terminado em `_test`).

## Segredos

Nada de senha, token, chave ou dump em código, testes, logs, issues ou PRs. `.env` e `certs/` não vão para o Git
(`.env.example` só tem nomes de variáveis).

## Revisão

O revisor confere o diff **e** a evidência: roda ou lê os testes, confirma as afirmações da descrição contra o código
e procura mudança de comportamento escondida em PRs "mecânicos". Achado sério volta para o autor antes do merge.
