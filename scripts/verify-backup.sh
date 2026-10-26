#!/bin/sh
# Prova que um backup RESTAURA: aplica o .sql.gz num banco temporário (sem tocar no banco em uso), confere
# que as tabelas, os usuários e a cadeia da auditoria voltaram e remove o banco temporário. Com o pacote de
# arquivos (.tar.gz), confere também que todo anexo registrado no banco está no pacote.
#
# Uso: scripts/verify-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz [/caminho/arquivos_..._.tar.gz]
#      make verify-backup FILE=... [FILES=...]
# Rode periodicamente (ex.: semanal, por cron no servidor): o SHA-256 só prova que o arquivo não mudou, não que ele
# restaura. Outro projeto Compose: use COMPOSE_PROJECT_NAME / COMPOSE_FILE / COMPOSE_ENV_FILES.
set -eu
# Git Bash (Windows) reescreve argumentos que começam com / (ex.: tar -C /); no Linux/macOS não tem efeito.
export MSYS_NO_PATHCONV=1

FILE="${1:?Informe o arquivo de backup do banco (.sql.gz)}"
FILES_TAR="${2:-}"
[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE" >&2; exit 1; }
gzip -t "$FILE" || { echo "Arquivo .gz corrompido: $FILE" >&2; exit 1; }
if [ -n "$FILES_TAR" ]; then
  [ -f "$FILES_TAR" ] || { echo "Arquivo não encontrado: $FILES_TAR" >&2; exit 1; }
  tar -tzf "$FILES_TAR" > /dev/null || { echo "Pacote de arquivos corrompido: $FILES_TAR" >&2; exit 1; }
fi

DB_USER="${POSTGRES_USER:-postgres}"
TMP_DB="gestao_ti_verify_$(date +%Y%m%d%H%M%S)"
PSQL="docker compose exec -T postgres psql -U $DB_USER -v ON_ERROR_STOP=1 -q -t -A"
WORK="$(mktemp -d)"

cleanup() {
  $PSQL -d postgres -c "DROP DATABASE IF EXISTS $TMP_DB" > /dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> Criando banco temporário $TMP_DB"
$PSQL -d postgres -c "CREATE DATABASE $TMP_DB" > /dev/null

echo "==> Restaurando o backup nele"
gunzip -c "$FILE" | $PSQL -d "$TMP_DB" --single-transaction > /dev/null

TABLES="$($PSQL -d "$TMP_DB" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" | tr -d '\r')"
USERS="$($PSQL -d "$TMP_DB" -c "SELECT count(*) FROM user_accounts" | tr -d '\r')"
REV="$($PSQL -d "$TMP_DB" -c "SELECT version_num FROM alembic_version" | tr -d '\r')"
[ "$TABLES" -gt 0 ] || { echo "!! O backup restaurou, mas sem nenhuma tabela." >&2; exit 1; }

# cadeia da auditoria (ADR-023), se o backup é de uma versão que já a tem
CHAIN="$($PSQL -d "$TMP_DB" -c "SELECT CASE WHEN to_regprocedure('public.audit_verify()') IS NULL THEN 'sem cadeia'
  ELSE coalesce((SELECT string_agg(chain_category || ': ' || problem, '; ') FROM audit_verify() WHERE problem IS NOT NULL), 'íntegra') END" | tr -d '\r')"
case "$CHAIN" in
  íntegra|"sem cadeia") ;;
  *) echo "!! A cadeia da auditoria do backup não confere: $CHAIN" >&2; exit 1 ;;
esac

FILES_MSG=""
if [ -n "$FILES_TAR" ]; then
  $PSQL -d "$TMP_DB" -c "SELECT file_path FROM attachments" | tr -d '\r' | sed '/^$/d' | sort -u > "$WORK/no-banco"
  tar -tzf "$FILES_TAR" | sed -n 's#^data/attachments/##p' | sed '/^$/d;/\/$/d' | sort -u > "$WORK/no-pacote"
  MISSING="$(comm -23 "$WORK/no-banco" "$WORK/no-pacote" | wc -l | tr -d ' ')"
  IN_DB="$(wc -l < "$WORK/no-banco" | tr -d ' ')"
  if [ "$MISSING" -gt 0 ]; then
    echo "!! $MISSING de $IN_DB anexo(s) registrados no banco não estão no pacote de arquivos, por exemplo:" >&2
    comm -23 "$WORK/no-banco" "$WORK/no-pacote" | head -5 >&2
    exit 1
  fi
  FILES_MSG=", $IN_DB anexo(s) no banco e todos no pacote ($(wc -l < "$WORK/no-pacote" | tr -d ' ') arquivo(s) de anexos)"
fi

echo "==> OK: $TABLES tabelas, $USERS usuários, migration $REV, auditoria $CHAIN$FILES_MSG"
echo "    (o banco temporário é removido ao final)"
