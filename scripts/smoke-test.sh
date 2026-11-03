#!/usr/bin/env bash
# =============================================================================
# Teste de fumaça das imagens: sobe a pilha real (postgres, backend, worker, nginx) com as imagens já
# construídas, num projeto Compose descartável, e confere que o sistema FUNCIONA, não só que responde 200.
#
# Uso:
#   scripts/smoke-test.sh                       # imagens gti-backend:ci-local e gti-nginx:ci-local
#   SMOKE_BACKEND_IMAGE=... SMOKE_NGINX_IMAGE=... scripts/smoke-test.sh
#
# Verifica (pelo Nginx, como um navegador chegaria):
#   1. /api/v1/health: JSON com status "healthy", banco "healthy", worker "healthy" e a versão do pyproject;
#   2. migrations na última versão (alembic current = head) e seed concluído;
#   3. rota pública que lê o banco (/api/v1/organization/company/public) responde JSON;
#   4. o frontend é servido (index com <app-root>) e uma rota do SPA cai no index;
#   5. o caminho interno da Evolution continua bloqueado no Nginx (404);
#   6. rota protegida sem token responde 401.
#
# Segurança: projeto Compose próprio (`gti-smoke`), segredos gerados na hora e descartados, porta só em
# 127.0.0.1, e tudo (contêineres e volumes do projeto) é apagado ao final. Não toca em gti-dev nem em produção.
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2

PROJECT=gti-smoke
PORT="${SMOKE_PORT:-18088}"
BASE="http://127.0.0.1:${PORT}"
mkdir -p .ci-local
ENV_FILE=".ci-local/smoke.env"  # relativo: funciona no Git Bash (Windows) e no Linux
COMPOSE=(docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.smoke.yml)
PY="$(command -v python3 || command -v python)"
failures=0

rand_hex() { "$PY" -c "import secrets; print(secrets.token_hex($1))"; }

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1
  rm -f "$ENV_FILE"
}
trap cleanup EXIT

check() { # check "descrição" condição(ões)...
  local name="$1"; shift
  if "$@"; then echo "OK      $name"; else echo "FALHOU  $name"; failures=$((failures + 1)); fi
}

{
  echo "POSTGRES_PASSWORD=$(rand_hex 16)"
  echo "SECRET_KEY=$(rand_hex 32)"
  echo "APP_ENCRYPTION_KEY=$("$PY" -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  echo "HTTP_PORT=127.0.0.1:${PORT}"
  echo "CORS_ORIGINS=[\"http://127.0.0.1:${PORT}\"]"
} > "$ENV_FILE"

expected_version="$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)"

echo "==> Subindo a pilha descartável ($PROJECT, porta $PORT)"
if ! "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 180 postgres backend worker nginx; then
  echo "FALHOU  a pilha não ficou saudável em 180 s"
  "${COMPOSE[@]}" ps
  "${COMPOSE[@]}" logs --tail 80 backend worker nginx
  exit 1
fi

# --- 1. health com conteúdo (o worker publica o batimento a cada ciclo; espera até 60 s) -------------------
health=""
for _ in $(seq 1 30); do
  health="$(curl -fsS "$BASE/api/v1/health" 2>/dev/null || true)"
  printf '%s' "$health" | grep -q '"worker":"healthy"' && break
  sleep 2
done
echo "health: $health"
health_ok() {
  printf '%s' "$health" | "$PY" -c '
import json, sys
h = json.load(sys.stdin)
expected = sys.argv[1]
problems = []
if h.get("status") != "healthy": problems.append("status=" + str(h.get("status")))
if h.get("components", {}).get("database") != "healthy": problems.append("banco não está healthy")
if h.get("components", {}).get("worker") != "healthy": problems.append("worker não está healthy")
if h.get("version") != expected: problems.append("versão " + str(h.get("version")) + " != " + expected)
if problems: print("  " + "; ".join(problems)); sys.exit(1)
' "$expected_version"
}
check "health: status, banco, worker e versão $expected_version" health_ok

# --- 2. migrations e seed -------------------------------------------------------------------------------
alembic_head() { "${COMPOSE[@]}" exec -T backend alembic current 2>/dev/null | grep -q "(head)"; }
check "migrations na última versão (alembic current = head)" alembic_head
seed_done() { "${COMPOSE[@]}" logs backend 2>/dev/null | grep -q "Iniciando aplicação"; }
check "seed concluído antes de iniciar a API" seed_done

# --- 3. rota pública que lê o banco ------------------------------------------------------------------------
public_company() {
  curl -fsS "$BASE/api/v1/organization/company/public" | "$PY" -c 'import json, sys; json.load(sys.stdin)'
}
check "rota pública com dados do banco responde JSON" public_company

# --- 4. frontend ------------------------------------------------------------------------------------------
check "frontend servido (index com <app-root>)" sh -c "curl -fsS '$BASE/' | grep -q '<app-root'"
check "rota do SPA cai no index" sh -c "curl -fsS '$BASE/service-desk' | grep -q '<app-root'"

# --- 5 e 6. bloqueios -------------------------------------------------------------------------------------
status_of() { curl -s -o /dev/null -w '%{http_code}' -X "$1" "$BASE$2"; }
check "caminho interno da Evolution bloqueado no Nginx (404)" \
  test "$(status_of POST /api/v1/integrations/whatsapp/evolution/webhook)" = "404"
check "rota protegida sem token responde 401" test "$(status_of GET /api/v1/tickets)" = "401"

if [ "$failures" -gt 0 ]; then
  echo "RESULTADO: $failures verificação(ões) falharam"
  "${COMPOSE[@]}" logs --tail 60 backend worker nginx
  exit 1
fi
echo "RESULTADO: teste de fumaça passou"
