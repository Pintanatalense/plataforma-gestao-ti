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

# Criar diretório de anexos e permissões do entrypoint
RUN mkdir -p /data/attachments && chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
