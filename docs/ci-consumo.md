# Consumo do CI (GitHub Actions)

Linha de base e método de medição dos minutos do CI. Fonte única: o que o CI custa hoje e como conferir se uma mudança economizou de verdade.

## Como medir

```bash
python scripts/ci_usage.py                                     # últimos 28 dias
python scripts/ci_usage.py --since 2026-10-24 --steps 3        # a partir de uma data
python scripts/ci_usage.py --since 2026-10-23 --until 2026-10-24 --json > consumo.json
```

O script só lê (`gh api`), roda na sua máquina e **não gasta minutos**. Mostra minutos por semana, evento, job e PR (inclui execuções por PR, canceladas e falhas) e as etapas mais lentas de cada job.

**Limites:** os minutos são uma *estimativa* (duração de cada job arredondada para cima, em minutos, runner Linux). O número oficial é o de *Settings → Billing and plans → Usage*; confira os dois uma vez por mês. Execuções recusadas pelo GitHub por cobrança aparecem com 0 minuto.

**Calibração (25/10/2026):** a página de cobrança mostrou US$ 12,20 de uso bruto em outubro (todo coberto pela franquia gratuita), o que equivale a ~2.033 minutos Linux; o script estimou ~2.035. A estimativa é confiável para comparar períodos.

## Linha de base: CI atual (a partir de 24/10/2026, antes do PR-C)

13 execuções de PR, ~80 min estimados. Duração média por job (n pequeno; a variação é grande):

| Job | Duração média | Min. faturados por execução |
|---|---|---|
| `backend-postgres` | 347 s (pytest 318 s) | 5–7 |
| `docker-build` | 81 s (nginx 42 s + backend 35 s) | 2 |
| `frontend-tests` | 81 s | 2 |
| `backend-tests` | 30 s | 1 |
| `changes` | 5 s | 1 |
| `shellcheck` | 6 s | 1 |

Execução completa de um PR: **~10 a 13 min faturados**; PR só de backend: ~9 a 11. O pytest em CI variou de 239 s a 354 s entre duas execuções com os mesmos 580 testes: compare médias, não execuções isoladas.

## Antes da economia (outubro inteiro)

182 execuções, ~2.035 min: 1.499 min só em 22/10 (todo PR rodava SQLite + PostgreSQL + auditoria + shellcheck e a `main` rodava a cada merge). Por evento: `pull_request` 1.334 min, `push` na `main` 668 min, Dependabot 33 min.

## Medição local do pytest (24/10/2026, 580 testes, SQLite, Python 3.14)

| Cenário | Tempo |
|---|---|
| Padrão (bcrypt de produção, 12 rounds) | 338 s |
| Só para medir: bcrypt com 4 rounds, aplicado por plugin descartável fora do repositório | 153 s |

- **A hipótese do bcrypt se confirma**: ~55% do tempo da suíte local é hash de senha criado pelas fixtures (≈ 0,19 s por hash; `make_user` aparece em 85 pontos). Nada disso foi aplicado no código.
- **Testes mais lentos**: `tests/core/test_request_logging.py` e `tests/core/test_health.py` levam ~4 s cada (≈ 50 s no total). Localmente o `/api/v1/health` tenta conectar ao PostgreSQL da porta 55432 (que não existe aqui) até estourar o tempo; esses testes aceitam `degraded`, então **não provam que o banco está saudável**. Em CI o banco existe e o custo é outro: sem `--durations` no log do CI, o valor por teste lá é desconhecido.
- Depois do hash, os mais lentos são os de login com bloqueio/redefinição de senha (1–2,4 s: verificam o algoritmo de verdade e devem continuar assim) e os de notificações cujo *setup* cria 3 usuários (~0,9 s).

## Achados sobre o CI

1. O antigo job `backend-postgres` **não rodava a suíte em PostgreSQL**: o `conftest.py` só usa PostgreSQL quando `USE_PG_TEST=true`, e o CI definia apenas `TEST_DATABASE_URL`. A suíte principal rodava em SQLite em memória; o PostgreSQL só servia aos testes marcados `pg`/`migrations` e ao `alembic upgrade/check`. **Corrigido no PR-C** (ver abaixo).
2. Na execução semanal a suíte SQLite rodava **duas vezes** (`backend-tests` e `backend-postgres`). **Corrigido no PR-C**: os dois jobs viraram um só (`backend-tests`).
3. O frontend é compilado duas vezes (`frontend-tests` e dentro da imagem nginx); a imagem é construída mas nunca iniciada. Tratado no PR-E.

## Suíte inteira em PostgreSQL real (medição de 25/10/2026, CI local, 587 testes)

| Modo | Tempo do pytest |
|---|---|
| Padrão: regras em SQLite + testes `pg`/`migrations` no PostgreSQL | 316 s |
| `USE_PG_TEST=true`: tudo no PostgreSQL 16 | 670 s (~2,1×) |

- O modo `USE_PG_TEST=true` **nunca tinha funcionado**: o engine dos testes guardava conexões num pool e cada teste roda num event loop novo; do 2º teste em diante, 586 erros (`another operation is in progress`). Corrigido no `conftest.py` (sem pool no PostgreSQL).
- Rodando de verdade, apareceram 3 suposições de SQLite nos próprios testes (comando `PRAGMA`, data sem fuso e falta do `pg_dump` na imagem de CI local), corrigidas. Nenhum defeito do sistema.
- **Regra adotada**: a suíte inteira em PostgreSQL real roda na execução semanal/manual (junto com a SQLite) e em PRs que mexem em `backend/alembic/`, `models.py`, `repository.py`, `app/database.py` ou `tests/conftest.py`. Custo extra estimado nesses PRs: ~6 min (substitui a execução SQLite, não se soma a ela).
