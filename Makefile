# =============================================================================
# Makefile — Plataforma de Gestão de TI
#
# Comandos disponíveis:
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
#   make backup      - Gera backup do banco + anexos
#   make restore     - Restaura backup .sql.gz com a API parada (FILE="arquivo.sql.gz")
# =============================================================================

.PHONY: up down logs migrate migration seed test lint shell db-shell backup restore

# --- Docker ---
up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

rebuild:
	docker-compose up -d --build

# --- Banco de Dados ---
migrate:
	docker-compose exec backend alembic upgrade head

migration:
	docker-compose exec backend alembic revision --autogenerate -m "$(MSG)"

rollback:
	docker-compose exec backend alembic downgrade -1

db-shell:
	docker-compose exec postgres psql -U postgres -d gestao_ti

# --- Seed ---
seed:
	docker-compose exec backend python -m app.seed

seed-demo:
	docker-compose exec backend python -m app.seed_demo --no-reset

seed-reset:
	docker-compose exec backend python -m app.seed_demo --reset

# --- Testes ---
test:
	cd backend && python -m pytest -v --tb=short

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
	docker-compose exec backend /bin/bash

# --- Backup ---
backup:
	@echo "Gerando backup..."
	@mkdir -p backups
	docker-compose exec postgres pg_dump -U postgres gestao_ti > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Backup concluído."

restore:
	@scripts/restore-backup.sh "$(FILE)"

# --- Frontend ---
fe-install:
	cd frontend && npm install

fe-dev:
	cd frontend && npm start

fe-build:
	cd frontend && npm run build
