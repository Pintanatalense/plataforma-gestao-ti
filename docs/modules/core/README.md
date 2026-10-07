# MOD-01 — Core

## Objetivo

Fornecer infraestrutura compartilhada e utilitários fundamentais para todos os módulos do sistema.

## Responsabilidades

- Configurações da aplicação
- Mixins de modelo (timestamps, soft delete)
- Hierarquia de exceções
- Barramento de eventos interno
- Paginação padronizada
- Utilitários de segurança (hash, JWT)
- Dependencies comuns para FastAPI

## Entidades Pertencentes

Nenhuma entidade de banco — o Core fornece apenas mixins e infraestrutura.

## Regras de Negócio

- Todos os timestamps devem estar em UTC
- Exclusão lógica deve ser preferida sobre exclusão física para entidades com histórico
- Eventos emitidos devem ser processados mesmo que um handler falhe

## Interface Pública

### Mixins (para uso direto em models)

```python
from app.core.timestamps import TimestampMixin
from app.core.soft_delete import SoftDeleteMixin
```

### Exceções

```python
from app.core.exceptions import (
    AppException,
    NotFoundException,
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
    ValidationException,
    BusinessRuleException,
    StateTransitionException,
)
```

### Eventos

```python
from app.core.events import event_bus, Event
```

### Paginação

```python
from app.core.pagination import PaginatedResponse, PaginationParams, get_pagination_params
```

### Segurança

```python
from app.core.security import hash_password, verify_password, create_access_token, decode_access_token
```

### Dependencies

```python
from app.core.dependencies import get_current_user_id, get_current_user_ip
```

## Dependências

Nenhuma — o Core não depende de nenhum outro módulo.

## Eventos Produzidos

Nenhum — o Core fornece o barramento, mas não emite eventos.
