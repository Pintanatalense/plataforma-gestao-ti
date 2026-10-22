# ADR-002 — Autenticação Própria

**Status:** Aceito  
**Data:** 2026-10-02  

## Contexto

Necessidade de definir o mecanismo de autenticação para o MVP.

## Decisão

A primeira versão utilizará autenticação própria com usuário e senha. Senhas armazenadas via hash bcrypt. Tokens JWT com expiração de 8 horas. Recuperação de senha via reset manual pelo administrador com senha temporária (troca obrigatória no primeiro login).

## Justificativa

- Elimina dependência de infraestrutura externa (AD/LDAP)
- Simplifica o deploy inicial
- bcrypt é padrão da indústria para hashing de senhas
- JWT permite sessões stateless

## Consequências

- Integração com AD/LDAP fica planejada para versão futura
- Administrador precisa gerenciar resets de senha manualmente

## Atualização (2026-10-22)

Revogação de sessões e limite de login: ver [ADR-016](ADR-016-sessao-e-revogacao.md). A recuperação por e-mail será tratada no ADR-018.
