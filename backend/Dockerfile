# =============================================================================
# Backend — Plataforma de Gestão de TI
# Multi-stage build: dependencies + runtime
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# --- Stage: dependencies ---
FROM base AS deps

RUN pip install --no-cache-dir hatchling --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org
COPY pyproject.toml ./
RUN pip install --no-cache-dir . --no-build-isolation --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org

# --- Stage: runtime ---
FROM base AS runtime

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# Instalar cliente do PostgreSQL para utilitários pg_dump e psql
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*

# Criar diretórios de armazenamento persistente e permissões do entrypoint
# Usuário não-root; diretórios de dados pertencem a ele (volumes nomeados herdam o dono)
RUN useradd --system --uid 1000 --home-dir /app app     && mkdir -p /data/attachments /data/backups /app/static     && chown -R app:app /data /app/static     && chmod +x docker-entrypoint.sh
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
