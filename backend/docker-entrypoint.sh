#!/bin/sh
set -e

echo "==> Aguardando banco de dados e executando migrações Alembic..."
alembic upgrade head

echo "==> Sincronizando dados iniciais (Seed)..."
python -m app.seed || true

echo "==> Iniciando aplicação..."
exec "$@"
