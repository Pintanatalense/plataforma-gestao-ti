# Plataforma Modular de Gestão de TI

Sistema modular para gestão de TI corporativa, incluindo service desk, gestão de ativos, estoque, inventário e controle de acessos.

## Stack Tecnológico

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12 / FastAPI |
| ORM | SQLAlchemy 2.0 + Alembic |
| Banco | PostgreSQL 16 |
| Frontend | Angular 18 |
| Containerização | Docker + Docker Compose |
| Proxy | Nginx |

## Pré-requisitos

- Docker e Docker Compose
- Node.js 20+ (para desenvolvimento frontend)
- Python 3.12+ (para desenvolvimento backend local)

## Início Rápido

```bash
# 1. Clonar e configurar
cp .env.example .env
# Editar .env com suas configurações

# 2. Subir os containers
docker-compose up -d

# 3. Executar migrações
make migrate

# 4. Popular dados iniciais
make seed

# 5. Acessar
# API: http://localhost:8000/api/v1/docs
# App: http://localhost
```

## Estrutura do Projeto

```
├── backend/          # API FastAPI (monólito modular)
│   ├── app/
│   │   ├── core/              # MOD-01 — Infraestrutura compartilhada
│   │   ├── organization/      # MOD-02 — Empresa, unidades, setores
│   │   ├── identity/          # MOD-03 — Autenticação e permissões
│   │   ├── service_desk/      # MOD-04 — Chamados
│   │   ├── assets/            # MOD-05 — Equipamentos
│   │   ├── movements/         # MOD-06 — Movimentações
│   │   ├── stock/             # MOD-07 — Estoque de insumos
│   │   ├── inventory_audit/   # MOD-08 — Inventário periódico
│   │   ├── access_control/    # MOD-09 — Contas e acessos
│   │   ├── attachments/       # MOD-10 — Anexos
│   │   ├── notifications/     # MOD-11 — Notificações
│   │   └── audit/             # MOD-12 — Auditoria
│   └── tests/
├── frontend/         # Angular SPA
├── nginx/            # Proxy reverso
├── docs/             # Documentação por módulo
└── docker-compose.yml
```

## Comandos Úteis

```bash
make up          # Iniciar containers
make down        # Parar containers
make logs        # Ver logs
make test        # Executar testes unitários rápidos (SQLite in-memory)
make test-pg     # Executar testes no PostgreSQL descartável real (porta 55432)
make test-db-up  # Iniciar PostgreSQL de testes (porta 55432)
make seed-test   # Popular base de homologação/QA com cenários de estresse
make migrate     # Rodar migrações
make lint        # Verificar código
make backup      # Backup do banco
```

## Documentação

- [Visão Geral do Sistema](docs/system-overview.md)
- [Arquitetura](docs/architecture/overview.md)
- [Base de Testes e Homologação (QA)](docs/11-base-de-testes-e-homologacao.md)
- [Gestão do Ambiente Demonstrativo](docs/07-gestao-do-ambiente-demonstrativo.md)
- [Decisões (ADRs)](docs/decisions/)
- [Módulos](docs/modules/)

## Licença

Proprietário — Uso interno.
