#!/usr/bin/env bash
# =============================================================================
# CI local: as mesmas verificações do GitHub Actions, em contêineres Linux, antes de publicar.
#
# Uso:
#   scripts/ci-local.sh                 # só as áreas alteradas em relação à main (como o job `changes` do CI)
#   scripts/ci-local.sh --all           # tudo, como a execução semanal
#   scripts/ci-local.sh --only backend,frontend
#   scripts/ci-local.sh --no-docker     # pula o build das imagens (mais rápido; o CI ainda o fará)
#   scripts/ci-local.sh --base origin/main
#   make ci-local / make ci-local-full  # atalhos (Linux/WSL); no Windows: bash scripts/ci-local.sh
#
# Áreas e o que roda (mesma regra do .github/workflows/ci.yml):
#   backend  (backend/)                          ruff, alembic upgrade + check, pytest (PostgreSQL descartável)
#   frontend (frontend/)                         npm ci, lint --quiet, test, build
#   docker   (backend/ nginx/ frontend/ compose) build das imagens do backend e do nginx (sem publicar)
#   scripts  (scripts/)                          shellcheck
#   audit    (uv.lock, package-lock.json)        pip-audit e npm audit (informativos, como no CI)
#   Mudou .github/workflows/: roda tudo.
#
# Segurança: nada aqui usa o banco de desenvolvimento, de teste ou de produção. O único banco é o do
# docker-compose.ci.yml: em memória, rede interna sem porta, nome terminado em `_test`, apagado ao final.
# O repositório é montado só leitura nos contêineres.
#
# Saída: resumo no terminal e em .ci-local/ultimo-resultado.txt (para colar no PR). Código 0 = tudo passou.
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash no Windows: não converter caminhos dos argumentos do docker

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2
COMPOSE=(docker compose -f docker-compose.ci.yml)

base="origin/main"
mode="changed"
only=""
with_docker=true

while [ $# -gt 0 ]; do
  case "$1" in
    --all) mode="all" ;;
    --only) only="${2:-}"; mode="only"; shift ;;
    --no-docker) with_docker=false ;;
    --base) base="${2:-}"; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $1 (use --help)" >&2; exit 2 ;;
  esac
  shift
done

command -v docker >/dev/null || { echo "Docker não encontrado. Instale/ligue o Docker Desktop." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "O Docker não está respondendo. Ligue o Docker Desktop e tente de novo." >&2; exit 2; }

# ---------------------------------------------------------------------------
# Quais áreas rodar
# ---------------------------------------------------------------------------
changed_files() {
  local merge_base
  if ! merge_base="$(git merge-base HEAD "$base" 2>/dev/null)"; then
    echo "Não achei a base '$base'. Rode 'git fetch origin' ou use --base / --all." >&2
    return 1
  fi
  {
    git diff --name-only "$merge_base" HEAD      # commits da branch
    git diff --name-only HEAD                    # alterações ainda não commitadas
    git ls-files --others --exclude-standard     # arquivos novos
  } | sort -u
}

declare -A run=([backend]=false [frontend]=false [docker]=false [scripts]=false [audit]=false)
files=""
case "$mode" in
  all) for a in "${!run[@]}"; do run[$a]=true; done ;;
  only)
    IFS=',' read -r -a wanted <<< "$only"
    for a in "${wanted[@]}"; do
      [ -n "${run[$a]+x}" ] || { echo "Área desconhecida: $a (backend, frontend, docker, scripts, audit)" >&2; exit 2; }
      run[$a]=true
    done ;;
  changed)
    files="$(changed_files)" || exit 2
    matches() { printf '%s\n' "$files" | grep -Eq "$1"; }
    if matches '^\.github/workflows/'; then
      for a in "${!run[@]}"; do run[$a]=true; done
    else
      matches '^backend/' && run[backend]=true
      matches '^frontend/' && run[frontend]=true
      matches '^(backend|nginx|frontend)/|^docker-compose' && run[docker]=true
      matches '^scripts/' && run[scripts]=true
      matches '(uv\.lock|package-lock\.json)$' && run[audit]=true
    fi ;;
esac
[ "$with_docker" = true ] || run[docker]=false

# ---------------------------------------------------------------------------
# Execução e resumo
# ---------------------------------------------------------------------------
results=()
failed=0
LOG_DIR="$ROOT/.ci-local"
mkdir -p "$LOG_DIR"

step() { # step "nome" comando...
  local name="$1"; shift
  local log start=$SECONDS
  log="$LOG_DIR/$(printf '%s' "$name" | tr ' /:()' '_____').log"
  printf '\n==> %s\n' "$name"
  if "$@" 2>&1 | tee "$log"; then
    results+=("OK     $(printf '%4ds' $((SECONDS - start)))  $name")
  else
    results+=("FALHOU $(printf '%4ds' $((SECONDS - start)))  $name  (log: .ci-local/$(basename "$log"))")
    failed=1
  fi
}

# shellcheck disable=SC2317,SC2329  # chamadas indiretas (trap e step); SC2329 é o nome no shellcheck 0.11
cleanup() { "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT

# shellcheck disable=SC2317,SC2329
in_backend() { "${COMPOSE[@]}" run --rm --no-deps ci-backend sh -c "$1"; }       # com internet, sem banco
# shellcheck disable=SC2317,SC2329
in_backend_db() { "${COMPOSE[@]}" run --rm ci-backend-db sh -c "$1"; }           # com banco, sem internet

if [ "${run[backend]}" = true ]; then
  step "backend: imagem" "${COMPOSE[@]}" build -q ci-backend
  step "backend: dependências (uv sync)" in_backend "uv sync --frozen --no-install-project --quiet"
  step "backend: banco descartável" "${COMPOSE[@]}" up -d --wait ci-db
  step "backend: ruff" in_backend_db "/venv/bin/ruff check app tests alembic"
  step "backend: alembic upgrade head" in_backend_db "/venv/bin/alembic upgrade head"
  step "backend: alembic check" in_backend_db "/venv/bin/alembic check"
  step "backend: pytest" in_backend_db "/venv/bin/python -m pytest -q -p no:cacheprovider"
fi

if [ "${run[frontend]}" = true ]; then
  # Copia o código para dentro do contêiner (sem o node_modules do host, que pode ser de outro sistema).
  step "frontend: npm ci, lint, test, build" "${COMPOSE[@]}" run --rm ci-frontend sh -c '
    set -e
    tar -C /src/frontend --exclude=node_modules --exclude=dist --exclude=.angular -cf - . | tar -C /work -xf -
    npm ci --no-audit --no-fund
    npm run lint -- --quiet
    npm run test -- --watch=false
    npm run build'
fi

if [ "${run[scripts]}" = true ]; then
  step "scripts: shellcheck" "${COMPOSE[@]}" run --rm ci-shellcheck sh -c 'shellcheck scripts/*.sh'
fi

if [ "${run[audit]}" = true ]; then
  # Informativo, como no CI: achados não reprovam; erro de ferramenta reprova.
  # shellcheck disable=SC2016  # o $? é do shell do contêiner
  step "audit: pip-audit (informativo)" in_backend '
    uv export --frozen --no-dev --no-emit-project -o /tmp/req.txt --quiet
    uv tool run pip-audit -r /tmp/req.txt --no-deps --disable-pip; rc=$?
    [ "$rc" -le 1 ] || exit "$rc"; exit 0'
  step "audit: npm audit (informativo)" "${COMPOSE[@]}" run --rm ci-frontend sh -c '
    cp /src/frontend/package.json /src/frontend/package-lock.json /work/ && npm audit --omit=dev --audit-level=high || true'
fi

if [ "${run[docker]}" = true ]; then
  step "docker: imagem do backend" docker build -q -t gti-backend:ci-local ./backend
  step "docker: imagem do nginx (compila o frontend)" docker build -q -f nginx/Dockerfile -t gti-nginx:ci-local .
fi

# ---------------------------------------------------------------------------
areas=""
for a in backend frontend docker scripts audit; do [ "${run[$a]}" = true ] && areas="$areas $a"; done
{
  echo "CI local — $(date '+%Y-%m-%d %H:%M')"
  echo "Commit: $(git rev-parse --short HEAD) ($(git branch --show-current))$( [ -n "$(git status --porcelain)" ] && echo ' + alterações não commitadas')"
  echo "Modo: $mode | áreas:${areas:- nenhuma (só documentação?)}"
  [ ${#results[@]} -gt 0 ] && printf '%s\n' "${results[@]}"
  [ "$failed" -eq 0 ] && echo "RESULTADO: tudo passou" || echo "RESULTADO: há falhas — corrija e rode de novo antes de publicar"
} | tee "$LOG_DIR/ultimo-resultado.txt"

exit "$failed"
