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

# Dependências exatas do uv.lock (build reproduzível: sem o lock, o pip pegava a versão mais nova de cada
# pacote e uma release sem wheel quebrava o build).
RUN pip install --no-cache-dir uv --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.lock \
    && pip install --no-cache-dir -r requirements.lock --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org

# --- Stage: runtime ---
FROM base AS runtime

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# Cliente do PostgreSQL 16 (mesma versão major do servidor do compose). O cliente do Debian é mais
# novo e gera dumps com parâmetros (ex.: transaction_timeout) que o servidor 16 não restaura.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# Criar diretórios de armazenamento persistente e permissões do entrypoint
# Usuário não-root; diretórios de dados pertencem a ele (volumes nomeados herdam o dono)
RUN useradd --system --uid 1000 --home-dir /app app \
    && mkdir -p /data/attachments /data/backups /app/static \
    && chown -R app:app /data /app/static \
    && chmod +x docker-entrypoint.sh
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
