# ADR-001 — Instância por Empresa (Single Tenant)

**Status:** Aceito  
**Data:** 2026-10-02  

## Contexto

O sistema precisa decidir se atenderá múltiplas empresas em uma única instalação (multi-tenant) ou se cada empresa terá sua própria instância.

## Decisão

Uma instalação do sistema atenderá apenas uma empresa.

## Justificativa

- Simplifica o modelo de dados (sem tenant_id em todas as tabelas)
- Reduz complexidade de permissões e isolamento de dados
- Adequado ao cenário atual de uso por uma única empresa
- Permite migração futura para multi-tenant se necessário

## Consequências

- Cada empresa precisa de deploy independente
- Não há compartilhamento de infraestrutura entre empresas
