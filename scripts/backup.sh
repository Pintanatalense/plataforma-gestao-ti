#!/bin/sh
# Backup completo: banco de dados + arquivos (anexos e logomarca).
#
# Uso:   scripts/backup.sh            (ou: make backup)
# Saída: backups/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz   (banco; restaurável por scripts/restore-backup.sh)
#        backups/arquivos_AAAAMMDD_HHMMSS.tar.gz           (volumes de anexos e de logo)
#
# - o banco sai com --clean --if-exists, no mesmo formato dos backups gerados pela tela do sistema;
# - cada arquivo é verificado (gzip íntegro; dump termina com a marca "dump complete"; tar legível);
# - NÃO inclui o .env: guarde-o à parte (APP_ENCRYPTION_KEY é necessária para ler as credenciais cifradas).
# Variáveis opcionais: BACKUP_DIR (padrão ./backups), POSTGRES_USER, POSTGRES_DB.
set -eu
# Git Bash (Windows) reescreve argumentos que começam com / (ex.: tar -C /); no Linux/macOS não tem efeito.
export MSYS_NO_PATHCONV=1

DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-gestao_ti}"
DEST="${BACKUP_DIR:-backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
SQL="$DEST/backup_gestao_ti_$STAMP.sql.gz"
FILES="$DEST/arquivos_$STAMP.tar.gz"

fail() { echo "!! $*" >&2; rm -f "$SQL" "$FILES"; exit 1; }

mkdir -p "$DEST"

echo "==> Banco de dados -> $SQL"
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$SQL" \
  || fail "pg_dump falhou (o serviço postgres está no ar? rode: docker compose ps)"
gzip -t "$SQL" || fail "arquivo .gz do banco corrompido"
gunzip -c "$SQL" | tail -n 5 | grep -q "dump complete" || fail "o dump do banco está incompleto (sem a marca final)"

echo "==> Anexos e logomarca -> $FILES"
docker compose exec -T backend tar czf - -C / data/attachments app/static > "$FILES" \
  || fail "não consegui empacotar os volumes de arquivos (o serviço backend está no ar?)"
tar -tz < "$FILES" > /dev/null || fail "arquivo .tar.gz dos volumes corrompido"

echo "==> Concluído"
for f in "$SQL" "$FILES"; do
  printf '    %s  %s bytes\n' "$f" "$(wc -c < "$f" | tr -d ' ')"
done
echo "    Lembrete: copie também o .env (APP_ENCRYPTION_KEY) para um local seguro, fora do servidor."
