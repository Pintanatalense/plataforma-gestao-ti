#!/usr/bin/env bash
# Instalação guiada da Plataforma de Gestão de TI (Linux, macOS, WSL, Git Bash).
#
#   scripts/install.sh              gera o .env (se não existir), sobe o sistema e espera ficar pronto
#   scripts/install.sh --env-only   só gera o .env, sem subir nada
#   scripts/install.sh --port 8080  porta HTTP publicada (padrão 80)
#
# Seguro para rodar de novo: nunca sobrescreve um .env existente.
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_ONLY=0
PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env-only) ENV_ONLY=1 ;;
    --port) PORT="${2:-}"; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opção desconhecida: $1 (use --help)" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '==> %s\n' "$*"; }
fail() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }

random_hex()    { openssl rand -hex "$1"; }
# Chave Fernet = 32 bytes aleatórios em base64 "url-safe" (44 caracteres com padding).
fernet_key()    { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }

env_value() { grep -E "^$1=" .env 2>/dev/null | head -n1 | cut -d= -f2- || true; }

set_env() { # set_env CHAVE VALOR: troca a linha "CHAVE=" (vazia) sem usar o valor como regex
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k && $2=="" {print k "=" v; next} {print}' .env > "$tmp"
  cat "$tmp" > .env
  rm -f "$tmp"
}

# --- 1. Pré-requisitos --------------------------------------------------------------------------
if [ "$ENV_ONLY" -eq 0 ]; then
  command -v docker >/dev/null 2>&1 || fail "Docker não encontrado. Instale o Docker com Compose v2: https://docs.docker.com/engine/install/"
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 não encontrado ('docker compose version' falhou)."
  docker info >/dev/null 2>&1 || fail "O Docker está instalado, mas não está em execução (ou seu usuário não tem acesso)."
fi
command -v openssl >/dev/null 2>&1 || fail "openssl não encontrado (usado para gerar as senhas)."

# --- 2. Arquivo .env ----------------------------------------------------------------------------
if [ -f .env ]; then
  say "Arquivo .env já existe: mantido como está."
else
  [ -f .env.example ] || fail ".env.example não encontrado; rode o script na raiz do repositório."
  say "Gerando .env com senhas aleatórias..."
  cp .env.example .env
  set_env POSTGRES_PASSWORD "$(random_hex 16)"
  set_env SECRET_KEY "$(random_hex 32)"
  set_env APP_ENCRYPTION_KEY "$(fernet_key)"
  chmod 600 .env 2>/dev/null || true
  GENERATED=1
fi

if [ -n "$PORT" ]; then
  case "$PORT" in ''|*[!0-9]*) fail "Porta inválida: $PORT" ;; esac
  if grep -qE '^HTTP_PORT=' .env; then
    awk -v v="$PORT" 'BEGIN{FS=OFS="="} $1=="HTTP_PORT" {print "HTTP_PORT=" v; next} {print}' .env > .env.tmp && cat .env.tmp > .env && rm -f .env.tmp
  else
    printf 'HTTP_PORT=%s\n' "$PORT" >> .env
  fi
fi

for required in POSTGRES_PASSWORD SECRET_KEY APP_ENCRYPTION_KEY; do
  [ -n "$(env_value "$required")" ] || fail "$required está vazio no .env. Preencha (veja os comentários do arquivo) e rode de novo."
done

if [ "${GENERATED:-0}" = "1" ]; then
  say "Senhas geradas em .env (somente leitura do dono)."
  echo
  echo "    IMPORTANTE: faça agora uma cópia da APP_ENCRYPTION_KEY FORA deste servidor"
  echo "    (cofre de senhas). Sem ela, senhas e tokens de canais gravados no banco não"
  echo "    podem ser lidos depois de uma restauração. Ela está no arquivo .env."
  echo
fi

[ "$ENV_ONLY" -eq 1 ] && { say "Pronto: .env gerado. Suba com: docker compose up -d --build"; exit 0; }

# --- 3. Subir e esperar ----------------------------------------------------------------------------
say "Construindo e iniciando os serviços (a primeira vez demora alguns minutos)..."
docker compose up -d --build

HTTP_PORT="$(env_value HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-80}"
URL="http://localhost:${HTTP_PORT}"
say "Aguardando o sistema responder em ${URL} ..."
for _ in $(seq 1 90); do
  if curl -fsS "${URL}/api/v1/health" >/dev/null 2>&1; then
    echo
    say "Sistema no ar!"
    echo "    Abra ${URL} e siga o assistente: ele cria o administrador e deixa você escolher"
    echo "    entre uma BASE LIMPA ou um MODELO DE EXEMPLO com dados fictícios."
    echo "    Para acompanhar:  docker compose ps   |   docker compose logs -f backend"
    exit 0
  fi
  sleep 2
done

echo
fail "O sistema não respondeu em 3 minutos. Veja: docker compose ps && docker compose logs --tail=80 backend"
