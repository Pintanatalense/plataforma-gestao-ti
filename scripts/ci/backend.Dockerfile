# Ambiente do backend para o CI local (scripts/ci-local.sh): mesmo Python do CI e da imagem de produção,
# com o uv na mesma versão do backend/Dockerfile. O código NÃO entra na imagem: é montado só leitura.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_CACHE_DIR=/cache/uv \
    UV_LINK_MODE=copy \
    RUFF_CACHE_DIR=/tmp/ruff-cache
WORKDIR /src/backend
