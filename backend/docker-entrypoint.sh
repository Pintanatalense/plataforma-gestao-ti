#!/bin/sh
set -e

# No Compose as migrations rodam no serviço db-init, com o papel dono (ADR-022): o backend usa o papel da
# aplicação, que não tem DDL, e chega aqui com RUN_MIGRATIONS=false.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "==> Aguardando banco de dados e executando migrações Alembic..."
  alembic upgrade head
fi

echo "==> Sincronizando dados iniciais (Seed)..."
python -m app.seed

echo "==> Iniciando aplicação..."
exec "$@"
