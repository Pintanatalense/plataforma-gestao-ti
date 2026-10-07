# Acompanhamento do Projeto: Plataforma Modular de Gestão de TI

Documento vivo para acompanhar o desenvolvimento. Atualize os checkboxes e o log ao concluir cada item.

**Legenda:** ✅ Concluído · 🟡 Em andamento · ⚪ Não iniciado

## Status Geral

**Fase atual:** Fase 3 — Service Desk (⚪)

| Módulo | Backend | Frontend | Testes |
|--------|---------|----------|--------|
| MOD-01 Core | ✅ | ✅ (layout, auth, interceptor) | ✅ |
| MOD-02 Organização | ✅ | ✅ | ✅ |
| MOD-03 Identidade | ✅ | ✅ | ✅ |
| MOD-04 Service Desk | ⚪ | ⚪ | ⚪ |
| MOD-05 Ativos | ⚪ | ⚪ | ⚪ |
| MOD-06 Movimentações | ⚪ | ⚪ | ⚪ |
| MOD-07 Estoque | ⚪ | ⚪ | ⚪ |
| MOD-08 Inventário | ⚪ | ⚪ | ⚪ |
| MOD-09 Contas/Acessos | ⚪ | ⚪ | ⚪ |
| MOD-10 Anexos | ⚪ | ⚪ | ⚪ |
| MOD-11 Notificações | ⚪ | ⚪ | ⚪ |
| MOD-12 Auditoria | ⚪ | ⚪ | ⚪ |

> MOD-04 a MOD-12 existem apenas como pastas com `__init__.py` vazio.

---

## Fase 1: Fundação e Setup ✅

- [x] Arquitetura definida (monólito modular FastAPI + Angular + PostgreSQL) — ADRs 001–005
- [x] Docker Compose, Nginx, Makefile, `.env.example`
- [x] Core (MOD-01): config, database, exceções, eventos, paginação, segurança (JWT/bcrypt), soft delete, timestamps
- [x] Alembic configurado + migração inicial (organização e identidade)
- [x] Seed (empresa, matriz, permissões, perfil Administrador, usuário admin)
- [x] Frontend: Angular + Material, shell/sidebar/header, login, interceptor JWT

## Fase 2: Organização e Identidade ✅

**Backend**
- [x] MOD-02: CRUD de empresa, unidades, setores, colaboradores
- [x] MOD-03: login JWT, `/me`, CRUD de usuários e perfis, RBAC por permissão
- [x] Corrigir `NotFoundException` chamada com argumentos errados (retorna 500 em vez de 404)
- [x] Falta de permissão deve retornar 403 (hoje retorna 401)
- [x] Endpoint `GET /identity/permissions` (necessário para a tela de perfis)
- [x] Endpoint para o próprio usuário trocar senha (`must_change_password`)
- [x] Testes de integração de MOD-02 e MOD-03
- [x] Setup inicial e publicação no GitHub

**Frontend**
- [x] Corrigir `authGuard` (desloga o usuário ao recarregar a página)
- [x] Ajustar menu lateral para rotas existentes
- [x] Telas CRUD: unidades, setores, colaboradores
- [x] Telas CRUD: usuários e perfis (com atribuição de permissões)
- [x] Fluxo de troca de senha obrigatória no primeiro login
- [x] Tela de setup inicial e proteções via guards

## Fase 3: Service Desk (MOD-04) ⚪
- [ ] Documentação do módulo (`docs/modules/service-desk`)
- [ ] Models, migração, repository, services, router
- [ ] Interações públicas e internas (DEC-012)
- [ ] Testes
- [ ] Frontend: abertura de chamado (colaborador) e painel de atendimento (técnico)

## Fase 4: Gestão Patrimonial (MOD-05, MOD-06) ⚪
- [ ] Ativos com specs em JSONB (ADR-005)
- [ ] Movimentações: entrega, devolução, transferência, baixa
- [ ] Associação chamado ↔ ativo (DEC-006)
- [ ] Testes e frontend

## Fase 5: Estoque e Inventário (MOD-07, MOD-08) ⚪
- [ ] Estoque de insumos por unidade (sem compras — DEC-009)
- [ ] Inventário periódico (abertura, conferência, fechamento)
- [ ] Testes e frontend

## Fase 6: Módulos Transversais (MOD-09 a MOD-12) ⚪
- [ ] Contas e acessos por colaborador (sem senhas — DEC-008)
- [ ] Anexos em disco, fora do banco (ADR-003)
- [ ] Notificações locais em tempo real (DEC-011)
- [ ] Auditoria via barramento de eventos
- [ ] Testes e frontend

## Fase 7: Estabilização e MVP ⚪
- [ ] Revisão de UX/responsividade
- [ ] Testes E2E
- [ ] Documentação de usuário
- [ ] Homologação com os perfis Colaborador, Gestor, Técnico e Admin

---

## Log de Atualizações

- **05/10/2026:** Roadmap criado.
- **05/10/2026:** Roadmap corrigido após análise do código. A versão inicial marcava a "estrutura base" de MOD-04 a MOD-12 como concluída, mas essas pastas estão vazias. Bugs identificados foram adicionados à Fase 2.
- **05/10/2026:** Backend da Fase 2 estabilizado, testes de integração implementados, falhas de segurança e regras de negócio corrigidas. Iniciando implementação Frontend.
- **05/10/2026:** Frontend da Fase 2 concluído: AuthGuard corrigido, fluxo de troca de senha inicial implementado, telas de CRUD (Unidades, Setores, Colaboradores, Usuários, Perfis) integradas aos serviços do backend. Fase 2 totalmente finalizada.
- **07/10/2026:** Removido o admin padrão (hardcoded) do seed. Implementada tela e backend de Setup Inicial para o primeiro uso do sistema. Repositório publicado privadamente no GitHub, juntamente com `.gitattributes`, LICENSE e workflow de CI com GitHub Actions. Fase 2 100% encerrada.
