# =============================================================================
# Backend — Plataforma de Gestão de TI
# Multi-stage build: dependencies + runtime
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- Stage: dependencies ---
FROM base AS deps

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# --- Stage: runtime ---
FROM base AS runtime

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# Criar diretório de anexos
RUN mkdir -p /data/attachments

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
