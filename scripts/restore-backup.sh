#!/bin/sh
# Restaura um backup .sql.gz gerado pelo sistema, com a API parada.
#
# Uso: scripts/restore-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz
#
# - gera antes um dump de segurança (pre-restore-<data>.sql.gz) no diretório atual
# - para o backend, restaura em uma única transação (aborta no primeiro erro) e sobe o backend
# - restaura SOMENTE o banco; anexos e logo ficam nos volumes attachments_data / static_data
set -eu

FILE="${1:?Informe o arquivo de backup (.sql.gz)}"
[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE" >&2; exit 1; }
gzip -t "$FILE" || { echo "Arquivo .gz corrompido: $FILE" >&2; exit 1; }

DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-gestao_ti}"
STAMP="$(date +%Y%m%d_%H%M%S)"

echo "==> Dump de segurança: pre-restore-$STAMP.sql.gz"
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "pre-restore-$STAMP.sql.gz"

echo "==> Parando o backend"
docker compose stop backend

echo "==> Restaurando (transação única, ON_ERROR_STOP)"
if gunzip -c "$FILE" | docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --single-transaction -q; then
  echo "==> Restauração concluída"
else
  echo "!! Falha na restauração: nada foi aplicado. Dump de segurança: pre-restore-$STAMP.sql.gz" >&2
  docker compose start backend
  exit 1
fi

echo "==> Iniciando o backend"
docker compose start backend
