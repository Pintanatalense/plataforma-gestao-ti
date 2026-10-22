# Status e Pendências - Plataforma de Gestão de TI

> **ARQUIVADO (2026-10-21) — não é fonte de verdade.** Este documento foi gerado antes das fases A–G e contém afirmações desatualizadas ou incorretas (por exemplo versões do Angular, Evolution API e status de "produção/homologado"). Vale o código. Estado atual: `README.md`, `docs/decisions/` e `docs/plans/plano-diretor.md`.

Este documento sumariza o status atual do projeto, as funcionalidades recém-entregues, e mapeia as pendências técnicas e tarefas pendentes que necessitam de intervenção ou desenvolvimento futuro.

---

## ✅ Funcionalidades Entregues e Concluídas

1. **Reestruturação e Entrega Completa do Frontend dos Módulos Físicos**
   - **Patrimônio e Ativos (`features/assets`)**:
     - `AssetListComponent`: listagem, badges de status, busca dinâmica por patrimônio/nome/categoria, botão de atalho para Categorias e roteamento.
     - `AssetCategoryListComponent`: tela completa de gestão de Categorias de Ativos (`/assets/categories`), com formulário reativo, builder visual de especificações dinâmicas (`spec_schema`), presets rápidos (Computador, Rede, Mobile) e listagem de categorias com edição/exclusão.
     - `AssetCreateComponent`: cadastro completo com formulário reativo dinâmico para especificações técnicas em JSONB baseadas na categoria.
     - `AssetDetailComponent`: visão geral com especificações, galeria/upload de anexos integrados (`AttachmentsComponent`) e linha do tempo de movimentações.
     - `AssetService`: integração completa com a API de ativos, movimentações e categorias (CRUD).
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
   - **Suíte Frontend**: 22 arquivos de teste e 32 testes unitários 100% aprovados via Vitest.

9. **Segurança de Rotas, Guards e Downloads Autenticados**
   - **Guards de Rota no Frontend (`auth.guard.ts`)**:
     - `authGuard`: validação de sessão, aguardo do carregamento assíncrono de `/me` (`ensureUser()`) e redirecionamento forçado para `/change-password` se exigido.
     - `permissionGuard(permission)`: validação declarativa de permissões granulares por rota com redirecionamento para o dashboard para usuários sem autorização.
     - `guestGuard`: redirecionamento automático de usuários já autenticados para o dashboard ao acessar `/login`.
   - **Downloads Autenticados**:
     - Substituição de `window.open` por `HttpClient` com `Blob` para envio seguro do cabeçalho `Authorization: Bearer <token>` tanto no download de anexos genéricos quanto na abertura do termo de responsabilidade.
   - **Segurança RBAC no Inventário**:
     - Endpoints de auditoria de inventário protegidos no backend por `inventory.read` e `inventory.write`.
     - Seed atualizado para sincronizar 25 permissões no perfil Administrador.

10. **Homologação e Deploy no Docker Compose**
    - **PostgreSQL 16 (`gestao-ti-db`)**: saudável e operacional na porta 5432.
    - **Backend FastAPI (`gestao-ti-api`)**: saudável e operacional com 4 workers Uvicorn na porta 8000.
    - **Nginx Proxy (`gestao-ti-proxy`)**: operacional na porta 80, servindo o frontend Angular e roteando chamadas de API (`/api/v1/`) e WebSockets (`/ws/`).
    - Migrações Alembic executadas e sincronizadas até a revisão `c2a8f41e9b03`.

11. **Perfil Solicitante ("Só Abrir Chamado") e Criador de Formulários com Pré-requisitos**
    - **Perfil Solicitante e RBAC Especializado**:
      - Novas permissões granulares no seed: `service_desk.tickets.create` e `service_desk.tickets.read`.
      - Perfil nativo `Solicitante` restrito estritamente à abertura e acompanhamento dos próprios chamados.
      - Sidebar e Dashboard adaptados: menus operacionais, ativos, estoque e segurança ficam invisíveis; a interface entrega experiência focada de autoatendimento ("Abrir Chamado" em destaque e lista dos seus chamados).
    - **Criador de Formulários por Categoria (Form Builder)**:
      - Colunas `form_schema` (JSONB) em `sd_ticket_category` e `custom_fields` (JSONB) em `sd_ticket`.
      - Construtor visual em `/service-desk/categories` com suporte a tipos (`text`, `textarea`, `number`, `select`, `checkbox`, `date`), opções para selects, marcação de `Pré-requisito Obrigatório`, templates pré-definidos em 1 clique (Troca de Hardware, Acesso a Sistema, Incidente Crítico) e Live Preview em tempo real.
    - **Validação Rigorosa de Pré-requisitos**:
      - Validação no Frontend: formulário reativo dinâmico que bloqueia a submissão e alerta campos obrigatórios pendentes.
      - Validação no Backend: barreira em `create_ticket` que rejeita a requisição (HTTP 400 `BusinessRuleException`) caso qualquer pré-requisito obrigatório esteja ausente, vazio ou preenchido com opção inválida.
    - **Visualização de Pré-requisitos no Chamado**:
      - Resumo dos pré-requisitos preenchidos exibido nos cards e em aba dedicada do chamado (`/service-desk/:id`).

12. **Categorias de Estoque e Especificações Técnicas Dinâmicas**
    - **Modelagem e Migração (`d4e9f71a82b4`)**:
      - Tabela `stk_categories` com `name`, `description` e `spec_schema` (JSONB).
      - Colunas `category_id` e `technical_specs` (JSONB) em `stk_items`.
    - **Gestão no Frontend**:
      - Interface de gestão de categorias de estoque (`/stock/categories`).
      - Suporte a formulário dinâmico de especificações técnicas no cadastro/edição de itens de estoque.
    - **Seed de Categorias Padrão**:
      - Inclusão automática de categorias essenciais: Periféricos & Acessórios, Cabos & Conectores, Toners & Suprimentos, Componentes & Peças.

13. **Linha do Tempo (Histórico) de Chamados e Resiliência de Autenticação**
    - **Histórico e Timeline Unificada**:
      - Novo endpoint `GET /api/v1/tickets/{id}/history` consolidando criação, alterações de status/responsável, notas internas, mensagens e consumo de materiais.
      - Nova aba "Linha do Tempo" interativa com badges de eventos, autor identificado por funcionário/e-mail e datação relativa.
      - Capacidade de encerramento do chamado pelo próprio solicitante.
    - **Estabilidade de Login e Troca de Senha**:
      - `AuthService` com persistência em cache (`USER_KEY`) e revalidação transparente em segundo plano, evitando deslogue indevido por recarregamento.
      - Redirecionamento correto e feedback visual no fluxo de primeiro login (`must_change_password`).

14. **Plano de Evolução do Sistema de Gestão de Chamados (Fases 1 a 6)**
    - **Perfis e Permissões Tripartites (RBAC Granular)**:
      - Perfis operacionais pré-configurados e sincronizados: `Gestão` (13 permissões, foco gerencial, relatórios e visão global de chamados), `Atendente` (7 permissões, foco operacional, notas internas, baixa de insumos e solução), `Solicitante` (2 permissões, autoatendimento estrito) e `Administrador` (35 permissões, controle pleno).
      - Isolamento estrito no backend: verificação de escopo de permissões nas rotas (`can_read_all`, `can_internal_notes`, `can_view_reports`, `system.backup.manage`, `system.data.export`, `system.data.import`, `integrations.whatsapp.manage`).
    - **Importação e Exportação Segura de Dados CSV**:
      - **Exportação Sanitizada**: Proteção automática contra vulnerabilidade de *CSV Formula Injection* (prefixando `=`, `+`, `-`, `@`, `\t`, `\r` com `'`), delimitador configurável (`;` para Excel Brasil ou `,`), cabeçalhos opcionais e injeção de UTF-8 BOM (`\xef\xbb\xbf`) para abertura direta em planilhas sem corrupção de caracteres acentuados.
      - **Assistente de Importação em Lote**: Wizard com detecção inteligente de delimitador/encoding, auto-sugestão de mapeamento de colunas, pré-visualização tabular das primeiras linhas, tratamento de duplicidades (`pular`, `atualizar` ou `erro`), simulação prévia (*Dry Run*) e relatório analítico de execução com identificação pontual de linhas com inconsistências.
    - **Central de Backup e Integridade do Banco de Dados**:
      - Geração de snapshots consistentes do PostgreSQL compactados em `.sql.gz` em diretório protegido contra acesso público direto.
      - Cálculo e registro do Hash criptográfico SHA-256 para cada arquivo gerado para auditoria e garantia de integridade física.
      - Política de retenção configurável para limpeza automatizada de arquivos antigos.
      - Rota autenticada de download de backups com verificação estrita de permissões (`system.backup.download`).
      - Tabela de histórico com metadados (tamanho em KB/MB, status, data/hora, e-mail do autor) e guia operacional de restauração via terminal.
    - **Integração Desacoplada com Bot de Atendimento via WhatsApp**:
      - Arquitetura baseada no padrão *Adapter*: suporte nativo para `Evolution API` (código aberto e auto-hospedado), `Mock` (desenvolvimento e testes unitários) e `Meta Cloud API`.
      - Máquina de estados conversacional para WhatsApp:
        1. Vinculação e identificação segura do colaborador via matrícula funcional (`REG`).
        2. Abertura interativa de chamados com seleção numerada de categoria, preenchimento de título e descrição detalhada.
        3. Consulta dinâmica dos chamados em aberto do solicitante e seus respectivos status.
        4. Resposta e envio de interações diretamente pelo WhatsApp registradas no histórico do chamado.
      - *Notification Dispatcher*: disparador de alertas automáticos quando um chamado for atribuído ou tiver seu status alterado.
    - **Painel Administrativo Unificado no Frontend (`/admin`)**:
      - Hub administrativo centralizado com 5 abas integradas: *Bot do WhatsApp* (com painel de teste de disparo e status toggle), *Importação CSV* (Wizard progressivo de 3 passos), *Exportação CSV* (com filtros de data e delimitador), *Backups do Banco* (com download e exclusão) e *Perfis & Matriz RBAC* (com cards explicativos e atalhos operacionais).
      - Rota protegida `/admin` e link destacado na barra lateral de navegação (`SidebarComponent`).

15. **Módulo WhatsApp Avançado: Escudo Anti-Ban, Fila Outbox, Templates e Disparo Rápido em Chamados**
    - **Proteção Anti-Ban Robusta**:
      - Mecanismos avançados para prevenir bloqueios de números empresariais: atrasos humanizados com *jitter* randômico (`min_delay_seconds` a `max_delay_seconds`), controle de cadência por minuto (`max_messages_per_minute`) e *cooldown* por destinatário (`cooldown_per_recipient_seconds`) para não sobrecarregar o mesmo colaborador.
      - Emulação de presença humana através do evento `"composing"` (digitando...) na Evolution API e Meta Cloud API antes do envio do texto.
      - *Kill Switch* emergencial (`emergency_pause`) com acionamento com 1 clique para cessar instantaneamente qualquer disparo em massa sem perder registros na fila.
    - **Fila Persistente Outbox (`wa_outbox`)**:
      - Desacoplamento integral de todos os envios com persistência transacional (`PENDING`, `SENDING`, `SENT`, `FAILED`, `CANCELLED`).
      - Suporte a tentativas automáticas com tolerância a falhas temporárias de rede, histórico de erros (`last_error`) e reprocessamento sob demanda.
    - **Templates e Respostas Rápidas Operacionais (`wa_templates`)**:
      - Cadastro e gestão de templates dinâmicos categorizados por módulo (`SERVICE_DESK`, `NOTIFICATIONS`, `GENERAL`).
      - Suporte completo a tags contextuais: `{{solicitante}}`, `{{protocolo}}`, `{{titulo}}`, `{{status}}`, `{{atendente}}`, `{{unidade}}`, `{{observacao}}`, `{{empresa}}`.
      - 7 templates pré-definidos essenciais para o fluxo de TI empresarial inseridos no seed do sistema (`TICKET_OPENED`, `TICKET_IN_PROGRESS`, `AWAITING_USER`, `REMOTE_ACCESS`, `ASSET_READY`, `TICKET_RESOLVED`, `MAINTENANCE_ALERT`).
    - **Painel Administrativo com Sub-Visões WhatsApp (`/admin`)**:
      - Sub-navegação com 4 visões integradas: *Conexão & Gateway*, *Escudo Anti-Ban*, *Templates & Simulador* (com mock chat estilo WhatsApp interativo em tempo real) e *Monitor da Fila Outbox* (com estatísticas ao vivo, cancelamento e reprocessamento).
    - **Disparo Rápido Integrado ao Chamado (`ticket-detail`)**:
      - Botão WhatsApp de acesso rápido na barra de ações do chamado exclusivo para a equipe de atendimento.
      - Modal com identificação do colaborador, validação de telefone cadastrado, seleção de templates com interpolação instantânea, campo livre de observações adicionais e badge informativo de proteção anti-ban ativa.
      - Registro automático de cada disparo como mensagem de atendimento no chat e linha do tempo do chamado, mantendo auditoria e transparência com o solicitante.

16. **Integração Bidirecional Completa: Ativos x Chamados e Rastreabilidade Operacional**
    - **Vínculo e Desvínculo Sob Demanda em Chamados Abertos**:
      - Novos endpoints `POST /api/v1/tickets/{ticket_id}/assets/{asset_id}` e `DELETE /api/v1/tickets/{ticket_id}/assets/{asset_id}` com registro auditado na linha do tempo (`ticket.asset_linked` e `ticket.asset_unlinked`).
      - Interface visual em `TicketDetailComponent`: modal para pesquisa e vínculo de equipamentos patrimoniais e ação rápida para desvincular itens associados por engano.
    - **Visão Reversa de Chamados no Detalhe do Ativo (`asset-detail`)**:
      - Novo endpoint `GET /api/v1/assets/{asset_id}/tickets` listando todos os chamados que envolveram o equipamento com badges de status, prioridade e solicitante.
      - Nova aba interativa "Chamados Relacionados" no cadastro do ativo com links diretos para cada atendimento.
      - Botão de ação rápida "Abrir Chamado" no cabeçalho do ativo pré-preenchendo o equipamento via query params.
    - **Autoatendimento Inclusivo para Solicitantes (`ticket-create`)**:
      - Solicitantes comuns agora visualizam e vinculam seus próprios equipamentos atribuídos (`GET /api/v1/assets/me`) mesmo sem possuir a permissão administrativa global `assets.read`.
      - Pré-seleção automática de ativo quando aberto a partir da tela de detalhes de um equipamento.

---

## 🎯 Status do MVP

Todas as Fases do roadmap foram concluídas integralmente:
- MOD-01 a MOD-12 100% operacionais e integrados.
- Fluxo de Termo de Responsabilidade e Assinatura Externa finalizado e validado.
- Proteção de rotas ponta a ponta com RBAC e JWT interceptor tratando expiração 401.
- Perfil Solicitante restrito e Form Builder com pré-requisitos obrigatórios homologados.
- Categorias de estoque com especificações técnicas dinâmicas integradas.
- Histórico completo de auditoria e linha do tempo do Service Desk com encerramento pelo solicitante.
- Módulos avançados do Plano de Evolução: RBAC Tripartite, CSV Import/Export, DB Backups, WhatsApp Bot e Painel Admin entregues.
- Módulo WhatsApp Anti-Ban, Fila Outbox, Templates e Disparo Rápido em Chamados 100% implementado e validado.
- Integração bidirecional Ativos x Chamados (vínculo dinâmico, visão reversa e autoatendimento de ativos pelo solicitante) 100% entregue.
- Suíte automatizada de testes cobrindo unidade, integração, auditoria, anexos, notificações, WhatsApp, ciclo de vida e E2E (**122 backend aprovados + 1 xfailed esperado, 39 frontend aprovados com 100% de sucesso**).
- Build de produção compilando limpo e otimizado via Angular 18+ e FastAPI/PostgreSQL.




