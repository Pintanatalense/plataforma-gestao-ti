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
#   6. rota protegida sem token responde 401;
#   7. IP forjado no X-Forwarded-For não é gravado (setup inicial pelo Nginx; consulta no banco descartável);
#   8. documentação da API desligada por padrão; worker enxerga anexos e logo, sem poder gravar;
#   9. papéis de banco (ADR-022): backend e worker sem superusuário nem DDL, tabelas do papel dono, Evolution
#      isolada no próprio schema, e o backup pela tela (pg_dump com o papel da aplicação) funcionando;
#  10. auditoria imutável (ADR-023): a aplicação não apaga a trilha e o worker a sela numa cadeia íntegra.
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
  rm -f "$ENV_FILE" .ci-local/smoke-setup.json
}
trap cleanup EXIT

check() { # check "descrição" condição(ões)...
  local name="$1"; shift
  if "$@"; then echo "OK      $name"; else echo "FALHOU  $name"; failures=$((failures + 1)); fi
}

{
  echo "POSTGRES_PASSWORD=$(rand_hex 16)"
  echo "DB_OWNER_PASSWORD=$(rand_hex 16)"
  echo "DB_APP_PASSWORD=$(rand_hex 16)"
  echo "DB_EVOLUTION_PASSWORD=$(rand_hex 16)"
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
# A saída vai para uma variável antes do grep: com pipefail, `comando | grep -q` falha ao acaso quando o grep sai no
# primeiro achado e o comando morre de SIGPIPE ainda escrevendo (logs longos).
alembic_head() { local out; out="$("${COMPOSE[@]}" exec -T backend alembic current 2>/dev/null)"; grep -q "(head)" <<< "$out"; }
check "migrations na última versão (alembic current = head)" alembic_head
seed_done() { local out; out="$("${COMPOSE[@]}" logs backend 2>/dev/null)"; grep -q "Iniciando aplicação" <<< "$out"; }
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

# --- 7. IP real: o cliente não escolhe o IP gravado (setup inicial passa pelo bloco geral /api/ do Nginx) -----
forged="203.0.113.77"
setup_body=".ci-local/smoke-setup.json"
setup_status="$(curl -s -o "$setup_body" -w '%{http_code}' -X POST "$BASE/api/v1/identity/setup" \
  -H 'Content-Type: application/json' -H "X-Forwarded-For: $forged" -H "X-Real-IP: $forged" \
  -d "{\"email\":\"smoke@example.com\",\"password\":\"Smoke-$(rand_hex 8)-Aa1!\",\"setup_mode\":\"CLEAN\"}")"
saved_ip="$("${COMPOSE[@]}" exec -T postgres psql -U postgres -d gestao_ti -tAc \
  "select last_login_ip from user_accounts where email = 'smoke@example.com'" 2>/dev/null | tr -d '[:space:]')"
echo "setup: HTTP $setup_status, IP gravado: ${saved_ip:-<vazio>}"
check "IP forjado no X-Forwarded-For não chega à auditoria" \
  test "$setup_status" = "201" -a -n "$saved_ip" -a "$saved_ip" != "$forged"

# --- 8. padrões seguros da instalação ------------------------------------------------------------------
check "documentação da API desligada por padrão (404)" test "$(status_of GET /api/v1/openapi.json)" = "404"
worker_volumes_ro() {
  "${COMPOSE[@]}" exec -T worker sh -c \
    'test -d /data/attachments && test -d /app/static && ! touch /data/attachments/.w 2>/dev/null && ! touch /app/static/.w 2>/dev/null'
}
check "worker lê anexos e logo, só leitura" worker_volumes_ro

# --- 9. papéis de banco separados (ADR-022) ------------------------------------------------------------
db_query() { "${COMPOSE[@]}" exec -T postgres psql -U postgres -d gestao_ti -tAc "$1" 2>/dev/null | tr -d '[:space:]'; }
app_sessions="$(db_query "select string_agg(distinct a.usename || ':' || r.rolsuper::text, ',') from pg_stat_activity a
  join pg_roles r on r.rolname = a.usename where a.datname = 'gestao_ti' and a.usename <> current_user")"
echo "conexões ao banco (papel:superusuário): ${app_sessions:-<nenhuma>}"
check "backend e worker conectados só com o papel da aplicação (sem superusuário)" test "$app_sessions" = "gestao_app:false"
privileges="$(db_query "select has_schema_privilege('gestao_app', 'public', 'CREATE')::text
  || '|' || (select count(*) from pg_tables where schemaname = 'public' and tableowner <> 'gestao_owner')
  || '|' || has_table_privilege('gestao_app', 'public.alembic_version', 'UPDATE')::text
  || '|' || has_table_privilege('gestao_evolution', 'public.user_accounts', 'SELECT')::text
  || '|' || (select pg_get_userbyid(nspowner) from pg_namespace where nspname = 'evolution_api')")"
echo "privilégios (DDL app | tabelas de outro dono | app grava alembic_version | Evolution lê public | dono evolution_api): $privileges"
check "aplicação sem DDL, tabelas do dono e Evolution isolada" test "$privileges" = "false|0|false|false|gestao_evolution"
token="$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1])).get("access_token", ""))' "$setup_body" 2>/dev/null)"
backup_status="$(curl -s -X POST "$BASE/api/v1/system/backups/generate" -H "Authorization: Bearer $token" \
  | "$PY" -c 'import json, sys; print(json.load(sys.stdin).get("status"))' 2>/dev/null)"
echo "backup pela tela: ${backup_status:-<sem resposta>}"
check "backup pela tela (pg_dump com o papel da aplicação) concluído" test "$backup_status" = "SUCCESS"

# --- 10. auditoria imutável (o job audit.seal roda a cada minuto) ---------------------------------------
audit_state=""
for _ in $(seq 1 45); do
  audit_state="$(db_query "select has_table_privilege('gestao_app', 'public.audit_logs', 'DELETE')::text
    || '|' || (select count(*) from audit_logs) || '|' || (select count(*) from audit_logs where row_hash is null)
    || '|' || coalesce((select string_agg(coalesce(problem, 'ok'), ',') from audit_verify()), 'sem cadeia')")"
  case "$audit_state" in false\|[1-9]*\|0\|ok*) break ;; esac
  sleep 4
done
echo "auditoria (app apaga | registros | sem selo | cadeias): $audit_state"
check "auditoria só de inserção e selada pelo worker, cadeia íntegra" sh -c "printf '%s' '$audit_state' | grep -Eq '^false\|[1-9][0-9]*\|0\|ok(,ok)*$'"

if [ "$failures" -gt 0 ]; then
  echo "RESULTADO: $failures verificação(ões) falharam"
  "${COMPOSE[@]}" logs --tail 60 backend worker nginx
  exit 1
fi
echo "RESULTADO: teste de fumaça passou"
