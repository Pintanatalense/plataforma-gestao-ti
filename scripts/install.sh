#!/usr/bin/env bash
# Instalação guiada da Plataforma de Gestão de TI (Linux, macOS, WSL, Git Bash).
#
#   scripts/install.sh              gera o .env (se não existir), sobe o sistema e espera ficar pronto
#   scripts/install.sh --env-only   só gera o .env, sem subir nada
#   scripts/install.sh --check      só verifica os requisitos (não instala nem altera nada)
#   scripts/install.sh --yes        instala sem perguntar o que faltar (Docker, curl, openssl)
#   scripts/install.sh --dry-run    mostra o que seria instalado, sem executar
#   scripts/install.sh --port 8080  porta HTTP publicada (padrão 80)
#   scripts/install.sh --https [hosts]   ativa HTTPS com certificado autoassinado (hosts: nomes/IPs extras separados
#                                   por vírgula, ex.: ti.local,192.168.0.10); porta com --https-port (padrão 443)
#
# Seguro para rodar de novo: nunca sobrescreve um .env existente.
#
# Plataforma de Gestão de TI — instalador Linux/macOS/WSL.
# Developed by Hedú • InfraNuvem • https://infranuvem.com.br  (HeduInfo)
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_ONLY=0
CHECK_ONLY=0
ASSUME_YES=0
DRY_RUN=0
PORT=""
HTTPS=0
HTTPS_HOSTS=""
HTTPS_PORT_ARG=""
need_arg() { if [ "$#" -lt 2 ] || [ -z "$2" ]; then echo "Faltou o valor de $1 (use --help)" >&2; exit 2; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --env-only) ENV_ONLY=1 ;;
    --check) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --port) need_arg "$@"; PORT="$2"; shift ;;
    --https) HTTPS=1; case "${2:-}" in ""|--*) ;; *) HTTPS_HOSTS="$2"; shift ;; esac ;;
    --https-port) need_arg "$@"; HTTPS_PORT_ARG="$2"; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opção desconhecida: $1 (use --help)" >&2; exit 2 ;;
  esac
  shift
done

case "$PORT$HTTPS_PORT_ARG" in *[!0-9]*) echo "Porta inválida: use só números (--port / --https-port)." >&2; exit 2 ;; esac
for port_value in "$PORT" "$HTTPS_PORT_ARG"; do
  if [ -n "$port_value" ] && { [ "$port_value" -lt 1 ] || [ "$port_value" -gt 65535 ]; }; then
    echo "Porta fora do intervalo 1-65535: $port_value" >&2; exit 2
  fi
done
case "$HTTPS_HOSTS" in *[!A-Za-z0-9._:,-]*) echo "--https: use só nomes/IPs separados por vírgula (letras, números, ponto, dois-pontos e hífen)." >&2; exit 2 ;; esac

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


# --- Identidade e requisitos mínimos ----------------------------------------------------------------
MIN_RAM_MB=1800      # 2 GB com folga (uma VM de "2 GB" reporta ~1,9 GB); abaixo disso o PostgreSQL e o build não cabem
REC_RAM_MB=3700      # 4 GB com folga
MIN_DISK_GB=10       # imagens, volumes do banco e anexos
BRAND_YEAR="$(date +%Y)"

banner() {
  printf '\n  Plataforma de Gestão de TI — Instalador\n'
  printf '  Developed by Hedú • InfraNuvem • %s  (HeduInfo)\n  https://infranuvem.com.br\n\n' "$BRAND_YEAR"
}

ok()   { printf '  [ok]   %s\n' "$*"; }
miss() { printf '  [FALTA] %s\n' "$*"; }
note() { printf '  [aviso] %s\n' "$*"; }

SUDO=""
NEED_DOCKER_SUDO=0

# Roda um comando de instalação (respeitando --dry-run). Usa sudo quando não é root.
run_install() {
  if [ "$DRY_RUN" -eq 1 ]; then printf '  (dry-run) %s\n' "$*"; return 0; fi
  # shellcheck disable=SC2086
  $SUDO "$@"
}

ask_yes() { # ask_yes "pergunta": com --yes sempre sim; sem terminal interativo, não
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -t 0 ] || return 1
  local answer
  read -r -p "$1 [s/N] " answer
  case "$answer" in s|S|sim|SIM|y|Y) return 0 ;; *) return 1 ;; esac
}

# docker pode exigir sudo logo depois da instalação (o grupo "docker" só vale em um novo login).
docker() {
  if [ "$NEED_DOCKER_SUDO" -eq 1 ]; then command sudo "$(type -P docker)" "$@"; else command docker "$@"; fi
}

detect_pm() {
  for pm in apt-get dnf yum zypper pacman apk; do
    if command -v "$pm" >/dev/null 2>&1; then printf '%s' "$pm"; return 0; fi
  done
  return 0
}

pm_install() { # pm_install pacote...
  local pm; pm="$(detect_pm)"
  case "$pm" in
    apt-get) run_install apt-get update -y && run_install apt-get install -y "$@" ;;
    dnf)     run_install dnf install -y "$@" ;;
    yum)     run_install yum install -y "$@" ;;
    zypper)  run_install zypper --non-interactive install "$@" ;;
    pacman)  run_install pacman -Sy --noconfirm "$@" ;;
    apk)     run_install apk add --no-cache "$@" ;;
    *)       return 1 ;;
  esac
}

free_mb_ram() {
  if [ -r /proc/meminfo ]; then awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo
  elif command -v sysctl >/dev/null 2>&1; then echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 ))
  else echo 0; fi
}

os_pretty_name() {
  # shellcheck source=/dev/null
  if [ -r /etc/os-release ]; then . /etc/os-release; printf "%s" "${PRETTY_NAME:-Linux}"; else printf "Linux"; fi
}

free_gb_disk() { df -Pk . 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}'; }

port_busy() { # port_busy PORTA: 0 se alguém já escuta
  local port="$1"
  local listing=""
  if command -v ss >/dev/null 2>&1; then listing="$(ss -ltn 2>/dev/null || true)"
  elif command -v netstat >/dev/null 2>&1; then listing="$(netstat -ltn 2>/dev/null || true)"
  else return 1; fi
  printf '%s\n' "$listing" | awk -v port="$port" '{n = split($4, a, /[:.]/); if (a[n] == port) found = 1} END {exit found ? 0 : 1}'
}

install_docker() {
  local pm; pm="$(detect_pm)"
  say "Instalando o Docker Engine com o Compose v2..."
  case "$pm" in
    pacman) pm_install docker docker-compose ;;
    apk)    pm_install docker docker-cli-compose ;;
    *)
      # Script oficial da Docker Inc. (https://get.docker.com): trata Debian, Ubuntu, Fedora, RHEL/CentOS/Rocky/Alma e SUSE.
      command -v curl >/dev/null 2>&1 || pm_install curl ca-certificates || return 1
      if [ "$DRY_RUN" -eq 1 ]; then
        printf '  (dry-run) curl -fsSL https://get.docker.com | %s sh\n' "${SUDO:-}"
      else
        local tmp_dir rc=0
        tmp_dir="$(mktemp -d)" || return 1
        curl --proto '=https' --tlsv1.2 -fsSL https://get.docker.com -o "$tmp_dir/get-docker.sh" || rc=1
        # shellcheck disable=SC2086
        [ "$rc" -eq 0 ] && { $SUDO sh "$tmp_dir/get-docker.sh" || rc=1; }
        rm -rf "$tmp_dir"
        [ "$rc" -eq 0 ] || return 1
      fi
      ;;
  esac
  if [ "$DRY_RUN" -eq 0 ]; then
    if command -v systemctl >/dev/null 2>&1; then $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
    elif command -v rc-service >/dev/null 2>&1; then $SUDO rc-update add docker default >/dev/null 2>&1 || true; $SUDO rc-service docker start >/dev/null 2>&1 || true
    fi
    local target_user="${SUDO_USER:-${USER:-}}"
    if [ -n "$target_user" ] && [ "$target_user" != "root" ]; then
      if $SUDO usermod -aG docker "$target_user" 2>/dev/null; then
        say "O usuário '$target_user' foi adicionado ao grupo docker (acesso equivalente a administrador do servidor)."
      fi
    fi
    # O grupo "docker" só vale em um novo login: nesta execução usa sudo.
    if ! command docker info >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then NEED_DOCKER_SUDO=1; fi
  fi
}

# Verifica (e, se permitido, instala) os requisitos. Sai com erro se algo essencial continuar faltando.
preflight() {
  local missing=0 pm ram disk http_port https_port

  say "Verificando os requisitos mínimos..."
  case "$(uname -s)" in
    Linux)  ok "Sistema: $(os_pretty_name) ($(uname -m))" ;;
    Darwin) note "macOS: o instalador funciona, mas o Docker Desktop precisa ser instalado manualmente (https://docs.docker.com/desktop/setup/install/mac-install/)." ;;
    *)      note "Sistema não reconhecido: $(uname -s). Se for Git Bash no Windows, prefira scripts/install.ps1." ;;
  esac

  case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ok "Arquitetura compatível: $(uname -m)" ;;
    *) miss "Arquitetura não suportada: $(uname -m) (use x86_64 ou arm64)."; missing=1 ;;
  esac

  ram="$(free_mb_ram)"
  if [ "$ram" -ge "$REC_RAM_MB" ]; then ok "Memória: ${ram} MB"
  elif [ "$ram" -ge "$MIN_RAM_MB" ]; then note "Memória: ${ram} MB (funciona; o recomendado é 4 GB)"
  else miss "Memória: ${ram} MB (mínimo 2 GB)"; missing=1; fi

  disk="$(free_gb_disk)"
  if [ "${disk:-0}" -ge "$MIN_DISK_GB" ]; then ok "Disco livre aqui: ${disk} GB"
  else miss "Disco livre aqui: ${disk:-0} GB (mínimo ${MIN_DISK_GB} GB)"; missing=1; fi

  if type -P docker >/dev/null 2>&1 && ! command docker info >/dev/null 2>&1 \
     && type -P sudo >/dev/null 2>&1 && sudo -n "$(type -P docker)" info >/dev/null 2>&1; then
    NEED_DOCKER_SUDO=1
  fi

  http_port="${PORT:-$(env_value HTTP_PORT)}"; http_port="${http_port:-80}"
  if [ "$HTTPS" -eq 1 ] || grep -qE '^COMPOSE_FILE=.*https' .env 2>/dev/null; then
    https_port="${HTTPS_PORT_ARG:-$(env_value HTTPS_PORT)}"; https_port="${https_port:-443}"
  fi
  # Uma instalação já em execução ocupa as próprias portas: só é conflito se não for do compose deste projeto.
  for port in "$http_port" ${https_port:-}; do
    if port_busy "$port" && [ -z "$(docker compose ps --status running -q 2>/dev/null || true)" ]; then
      miss "Porta ${port} já está em uso por outro programa (escolha outra com --port ou libere a porta)."; missing=1
    else
      ok "Porta ${port} livre"
    fi
  done

  # Ferramentas básicas
  local to_install=""
  for tool in curl openssl; do
    if command -v "$tool" >/dev/null 2>&1; then ok "$tool"; else miss "$tool"; to_install="$to_install $tool"; fi
  done

  # Docker
  local docker_ok=1
  if type -P docker >/dev/null 2>&1; then
    ok "docker ($(command docker --version 2>/dev/null | head -n1))"
    if command docker compose version >/dev/null 2>&1; then ok "docker compose v2"; else miss "docker compose v2"; docker_ok=0; fi
    if command docker info >/dev/null 2>&1; then ok "docker em execução"
    elif command -v sudo >/dev/null 2>&1 && sudo -n "$(type -P docker)" info >/dev/null 2>&1; then
      NEED_DOCKER_SUDO=1; note "docker só responde com sudo (seu usuário não está no grupo docker); usarei sudo nesta execução."
    else miss "docker instalado, mas não está em execução (ou sem acesso)"; docker_ok=0; fi
  else
    miss "docker"; docker_ok=0
  fi

  if [ "$CHECK_ONLY" -eq 1 ]; then
    echo
    if [ "$missing" -eq 0 ] && [ -z "$to_install" ] && [ "$docker_ok" -eq 1 ]; then say "Tudo certo: o sistema atende aos requisitos."; return 0; fi
    fail "Há requisitos faltando (veja [FALTA] acima). Rode sem --check para instalar o que for possível."
  fi

  [ "$missing" -eq 0 ] || fail "Requisitos de hardware/porta não atendidos (acima). Corrija e rode de novo."

  # Instalação do que falta
  if [ -n "$to_install" ] || [ "$docker_ok" -eq 0 ]; then
    [ "$(id -u)" -eq 0 ] || { command -v sudo >/dev/null 2>&1 && SUDO="sudo"; }
    if [ "$(id -u)" -ne 0 ] && [ -z "$SUDO" ] && [ "$DRY_RUN" -eq 0 ]; then
      fail "Faltam programas e não sou root nem há sudo. Rode como root ou instale: curl, openssl e Docker com Compose v2."
    fi
    pm="$(detect_pm)"
    [ -n "$pm" ] || [ "$DRY_RUN" -eq 1 ] || fail "Gerenciador de pacotes não reconhecido. Instale manualmente: curl, openssl e Docker com Compose v2."
    echo
    echo "Vou instalar o que falta:${to_install:+ $to_install}$([ "$docker_ok" -eq 0 ] && printf ' docker (Docker Engine + Compose v2)')."
    ask_yes "Posso continuar?" || fail "Instalação cancelada. Instale os itens acima e rode de novo (ou use --yes)."
    if [ -n "$to_install" ]; then
      # shellcheck disable=SC2086
      pm_install $to_install || fail "Não consegui instalar:${to_install}."
    fi
    if [ "$docker_ok" -eq 0 ]; then
      if ! type -P docker >/dev/null 2>&1; then install_docker || fail "A instalação do Docker falhou. Veja https://docs.docker.com/engine/install/"
      elif [ "$DRY_RUN" -eq 0 ]; then
        if command -v systemctl >/dev/null 2>&1; then $SUDO systemctl enable --now docker >/dev/null 2>&1 || true; fi
        if ! command docker info >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then NEED_DOCKER_SUDO=1; fi
      fi
    fi
    if [ "$DRY_RUN" -eq 1 ]; then say "Simulação concluída: nada foi instalado."; exit 0; fi
    command docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 não ficou disponível após a instalação."
    docker info >/dev/null 2>&1 || fail "O Docker foi instalado, mas não respondeu. Abra uma nova sessão (grupo docker) ou rode: sudo systemctl start docker"
    say "Requisitos instalados."
  fi
}

# --- 1. Pré-requisitos --------------------------------------------------------------------------
banner
if [ "$ENV_ONLY" -eq 1 ] && [ "$CHECK_ONLY" -eq 0 ]; then
  command -v openssl >/dev/null 2>&1 || fail "openssl não encontrado (usado para gerar as senhas)."
else
  preflight
  [ "$CHECK_ONLY" -eq 1 ] && exit 0
fi
if [ "$DRY_RUN" -eq 1 ]; then
  say "Simulação concluída: os requisitos estão atendidos e nada foi alterado."
  exit 0
fi

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
    put_env HTTP_PORT "$PORT"
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
