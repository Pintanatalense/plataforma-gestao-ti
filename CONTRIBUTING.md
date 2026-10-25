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
   Com um único code owner, o GitHub não deixa o dono aprovar o PR que ele mesmo abriu: use um autor diferente do dono, um segundo code owner ou o bypass de administrador na proteção da `main`.

Dependabot: PRs semanais de dependências (limite baixo no início). Versão **maior** de runtime (Python, Node, PostgreSQL, Nginx, uv) não é proposta automaticamente; o `uv` do `backend/Dockerfile` é atualizado à mão.

## Qualidade mínima

| Verificação | Comando |
|---|---|
| Testes do backend (SQLite, rápido) | `cd backend && uv run pytest` |
| Testes do backend em PostgreSQL (inclui `pg` e `migrations`) | `docker compose -f docker-compose.test.yml up -d`; depois `export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test` e `cd backend && uv run pytest` (sem a variável os testes `pg`/`migrations` são ignorados; ver `docs/11-base-de-testes-e-homologacao.md`) |
| Lint do backend | `cd backend && uv run ruff check app tests alembic` |
| Models × migrations | `cd backend && uv run alembic upgrade head && uv run alembic check` |
| Scripts de operação | `shellcheck scripts/*.sh` |
| Frontend | `cd frontend && npm ci && npm run test -- --watch=false && npm run build` |

Regras que o CI faz cumprir: `ruff` sem achados (regras de defeito), `alembic check` sem diferença, `shellcheck` limpo,
testes em SQLite **e** PostgreSQL, imagens Docker construindo.

## Telas que dependem da API (frontend)

Toda tela que carrega dados trata **quatro estados**: carregando, erro (com "Tentar novamente"), vazio e conteúdo.
**Falha de comunicação nunca pode parecer lista vazia ou zero.**

- Componente `<app-load-state>` (`shared/components/load-state`): `[loading]`, `[error]` (texto), `[empty]`, `(retry)`.
- Mensagem de erro: `apiErrorMessage(err, "texto padrão")` (`core/http/api-error.ts`). A API responde `{ error: { message } }`;
  **não existe** `err.error.detail`.
- O interceptor (`jwt.interceptor.ts`) já avisa uma vez quando o servidor não responde (status 0 ou 5xx) e, ao expirar a sessão,
  guarda a página para voltar a ela depois do login. Não repita esse aviso na tela.
- Não escreva `error: () => {}` nem só `console.error`. Teste a falha da API: o número não vira zero, o aviso aparece e "Tentar novamente" recarrega.

## Banco de dados

- Uma migration por PR; **testar com dados**: `alembic upgrade head` → `downgrade -1` → `upgrade head`.
- Alterou um model? A migration correspondente vai junto (`alembic check` reprova o PR se faltar).
- Nunca rode testes contra um banco que não seja descartável (o guarda `backend/tests/_guard.py` exige nome terminado em `_test` **e** host local).

## Segredos

Nada de senha, token, chave ou dump em código, testes, logs, issues ou PRs. `.env` e `certs/` não vão para o Git
(`.env.example` só tem nomes de variáveis).

## Revisão

O revisor confere o diff **e** a evidência: roda ou lê os testes, confirma as afirmações da descrição contra o código
e procura mudança de comportamento escondida em PRs "mecânicos". Achado sério volta para o autor antes do merge.

## Minutos do GitHub Actions

O plano gratuito dá 2.000 minutos por mês (e o aviso chega aos 90%). Uma execução completa do CI custa cerca de 10 a 13 minutos faturados (medição de 24/10/2026 em [docs/ci-consumo.md](docs/ci-consumo.md), que também ensina a medir o consumo com `scripts/ci_usage.py`), por isso:

- **Rode o CI local antes de subir**: `make ci-local` (Linux/WSL) ou `bash scripts/ci-local.sh` (Git Bash no Windows). Ele roda as mesmas verificações do CI, só nas áreas que mudaram, em contêineres Linux (Python 3.12, Node 22, PostgreSQL 16 descartável), e grava o resumo em `.ci-local/ultimo-resultado.txt` para colar no PR. `--all` roda tudo; `--no-docker` pula o build das imagens. O CI confirma; não é para descobrir erro.
  - Precisa só do Docker ligado. O banco é criado em memória, numa rede interna sem porta, e apagado ao final; o código é montado só leitura. Nunca aponta para o banco de desenvolvimento ou de produção.
  - Diferenças que ainda podem existir: o runner do GitHub (Ubuntu) e a versão do `uv` instalada pelo CI. Verde local reduz, mas não elimina, a chance de falha no CI.
- **Um PR, poucos commits.** Cada `push` num PR reexecuta o que mudou. Junte as correções de revisão em um único commit em vez de um commit por achado.
- **O CI só roda o que o PR tocou** (job `changes`): só documentação não roda nada pesado; só frontend não roda o backend. Mudar `.github/workflows/` roda tudo.
- **Não há execução em `push` na `main`** (o PR já rodou o mesmo código). A suíte completa, inclusive SQLite e auditoria de dependências, roda toda segunda-feira e sob demanda (aba *Actions* → *CI* → *Run workflow*).
- **Dependabot é mensal e sem rebase automático**: cada rebase reexecuta o CI. Revise os PRs dele em lote, um por vez.
- Consulte o gasto em *Settings → Billing → Usage*. Para nunca cobrar além do incluído, defina um orçamento de US$ 0 para Actions (isso bloqueia as execuções ao chegar no limite).
