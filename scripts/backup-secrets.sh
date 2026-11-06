#!/bin/sh
# Cópia CIFRADA do .env (senhas do banco, SECRET_KEY e APP_ENCRYPTION_KEY), guardada à parte dos backups (S10).
#
# Sem a APP_ENCRYPTION_KEY os segredos gravados no banco (SMTP, tokens de canais) não podem ser lidos depois de uma
# restauração; sem as senhas do .env o sistema não sobe. O backup do banco NÃO leva o .env, de propósito.
#
# Uso:   scripts/backup-secrets.sh [pasta-destino]          (padrão: ./backups-segredos; nunca dentro de ./backups)
#        a senha da cópia é pedida pelo openssl (duas vezes). Em automação: BACKUP_SECRETS_PASSPHRASE (12+ caracteres).
#        ENV_FILE=outro.env scripts/backup-secrets.sh      (padrão: .env)
# Saída: segredos_gestao_ti_AAAAMMDD_HHMMSS.env.enc  +  .sha256
#
# Restaurar (pede a mesma senha):
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in segredos_gestao_ti_....env.enc -out .env && chmod 600 .env
#
# Leve a cópia para FORA do servidor (cofre de senhas, outro equipamento). Guarde a senha em outro lugar: sem ela a
# cópia não abre.
set -eu

ENV_FILE="${ENV_FILE:-.env}"
DEST="${1:-${SECRETS_DIR:-backups-segredos}}"
STAMP="$(date +%Y%m%d_%H%M%S)"
CIPHER="-aes-256-cbc -pbkdf2 -iter 600000"

fail() { echo "!! $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || fail "Arquivo não encontrado: $ENV_FILE (rode na pasta do projeto)"
command -v openssl > /dev/null 2>&1 || fail "openssl não encontrado"
case "$DEST" in
  backups|backups/*|./backups|./backups/*) fail "Não guarde os segredos junto dos backups do banco: escolha outra pasta." ;;
esac
if [ -n "${BACKUP_SECRETS_PASSPHRASE:-}" ] && [ "${#BACKUP_SECRETS_PASSPHRASE}" -lt 12 ]; then
  fail "BACKUP_SECRETS_PASSPHRASE curta: use 12 caracteres ou mais"
fi

umask 077
mkdir -p "$DEST"
OUT="$DEST/segredos_gestao_ti_$STAMP.env.enc"

echo "==> Cifrando $ENV_FILE -> $OUT"
if [ -n "${BACKUP_SECRETS_PASSPHRASE:-}" ]; then
  # shellcheck disable=SC2086  # CIPHER são opções separadas de propósito
  openssl enc $CIPHER -salt -in "$ENV_FILE" -out "$OUT" -pass env:BACKUP_SECRETS_PASSPHRASE
  # confere que a cópia abre e é idêntica (sem gravar o texto em claro em lugar nenhum)
  # shellcheck disable=SC2086
  openssl enc -d $CIPHER -in "$OUT" -pass env:BACKUP_SECRETS_PASSPHRASE | cmp -s - "$ENV_FILE" \
    || { rm -f "$OUT"; fail "A cópia cifrada não confere com o original"; }
else
  # shellcheck disable=SC2086
  openssl enc $CIPHER -salt -in "$ENV_FILE" -out "$OUT"
  echo "==> Conferindo a cópia (digite a senha mais uma vez)"
  # shellcheck disable=SC2086
  openssl enc -d $CIPHER -in "$OUT" | cmp -s - "$ENV_FILE" \
    || { rm -f "$OUT"; fail "A cópia cifrada não confere com o original (senha diferente?)"; }
fi

digest="$(openssl dgst -sha256 -r "$OUT" | cut -d' ' -f1)"
printf '%s  %s\n' "$digest" "$(basename "$OUT")" > "$OUT.sha256"
echo "==> Concluído: $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, SHA-256 ${digest%"${digest#????????????????}"}...)"
echo "    Leve este arquivo para FORA do servidor e guarde a senha em outro lugar."
