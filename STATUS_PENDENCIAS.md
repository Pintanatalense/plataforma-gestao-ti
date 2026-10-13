# Status e Pendências - Plataforma de Gestão de TI

Este documento sumariza o status atual do projeto, as funcionalidades recém-entregues, e mapeia as pendências técnicas e tarefas pendentes que necessitam de intervenção ou desenvolvimento futuro.

---

## ✅ Funcionalidades Entregues e Concluídas

1. **Reestruturação e Entrega Completa do Frontend dos Módulos Físicos**
   - **Patrimônio e Ativos (`features/assets`)**:
     - `AssetListComponent`: listagem, badges de status, busca dinâmica por patrimônio/nome/categoria e roteamento.
     - `AssetCreateComponent`: cadastro completo com formulário reativo dinâmico para especificações técnicas em JSONB baseadas na categoria.
     - `AssetDetailComponent`: visão geral com especificações, galeria/upload de anexos integrados (`AttachmentsComponent`) e linha do tempo de movimentações.
     - `AssetService`: integração completa com a API de ativos e movimentações.
   - **Estoque e Insumos (`features/stock`)**:
     - `StockListComponent`: listagem, alertas visuais de estoque baixo (`min_quantity`), badges por unidade física.
     - `StockCreateComponent`: criação de novos insumos com validação de quantidades iniciais e limites mínimos.
     - `StockDetailComponent`: visão do saldo, lançamento de movimentações (Entrada, Saída, Ajuste) e histórico em linha do tempo.
     - `StockService`: serviço reativo conectado à API do estoque.
   - **Inventário Periódico (`features/inventory`)**:
     - `InventoryListComponent`: acompanhamento de auditorias abertas, em andamento e concluídas, com dialog para criação de novas conferências (`CreateAuditDialogComponent`).
     - `InventoryDetailComponent`: conferência item a item (ativos e insumos), verificação de conformidade esperada vs. real, botões de início, encerramento e cancelamento.
     - `InventoryService`: operações completas de auditoria e itens auditados.
   - **Service Desk**:
     - Implementado gerenciador de Categorias de Chamados (`CategoryListComponent`), permitindo associar categorias a setores de atendimento padrão.

2. **Criação do Shell e Layout Interno Definitivo**
   - **Sidebar**:
     - Logomarca da empresa e nome exibidos dinamicamente (`/organization/company/public`), com fallback para badge de sistema.
     - Navegação modular dividida em seções claras: Principal, Service Desk, Operações & Físico, Organização e Segurança & Acessos.
     - Filtragem de menus orientada a permissões granulares (`AuthService.hasPermission`), garantindo acesso adaptativo para Admin, Técnicos e Colaboradores.
   - **Header**:
     - Integração com `NotificationsService` via WebSockets em tempo real.
     - Indicador numérico (badge) de notificações não lidas.
     - Menu dropdown com lista de notificações, clique para marcar como lida e botão "Marcar todas como lidas".
     - Menu do usuário com identificação de perfil e acesso direto a alteração de senha e logout.
   - **Shell**:
     - Layout responsivo com transição de Sidenav, espaçamentos consistentes e fundo `#f8fafc`.

3. **Testes Automatizados dos Módulos Transversais (Fase 6)**
   - Criados testes de integração no Backend:
     - `tests/notifications/test_notifications.py`: listagem, leitura e marcação em massa de notificações.
     - `tests/audit/test_audit.py`: validação de logs de auditoria e filtros por entidade.
     - `tests/attachments/test_attachments.py`: upload físico em disco, listagem por entidade, download e exclusão.
   - **Status dos testes:** Suíte executada com 100% de sucesso.

4. **Dashboard Principal & Responsividade Mobile (Fase 7)**
   - Criado [Dashboard](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/dashboard/dashboard.component.ts) completo com KPIs em tempo real (chamados pendentes, ativos em uso/estoque, alerta de insumos com estoque crítico e contagem de auditorias ativas).
   - Tabela de chamados recentes com acesso rápido ao atendimento.
   - Painel lateral com alertas de insumos abaixo da cota mínima e atalhos rápidos.
   - Suporte responsivo com `@angular/cdk/layout` no [ShellComponent](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/layout/shell/shell.component.ts) com `mode="over"` em celulares/tablets e fechamento automático ao navegar.

5. **Documentação e Guia do Usuário**
   - Criado o manual completo em [docs/user-guide.md](file:///c:/Projetos/plataforma-gestao-ti/docs/user-guide.md), cobrindo perfis (Colaborador, Técnico, Gestor e Admin) e todos os fluxos operacionais.

6. **Consistência do Build e CI**
   - Frontend: `ng build` compila 100% sem erros, bundles otimizados.
   - Backend: endpoints documentados no OpenAPI/Swagger e schemas alinhados com Pydantic v2.

7. **Testes End-to-End (E2E) e Homologação dos Perfis (Fase 7 - Concluída)**
   - `tests/test_e2e_lifecycle.py`:
     - Teste de ciclo de vida completo: Organização -> Ativos com specs JSONB -> Insumos em Estoque -> Abertura de Chamado associando Ativo -> Atendimento com chat público e notas internas isoladas -> Anexo de evidências fotográficas/documentais -> Consumo de insumo com baixa automática no estoque -> Encerramento do chamado -> Push de notificação e leitura -> Auditoria administrativa com bloqueio a usuários sem privilégios.
     - Teste da Matriz RBAC para os 4 perfis operacionais: `Admin`, `Gestor`, `Técnico` e `Colaborador`.
   - Suíte de testes backend: 92 aprovados, 1 baseline xfailed documentado.

8. **Termo de Responsabilidade & Cautela e Fluxo de Assinatura Externa**
   - **Geração Formal de Documento (Backend)**: endpoint `GET /api/v1/assets/{asset_id}/responsibility-statement` gerando HTML padronizado com `@media print`, dados cadastrais da empresa, colaborador vinculado, especificações técnicas detalhadas e cláusulas de zelo.
   - **Fluxo Operacional de Assinatura Externa (Frontend)**:
     - Card dedicado guiando os 3 passos: 1. Gerar Termo Oficial -> 2. Coletar Assinatura Externa (Clicksign, DocuSign, Gov.br ou física) -> 3. Anexar Documento Assinado diretamente ao ativo.
     - Indicador visual dinâmico de status: `Termo Assinado Anexado` (verde) vs `Aguardando Anexo do Termo` (âmbar).
     - Upload direto com barra de progresso e botão para visualização imediata do documento anexado.
     - Destaque e detecção automática de termos com badge `Termo Assinado` na listagem de anexos.
     - Ação rápida na listagem de ativos para gerar termo diretamente com 1 clique para equipamentos atribuídos.
   - **Suíte Frontend**: 21 arquivos de teste e 25 testes unitários 100% aprovados via Vitest.

---

## 🎯 Status do MVP

Todas as Fases do roadmap foram concluídas integralmente:
- MOD-01 a MOD-12 100% operacionais e integrados.
- Fluxo de Termo de Responsabilidade e Assinatura Externa finalizado e validado.
- Interface rica com Material 3, responsiva para dispositivos móveis e desktops.
- Suíte automatizada de testes cobrindo unidade, integração, auditoria, anexos, notificações e E2E (92 backend + 25 frontend).
- Sistema pronto para publicação, homologação e deploy via Docker Compose com migrations e seed automáticos.



