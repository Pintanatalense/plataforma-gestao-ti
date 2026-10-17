#!/bin/sh
set -e

echo "==> Aguardando banco de dados e executando migrações Alembic..."
alembic upgrade head

echo "==> Sincronizando dados iniciais (Seed)..."
python -m app.seed

echo "==> Iniciando aplicação..."
exec "$@"
