# ADR-004 — Monólito Modular

**Status:** Aceito  
**Data:** 2026-10-02  

## Contexto

O sistema precisa de uma arquitetura que permita manutenção modular sem a complexidade de microsserviços.

## Decisão

O sistema será um monólito modular com 12 módulos e fronteiras internas rígidas. A comunicação entre módulos ocorre via interfaces públicas (services + schemas) e barramento de eventos in-process.

### Regras de isolamento

1. Um módulo NÃO importa models de outro módulo
2. Um módulo NÃO acessa repositórios de outro módulo
3. Um módulo NÃO executa queries em tabelas de outro módulo
4. Comunicação entre módulos via `services.py` e `schemas.py` públicos
5. Eventos desacoplados via `core.events.EventBus`

## Justificativa

- Menor complexidade que microsserviços (sem rede, sem service discovery)
- Facilita desenvolvimento assistido por IA com contexto reduzido
- Permite evolução para microsserviços no futuro se necessário
- Cada módulo pode ser testado independentemente

## Consequências

- Requer disciplina para manter fronteiras (linting de imports recomendado)
- Toda a aplicação compartilha o mesmo processo e banco
- Necessidade de documentação de interface pública por módulo
