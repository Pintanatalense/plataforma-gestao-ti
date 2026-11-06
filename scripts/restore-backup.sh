#!/bin/sh
# Restaura um backup do banco (.sql.gz) e, opcionalmente, os arquivos (anexos e logomarca).
#
# Uso: scripts/restore-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz [/caminho/arquivos_AAAAMMDD_HHMMSS.tar.gz]
#      make restore FILE=/caminho/backup.sql.gz [FILES=/caminho/arquivos.tar.gz]
#
# Ordem (nada é alterado antes do passo 3):
#  1. valida os arquivos (gzip/tar íntegros; o tar só pode conter data/attachments e app/static);
#  2. grava e confere cópias de segurança no diretório atual: pre-restore-<data>.sql.gz (banco) e, se for
#     restaurar arquivos, pre-restore-arquivos-<data>.tar.gz (anexos e logo ATUAIS);
#  3. garante os papéis de banco (o dump cita o papel dono e o da Evolution; ADR-022) e para o backend E o worker
#     (o worker continuaria gravando durante a restauração);
#  4. restaura o banco em uma única transação (aborta no primeiro erro, sem aplicar nada) e roda o db-init
#     (papéis, dono das tabelas e permissões da aplicação; migrations, se o backup for de uma versão anterior);
#  5. sobe o backend e, se informado o tar, extrai primeiro numa pasta temporária e SÓ DEPOIS troca o conteúdo
#     dos volumes (se a extração falhar, os arquivos atuais continuam intactos);
#  6. sobe o worker.
# Se algo falhar depois do passo 4, o script PARA com o worker desligado e diz o que fazer.
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
  # só pode conter os dois diretórios do sistema, sem ".." (um tar adulterado não escreve fora deles)
  if tar -tz < "$FILES_TAR" | grep -qvE '^(data/attachments|app/static)(/|$)' \
     || tar -tz < "$FILES_TAR" | grep -qE '(^|/)\.\.(/|$)'; then
    echo "!! O tar contém caminhos fora de data/attachments e app/static (ou com ..): recusado." >&2
    exit 1
  fi
fi

DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-gestao_ti}"
STAMP="$(date +%Y%m%d_%H%M%S)"
PRE_SQL="pre-restore-$STAMP.sql.gz"
PRE_FILES="pre-restore-arquivos-$STAMP.tar.gz"

abort_safe() { rm -f "$PRE_SQL" "$PRE_FILES"; echo "!! $*; nada foi alterado." >&2; exit 1; }

echo "==> Cópia de segurança do banco: $PRE_SQL"
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$PRE_SQL"
# gzip -t aceita até um arquivo vazio: confira também a marca final do pg_dump antes de mexer em qualquer coisa
gunzip -c "$PRE_SQL" | tail -n 5 | grep -q "dump complete" || abort_safe "O dump de segurança falhou ou está incompleto"

if [ -n "$FILES_TAR" ]; then
  echo "==> Cópia de segurança dos arquivos atuais: $PRE_FILES"
  docker compose exec -T backend tar czf - -C / data/attachments app/static > "$PRE_FILES" \
    || abort_safe "Não consegui copiar os arquivos atuais (o backend está no ar?)"
  tar -tz < "$PRE_FILES" > /dev/null || abort_safe "A cópia de segurança dos arquivos está corrompida"
fi

echo "==> Papéis de banco (o dump referencia o papel dono e o da Evolution)"
docker compose run --rm --no-deps db-init python -m app.db_roles \
  || abort_safe "Não consegui criar/atualizar os papéis de banco (veja a mensagem acima; o .env tem DB_*_PASSWORD?)"

echo "==> Parando o backend e o worker"
docker compose stop worker backend

echo "==> Restaurando o banco (transação única, ON_ERROR_STOP)"
if gunzip -c "$FILE" | docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --single-transaction -q; then
  echo "==> Banco restaurado"
else
  echo "!! Falha na restauração: nada foi aplicado. Cópia de segurança: $PRE_SQL" >&2
  docker compose start backend worker
  exit 1
fi

# Um backup antigo (de antes dos papéis separados, ADR-022) traz as tabelas do superusuário: o db-init devolve a
# posse ao papel dono, reaplica as permissões da aplicação e leva o banco à última migration.
echo "==> Papéis, permissões e migrations (db-init)"
if ! docker compose run --rm --no-deps db-init; then
  {
    echo "!! O BANCO foi restaurado, mas o db-init falhou. Backend e worker NÃO foram iniciados."
    echo "   Veja a mensagem acima, corrija e rode:  docker compose run --rm db-init && docker compose start backend worker"
    echo "   Banco de antes da restauração: $PRE_SQL"
  } >&2
  exit 1
fi

echo "==> Iniciando o backend"
docker compose start backend

if [ -n "$FILES_TAR" ]; then
  echo "==> Repondo anexos e logomarca (extrai numa pasta temporária; só então troca)"
  if ! {
    docker compose exec -T backend sh -c 'rm -rf /tmp/restore-files && mkdir -p /tmp/restore-files' &&
    docker compose exec -T backend tar xz -C /tmp/restore-files < "$FILES_TAR" &&
    docker compose exec -T backend sh -c '
      set -e
      find /data/attachments /app/static -mindepth 1 -delete
      if [ -d /tmp/restore-files/data/attachments ]; then cp -a /tmp/restore-files/data/attachments/. /data/attachments/; fi
      if [ -d /tmp/restore-files/app/static ]; then cp -a /tmp/restore-files/app/static/. /app/static/; fi
      rm -rf /tmp/restore-files
    '
  }; then
    {
      echo "!! O BANCO foi restaurado, mas a reposição dos ARQUIVOS falhou. O worker NÃO foi iniciado."
      echo "   Arquivos de antes da restauração: $PRE_FILES"
      echo "   Banco de antes da restauração:    $PRE_SQL"
      echo "   Corrija a causa, repita este comando (ou extraia $PRE_FILES com tar -xz -C / dentro do backend)"
      echo "   e depois inicie o worker:  docker compose start worker"
    } >&2
    exit 1
  fi
else
  echo "   (anexos e logomarca NÃO foram restaurados: informe o segundo arquivo, arquivos_*.tar.gz)"
fi

echo "==> Iniciando o worker"
docker compose start worker
echo "==> Concluído"
