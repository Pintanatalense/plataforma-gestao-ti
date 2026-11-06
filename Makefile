# =============================================================================
# Makefile — Plataforma de Gestão de TI
#
# Comandos disponíveis:
#   make install     - Instalação guiada (gera o .env, sobe e espera ficar pronto)
#   make up          - Inicia todos os containers
#   make down        - Para todos os containers
#   make logs        - Mostra logs em tempo real
#   make migrate     - Executa migrações pendentes
#   make migration   - Gera nova migração (MSG="descrição")
#   make seed        - Popula banco com dados iniciais
#   make test        - Executa testes do backend
#   make lint        - Executa linter no backend
#   make shell       - Abre shell no container do backend
#   make db-shell    - Abre psql no container do banco
#   make backup        - Backup do banco (.sql.gz) + anexos e logomarca (.tar.gz) em ./backups
#   make restore       - Restaura (FILE="banco.sql.gz" [FILES="arquivos.tar.gz"]) com backend e worker parados
#   make verify-backup - Prova que um backup restaura, num banco temporário (FILE="banco.sql.gz" [FILES="arquivos.tar.gz"])
#   make backup-secrets - Cópia cifrada do .env (senhas e APP_ENCRYPTION_KEY), à parte dos backups
#   make ci-local      - Mesmas verificações do CI, em contêineres, só nas áreas alteradas (antes de publicar)
#   make ci-local-full - Todas as verificações do CI (como a execução semanal)
# =============================================================================

install:
	@scripts/install.sh

.PHONY: install up down logs migrate migration seed test lint shell db-shell backup restore verify-backup backup-secrets ci-local ci-local-full

# --- Docker ---
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose up -d --build

# --- Banco de Dados ---
# migrations rodam no db-init, com o papel dono (ADR-022): o backend não tem permissão de alterar a estrutura
migrate:
	docker compose run --rm db-init

migration:
	docker compose exec backend alembic revision --autogenerate -m "$(MSG)"

rollback:
	docker compose run --rm db-init alembic downgrade -1

db-shell:
	docker compose exec postgres psql -U postgres -d gestao_ti

# --- Seed ---
seed:
	docker compose exec backend python -m app.seed

seed-demo:
	docker compose exec backend python -m app.seed_demo --no-reset

seed-reset:
	docker compose exec backend python -m app.seed_demo --reset

seed-test:
	docker compose exec backend python -m app.seed_test

seed-test-reset:
	docker compose exec backend python -m app.seed_test --reset

# --- Base de Testes e Homologação (Porta 55432 / gti_test) ---
test-db-up:
	docker compose -f docker-compose.test.yml up -d

test-db-down:
	docker compose -f docker-compose.test.yml down -v

test-db-reset:
	docker compose -f docker-compose.test.yml down -v
	docker compose -f docker-compose.test.yml up -d

# --- Testes ---
test:
	cd backend && python -m pytest -v --tb=short

test-pg:
	cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test USE_PG_TEST=true python -m pytest -v --tb=short

test-cov:
	cd backend && python -m pytest --cov=app --cov-report=term-missing

# --- Linting ---
lint:
	cd backend && ruff check .

lint-fix:
	cd backend && ruff check --fix .

format:
	cd backend && ruff format .

# --- Shell ---
shell:
	docker compose exec backend /bin/bash

# --- Backup ---
backup:
	@scripts/backup.sh

restore:
	@scripts/restore-backup.sh "$(FILE)" "$(FILES)"

verify-backup:
	@scripts/verify-backup.sh "$(FILE)" "$(FILES)"

# cópia cifrada do .env (pede a senha), à parte dos backups
backup-secrets:
	@scripts/backup-secrets.sh

# --- Frontend ---
fe-install:
	cd frontend && npm install

fe-dev:
	cd frontend && npm start

fe-build:
	cd frontend && npm run build

# --- CI local (ver scripts/ci-local.sh; no Windows sem make: bash scripts/ci-local.sh) ---
ci-local:
	@scripts/ci-local.sh

ci-local-full:
	@scripts/ci-local.sh --all
