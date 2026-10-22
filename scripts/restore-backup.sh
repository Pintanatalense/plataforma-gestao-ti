#!/bin/sh
# Restaura um backup do banco (.sql.gz) e, opcionalmente, os arquivos (anexos e logomarca).
#
# Uso: scripts/restore-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz [/caminho/arquivos_AAAAMMDD_HHMMSS.tar.gz]
#      make restore FILE=/caminho/backup.sql.gz [FILES=/caminho/arquivos.tar.gz]
#
# - gera antes um dump de segurança (pre-restore-<data>.sql.gz) no diretório atual;
# - para o backend E o worker (o worker continuaria gravando entregas/heartbeat durante a restauração);
# - restaura o banco em uma única transação (aborta no primeiro erro, sem aplicar nada);
# - se informado o segundo arquivo, repõe anexos e logomarca (substitui o conteúdo dos volumes);
# - sobe de novo o backend e o worker.
# Quem restaura em outra máquina precisa do MESMO APP_ENCRYPTION_KEY do ambiente original.
set -eu
# Git Bash (Windows) reescreve argumentos que começam com / (ex.: tar -C /); no Linux/macOS não tem efeito.
export MSYS_NO_PATHCONV=1

FILE="${1:?Informe o arquivo de backup do banco (.sql.gz)}"
FILES_TAR="${2:-}"
[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE" >&2; exit 1; }
gzip -t "$FILE" || { echo "Arquivo .gz corrompido: $FILE" >&2; exit 1; }
if [ -n "$FILES_TAR" ]; then
  [ -f "$FILES_TAR" ] || { echo "Arquivo não encontrado: $FILES_TAR" >&2; exit 1; }
  tar -tz < "$FILES_TAR" > /dev/null || { echo "Arquivo .tar.gz corrompido: $FILES_TAR" >&2; exit 1; }
fi

DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-gestao_ti}"
STAMP="$(date +%Y%m%d_%H%M%S)"

echo "==> Dump de segurança: pre-restore-$STAMP.sql.gz"
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "pre-restore-$STAMP.sql.gz"
# gzip -t aceita até um arquivo vazio: confira também a marca final do pg_dump antes de mexer em qualquer coisa
if ! gunzip -c "pre-restore-$STAMP.sql.gz" | tail -n 5 | grep -q "dump complete"; then
  rm -f "pre-restore-$STAMP.sql.gz"
  echo "!! O dump de segurança falhou ou está incompleto; nada foi alterado." >&2
  exit 1
fi

echo "==> Parando o backend e o worker"
docker compose stop worker backend

echo "==> Restaurando o banco (transação única, ON_ERROR_STOP)"
if gunzip -c "$FILE" | docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --single-transaction -q; then
  echo "==> Banco restaurado"
else
  echo "!! Falha na restauração: nada foi aplicado. Dump de segurança: pre-restore-$STAMP.sql.gz" >&2
  docker compose start backend worker
  exit 1
fi

echo "==> Iniciando o backend"
docker compose start backend

if [ -n "$FILES_TAR" ]; then
  echo "==> Repondo anexos e logomarca"
  # o conteúdo atual dos volumes é substituído pelo do backup
  docker compose exec -T backend sh -c 'rm -rf /data/attachments/* /app/static/*'
  docker compose exec -T backend tar xzf - -C / < "$FILES_TAR"
else
  echo "   (anexos e logomarca NÃO foram restaurados: informe o segundo arquivo, arquivos_*.tar.gz)"
fi

echo "==> Iniciando o worker"
docker compose start worker
echo "==> Concluído"
