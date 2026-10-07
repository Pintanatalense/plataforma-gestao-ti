# Arquitetura — Visão Geral

## Tipo de Arquitetura

**Monólito Modular** — uma única aplicação com fronteiras internas rígidas entre módulos.

Referência: [ADR-004 — Monólito Modular](../decisions/ADR-004-modular-monolith.md)

## Componentes

```
┌─────────────────────────────────────────────────────────┐
│                     Nginx (porta 80)                     │
│            Proxy Reverso + Static Files                  │
│     /api/* → Backend    /* → Frontend    /ws/* → WS      │
└────────────────────┬────────────────────────────────────┘
                     │
    ┌────────────────┴─────────────────┐
    │        FastAPI (porta 8000)       │
    │        Monólito Modular           │
    │                                   │
    │  ┌─────────────────────────────┐  │
    │  │     MOD-01 Core             │  │
    │  │  (timestamps, events, etc.) │  │
    │  └─────────────────────────────┘  │
    │                                   │
    │  ┌────────┐ ┌────────┐ ┌───────┐  │
    │  │ Org    │ │ Auth   │ │ Audit │  │
    │  │ MOD-02 │ │ MOD-03 │ │MOD-12 │  │
    │  └────┬───┘ └───┬────┘ └───────┘  │
    │       │         │                 │
    │  ┌────┴─────────┴───────┐         │
    │  │   Service Desk       │         │
    │  │   MOD-04             │         │
    │  └──────┬───────────────┘         │
    │         │                         │
    │  ┌──────┴──────┐  ┌───────────┐   │
    │  │ Assets      │  │ Stock     │   │
    │  │ MOD-05      │  │ MOD-07    │   │
    │  └──────┬──────┘  └───────────┘   │
    │         │                         │
    │  ┌──────┴──────┐                  │
    │  │ Movements   │                  │
    │  │ MOD-06      │                  │
    │  └─────────────┘                  │
    │                                   │
    └────────────────┬─────────────────┘
                     │
    ┌────────────────┴─────────────────┐
    │      PostgreSQL 16 (porta 5432)   │
    └───────────────────────────────────┘
```

## Padrão Interno dos Módulos

Cada módulo segue a mesma estrutura:

```
module/
├── __init__.py         # Docstring do módulo
├── models.py           # Entidades SQLAlchemy (INTERNO)
├── schemas.py          # DTOs Pydantic (PÚBLICO)
├── services.py         # Lógica de negócio (PÚBLICO)
├── repository.py       # Queries ao banco (INTERNO)
├── router.py           # Endpoints FastAPI (PÚBLICO via HTTP)
└── events.py           # Eventos emitidos (PÚBLICO)
```

### Visibilidade

| Arquivo | Acessível por outros módulos? |
|---------|------------------------------|
| `models.py` | ❌ NÃO |
| `repository.py` | ❌ NÃO |
| `schemas.py` | ✅ SIM — DTOs de entrada/saída |
| `services.py` | ✅ SIM — interface de negócio |
| `events.py` | ✅ SIM — para escutar eventos |
| `router.py` | ❌ NÃO — montado pelo main.py |

## Comunicação entre Módulos

### Síncrona (chamada direta)

```python
# ✅ Service Desk chama Assets para obter dados
from app.assets.services import AssetService
from app.assets.schemas import AssetSummaryOut

asset = await asset_service.get_by_id(asset_id)
```

### Assíncrona (eventos)

```python
# ✅ Movements emite evento → Notifications escuta
from app.core.events import event_bus, Event

# Em movements/services.py
await event_bus.emit(Event(
    event_type="asset.delivered",
    entity_type="asset_movement",
    entity_id=movement.id,
    data={"asset_id": str(asset.id), "to": employee.name},
))

# Em notifications/events.py
@event_bus.on("asset.delivered")
async def notify_delivery(event: Event):
    ...
```

## Stack de Dados

- **PostgreSQL 16** — banco principal
- **JSONB** — specs dinâmicas de ativos, snapshots de contexto
- **Full Text Search** — busca de categorias (trigram)
- **Alembic** — migrações versionadas

## Segurança

- **bcrypt** — hashing de senhas
- **JWT (HS256)** — autenticação stateless, expiração 8h
- **RBAC** — permissões granulares (module.resource.action)
- **Nginx** — headers de segurança (X-Frame-Options, X-Content-Type-Options, etc.)
