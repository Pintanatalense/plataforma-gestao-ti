#!/usr/bin/env bash
# Instalação guiada da Plataforma de Gestão de TI (Linux, macOS, WSL, Git Bash).
#
#   scripts/install.sh              gera o .env (se não existir), sobe o sistema e espera ficar pronto
#   scripts/install.sh --env-only   só gera o .env, sem subir nada
#   scripts/install.sh --port 8080  porta HTTP publicada (padrão 80)
#   scripts/install.sh --https [hosts]   ativa HTTPS com certificado autoassinado (hosts: nomes/IPs extras separados
#                                   por vírgula, ex.: ti.local,192.168.0.10); porta com --https-port (padrão 443)
#
# Seguro para rodar de novo: nunca sobrescreve um .env existente.
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_ONLY=0
PORT=""
HTTPS=0
HTTPS_HOSTS=""
HTTPS_PORT_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env-only) ENV_ONLY=1 ;;
    --port) PORT="${2:-}"; shift ;;
    --https) HTTPS=1; case "${2:-}" in ""|--*) ;; *) HTTPS_HOSTS="$2"; shift ;; esac ;;
    --https-port) HTTPS_PORT_ARG="${2:-}"; shift ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

put_env() { # put_env CHAVE VALOR: troca a linha existente ou acrescenta no fim
  local key="$1" value="$2" tmp
  if grep -qE "^${key}=" .env; then
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env > "$tmp"
    cat "$tmp" > .env
    rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

make_cert() { # make_cert HOSTS: certificado autoassinado em ./certs (gerado com a imagem alpine/openssl)
  local hosts="$1" san="DNS:localhost,IP:127.0.0.1,IP:::1" first="localhost" h
  IFS=',' read -ra list <<< "$hosts"
  for h in "${list[@]:-}"; do
    h="$(printf '%s' "$h" | tr -d ' ')"
    [ -z "$h" ] && continue
    if printf '%s' "$h" | grep -qE '^[0-9.]+$|:'; then san="$san,IP:$h"; else san="$san,DNS:$h"; fi
    first="$h"
  done
  mkdir -p certs
  MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)/certs:/certs" alpine/openssl req -x509 -newkey rsa:2048 -nodes -days 730 \
    -keyout /certs/server.key -out /certs/server.crt -subj "/CN=${first}" \
    -addext "subjectAltName=${san}" -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=digitalSignature,keyEncipherment,keyCertSign" -addext "extendedKeyUsage=serverAuth" >/dev/null 2>&1 \
    || fail "Não consegui gerar o certificado (o Docker precisa conseguir baixar a imagem alpine/openssl)."
  say "Certificado autoassinado criado em certs/ (válido por 2 anos; vale para: ${san})."
}

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

if [ "$HTTPS" -eq 1 ]; then
  [ "$ENV_ONLY" -eq 1 ] && fail "--https precisa do Docker para gerar o certificado; não combine com --env-only."
  if [ -f certs/server.crt ] && [ -f certs/server.key ]; then
    say "Certificado em certs/ já existe: mantido (apague a pasta para gerar outro)."
  else
    make_cert "$HTTPS_HOSTS"
  fi
  put_env HTTPS_PORT "${HTTPS_PORT_ARG:-$(env_value HTTPS_PORT)}"
  [ -n "$(env_value HTTPS_PORT)" ] || put_env HTTPS_PORT 443
  put_env COMPOSE_PATH_SEPARATOR ":"
  put_env COMPOSE_FILE "docker-compose.yml:docker-compose.https.yml"
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
CURL_OPTS="-fsS"
if grep -qE '^COMPOSE_FILE=.*https' .env; then
  URL="https://localhost:$(env_value HTTPS_PORT)"; CURL_OPTS="-fsSk"
fi
say "Aguardando o sistema responder em ${URL} ..."
for _ in $(seq 1 90); do
  if curl $CURL_OPTS "${URL}/api/v1/health" >/dev/null 2>&1; then
    echo
    say "Sistema no ar!"
    echo "    Abra ${URL} e siga o assistente: ele cria o administrador e deixa você escolher"
    echo "    entre uma BASE LIMPA ou um MODELO DE EXEMPLO com dados fictícios."
    if [ "$CURL_OPTS" = "-fsSk" ]; then
      echo "    HTTPS autoassinado: o navegador avisa que o certificado não é confiável. Para o pop-up do navegador"
      echo "    funcionar, importe certs/server.crt como autoridade raiz confiável (veja docs/02, seção 7)."
    fi
    echo "    Para acompanhar:  docker compose ps   |   docker compose logs -f backend"
    exit 0
  fi
  sleep 2
done

echo
fail "O sistema não respondeu em 3 minutos. Veja: docker compose ps && docker compose logs --tail=80 backend"
