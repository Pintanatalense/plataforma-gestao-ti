#!/bin/sh
# Prova que um backup RESTAURA: aplica o .sql.gz num banco temporário (sem tocar no banco em uso), confere
# que as tabelas e os usuários voltaram e remove o banco temporário.
#
# Uso: scripts/verify-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz     (ou: make verify-backup FILE=...)
# Rode periodicamente (ex.: semanal): o SHA-256 só prova que o arquivo não mudou, não que ele restaura.
set -eu
# Git Bash (Windows) reescreve argumentos que começam com / (ex.: tar -C /); no Linux/macOS não tem efeito.
export MSYS_NO_PATHCONV=1

FILE="${1:?Informe o arquivo de backup do banco (.sql.gz)}"
[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE" >&2; exit 1; }
gzip -t "$FILE" || { echo "Arquivo .gz corrompido: $FILE" >&2; exit 1; }

DB_USER="${POSTGRES_USER:-postgres}"
TMP_DB="gestao_ti_verify_$(date +%Y%m%d%H%M%S)"
PSQL="docker compose exec -T postgres psql -U $DB_USER -v ON_ERROR_STOP=1 -q -t -A"

cleanup() { $PSQL -d postgres -c "DROP DATABASE IF EXISTS $TMP_DB" > /dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Criando banco temporário $TMP_DB"
$PSQL -d postgres -c "CREATE DATABASE $TMP_DB" > /dev/null

echo "==> Restaurando o backup nele"
gunzip -c "$FILE" | $PSQL -d "$TMP_DB" --single-transaction > /dev/null

TABLES="$($PSQL -d "$TMP_DB" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
USERS="$($PSQL -d "$TMP_DB" -c "SELECT count(*) FROM user_accounts")"
REV="$($PSQL -d "$TMP_DB" -c "SELECT version_num FROM alembic_version")"

[ "$TABLES" -gt 0 ] || { echo "!! O backup restaurou, mas sem nenhuma tabela." >&2; exit 1; }
echo "==> OK: $TABLES tabelas, $USERS usuários, migration $REV"
echo "    (o banco temporário é removido ao final)"
