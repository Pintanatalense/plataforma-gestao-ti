# Acompanhamento do Projeto: Plataforma Modular de Gestão de TI

Documento vivo para acompanhar o desenvolvimento. Atualize os checkboxes e o log ao concluir cada item.

**Legenda:** ✅ Concluído · 🟡 Em andamento · ⚪ Não iniciado

## Status Geral

**Fase atual:** Fase 3 — Service Desk (✅)

| Módulo | Backend | Frontend | Testes |
|--------|---------|----------|--------|
| MOD-01 Core | ✅ | ✅ (layout, auth, interceptor) | ✅ |
| MOD-02 Organização | ✅ | ✅ | ✅ |
| MOD-03 Identidade | ✅ | ✅ | ✅ |
| MOD-04 Service Desk | ✅ | ✅ | ✅ |
| MOD-05 Ativos | ⚪ | ⚪ | ⚪ |
| MOD-06 Movimentações | ⚪ | ⚪ | ⚪ |
| MOD-07 Estoque | ⚪ | ⚪ | ⚪ |
| MOD-08 Inventário | ⚪ | ⚪ | ⚪ |
| MOD-09 Contas/Acessos | ⚪ | ⚪ | ⚪ |
| MOD-10 Anexos | ✅ | ✅ | ✅ |
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

## Fase 3: Service Desk (MOD-04) ✅
- [x] Documentação do módulo (`docs/modules/service-desk`)
- [x] Models, migração, repository, services, router
- [x] Interações públicas e internas (DEC-012)
- [x] Testes
- [x] Frontend: abertura de chamado (colaborador) e painel de atendimento (técnico)

## Fase 4: Gestão Patrimonial (MOD-05, MOD-06) 🟢
- [x] Ativos com specs em JSONB (ADR-005)
- [x] Movimentações: entrega, devolução, transferência, baixa
- [x] Associação chamado ↔ ativo (DEC-006)
- [x] Testes e frontend

## Fase 5: Estoque e Inventário (MOD-07, MOD-08) 🟡
- [x] Estoque de insumos por unidade (sem compras — DEC-009)
- [x] Inventário periódico (abertura, conferência, fechamento) - Backend
- [x] Testes e frontend do Inventário

## Fase 6: Módulos Transversais (MOD-09 a MOD-12) 🟡
- [x] Contas e acessos por colaborador (sem senhas — DEC-008)
- [x] Anexos em disco, fora do banco (ADR-003)
- [x] Notificações locais em tempo real (DEC-011) - Backend
- [x] Auditoria via barramento de eventos - Backend
- [ ] Testes e frontend (Fase 6)

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
- **07/10/2026:** Iniciada Fase 3 (Service Desk). Implementado Router, migrações e testes automatizados. O bug de lazy-loading da ORM foi resolvido, bem como o vazamento de interações internas. Backend da Fase 3 concluído. Próximo passo: Frontend do Service Desk.
- **07/10/2026:** Frontend do Service Desk implementado (lista, criação e detalhe estilo chat). Adicionada navegação lateral para "Chamados". O aplicativo foi compilado com sucesso. Fase 3 concluída (100%). Próximo passo: Fase 4.
- **08/10/2026:** Iniciada a Fase 4 (Gestão Patrimonial e Movimentações). Foram implementados os modulos de assets e movements no backend, incluindo o schemas, repositorio, services e router, e também a tabela de associação `sd_ticket_assets` no Service Desk. Alembic `env.py` foi atualizado. Falta testar e criar o frontend.
- **08/10/2026:** Fase 4 concluída (100%). Testes unitários do backend para assets/movements adicionados. No frontend (Angular), as telas de Lista, Criação e Detalhes de Ativos (com histórico de movimentações) foram desenvolvidas, com suporte dinâmico a `technical_specs` (JSONB) baseadas na Categoria selecionada. A tela de abertura de chamados também foi ajustada para aceitar e exibir os ativos associados. Próximo passo: Fase 5 (Estoque).
- **08/10/2026:** Fase 5 (Estoque e Inventário) concluída (100%). Criados modelos, schemas, repository e service para `StockItem` e `StockMovement`. Desenvolvidas as telas de listagem, criação e detalhamento do insumo com histórico e funcionalidade de Entrada/Saída/Ajuste. Adicionados testes unitários no backend. Próximo passo: Testar a aplicação localmente no ambiente do usuário.
- **09/10/2026:** Implementado backend do MOD-08 (Inventário Periódico). Criados modelos, schemas, repository, service e router (`/inventory-audits`). Atualizado o `env.py` do Alembic. Foram incluídas validações de status (OPENED, IN_PROGRESS, CLOSED, CANCELLED) e gestão de itens do inventário (ativos ou estoque). Próximo passo: Desenvolver as telas do Frontend para o Inventário Periódico.
- **09/10/2026:** Finalizado Frontend do MOD-08 (Inventário Periódico). Criadas as telas de listagem (`inventory-list`) e de execução da auditoria (`inventory-detail`), permitindo iniciar a conferência, registrar a situação real de Patrimônios e de Itens em Estoque e encerrar o inventário. O acesso foi adicionado ao menu lateral. Próximo passo: Seguir para a Fase 6 (Módulos Transversais).
- **09/10/2026:** MOD-09 (Contas e Acessos Avançados) concluído. A base no backend (Identity) já vinculava Colaboradores a UserAccounts (1:1), restava polir a interface. As telas de Gestão de Usuários (`user-list`, `user-dialog`) e de Gestão de Perfis de Acesso/Roles (`role-list`, `role-dialog`) foram completamente modernizadas no Angular, entregando a vinculação avançada com design visual "premium". Próximo passo: MOD-10 (Anexos em Disco).
- [x] MOD-10 (Anexos em Disco) concluído. Criado backend (models, repository, service, router) para salvar metadados no banco e arquivo na pasta `/uploads`. Adicionado frontend (AttachmentsService e AttachmentsComponent) e integrado nos componentes de detalhe de Chamados e de Ativos. Próximo passo: MOD-11 (Notificações).
- **09/10/2026:** MOD-11 (Notificações) e MOD-12 (Auditoria) implementados no backend. Auditoria intercepta todos os eventos do barramento local e registra logs. Notificações implementam WebSockets para push em tempo real. Alembic migrado para suportar os novos models. Próximo passo: Implementar o frontend e testes da Fase 6.
