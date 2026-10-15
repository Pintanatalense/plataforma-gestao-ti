# Mapeamento Completo de Telas e Funcionalidades — Plataforma de Gestão de TI

> **Documento de Referência Oficial do Sistema**  
> **Arquivo:** `Oque_tem_gestao_ti.md`  
> **Data de Levantamento:** Outubro de 2026  
> **Status da Plataforma:** Produção / Homologado (Angular 18+ Zoneless, FastAPI, PostgreSQL 16)

---

## 📌 Sumário Executivo

A **Plataforma de Gestão de TI** é um ecossistema integrado para governança de Tecnologia da Informação, suporte operacional e controle físico-patrimonial corporativo.

O sistema opera sob o modelo de **Controle de Acesso Baseado em Funções (RBAC Tripartite + Solicitante)** com quatro perfis padrão:
1. **Administrador (`Admin`)**: Acesso irrestrito a todas as rotas operacionais, cadastrais e administrativas (35 permissões).
2. **Gestão (`Gestor`)**: Visão gerencial global de chamados, relatórios de produtividade, auditorias de inventário e supervisão física (13 permissões).
3. **Atendente (`Técnico`)**: Atendimento operacional de chamados, movimentação de ativos, notas internas, baixa de insumos de estoque e triagem (7 permissões).
4. **Solicitante (`Usuário Padrão`)**: Perfil restrito de autoatendimento para abertura e acompanhamento estrito dos seus próprios chamados ou chamados do seu setor (2 permissões).

---

## 🧭 Estrutura Global de Layout (Shell da Aplicação)

Todas as telas internas do sistema rodam envelopadas pelo componente [`ShellComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/layout/shell/shell.component.ts), composto por:

### 1. Barra Lateral de Navegação ([`SidebarComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/layout/sidebar/sidebar.component.ts))
* **Identidade Visual Dinâmica:** Exibe o logotipo oficial e a razão social da empresa obtidos via API pública (`GET /api/v1/organization/company/public`). Caso não haja logo cadastrado, apresenta um badge com ícone padrão de computador.
* **Menus por Seção com Filtragem de Permissões:**
  * **Principal:** *Dashboard* (Acesso universal).
  * **Service Desk:** *Chamados*, *Abrir Chamado* e *Categorias de Chamados* (restrito a `service_desk.tickets.manage`).
  * **Operações & Físico:** *Patrimônio & Ativos* (`assets.read`), *Categorias de Ativos* (`assets.read`), *Estoque & Insumos* (`stock.read`), *Inventário Periódico* (`inventory.read`).
  * **Organização:** *Unidades* (`organization.units.read`), *Setores* (`organization.sectors.read`), *Colaboradores* (`organization.employees.read`).
  * **Administração & Sistema:** *Painel Administrativo* (`identity.roles.read`), *Usuários* (`identity.users.read`), *Perfis (Roles)* (`identity.roles.read`).
* **Comportamento Mobile:** Em resoluções menores que 768px, a sidebar opera em modo `over` (gaveta suspensa) com fechamento automático após clique em qualquer rota.

### 2. Barra Superior ([`HeaderComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/layout/header/header.component.ts))
* **Botão Hambúrguer:** Alterna a visibilidade/recolhimento da barra lateral.
* **Badge de Ambiente Demo:** Quando o backend está com modo de demonstração ativo (`/api/v1/system/demo/status`), exibe uma etiqueta destacada em amarelo/âmbar informando `AMBIENTE DEMO` para prevenir que operadores confundam dados fictícios com a base real.
* **Central de Notificações em Tempo Real:**
  * Conexão ativa via WebSockets (`NotificationsService`) recebendo pushes de chamados atribuídos, alterações de status e movimentações.
  * Contador numérico vermelho (badge) de notificações não lidas.
  * Menu dropdown com rolagem contínua, datação relativa, clique para marcar como lida e botão "Marcar todas como lidas".
* **Pílula de Perfil do Usuário:**
  * Avatar com as iniciais do e-mail do operador.
  * Exibição do e-mail e nível de acesso (`Administrador` vs `Colaborador`).
  * Dropdown com atalho direto para *Alterar Senha* (`/change-password`) e *Sair do Sistema* (logout com revogação de tokens).

---

## 🖥️ Detalhamento Página por Página

---

### 1. Setup Inicial do Sistema
* **Rota:** `/setup`
* **Componente:** [`SetupComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/setup/setup.component.ts)
* **Controle de Acesso:** [`setupGuard`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/auth/setup.guard.ts) (Permitido **apenas** quando o sistema não possui nenhum administrador cadastrado no banco).
* **O que faz no sistema:**
  Inicializa a plataforma pela primeira vez criando a credencial mestra de Administrador e a estrutura corporativa fundamental.
* **Elementos da Página:**
  * Card centralizado com estilo glassmorphism e logo do sistema.
  * Formulário reativo com campos:
    * Nome Completo do Administrador.
    * E-mail institucional do Administrador.
    * Senha (mínimo de 8 caracteres) com visualizador de força/máscara.
    * Confirmação de Senha (validador de correspondência em tempo real).
    * Seletor de Modo de Instalação (`setup_mode`):
      * `CLEAN`: Instalação Empresarial Limpa (apenas permissões e tabelas zeradas).
      * `DEMO`: Modo Demonstração (popula o banco com unidades, ativos, insumos e chamados fictícios realistas).
    * Razão Social da Empresa e CNPJ.
  * Botão de envio com spinner de processamento assíncrono.

---

### 2. Autenticação e Login
* **Rota:** `/login`
* **Componente:** [`LoginComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/auth/login/login.component.ts)
* **Controle de Acesso:** [`guestGuard`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/auth/auth.guard.ts) (Se já estiver logado, redireciona automaticamente para o Dashboard).
* **O que faz no sistema:**
  Valida e-mail e senha do operador, gerando um token JWT com lista de permissões embutida (`claims`). Se o sistema nunca foi configurado, redireciona imediatamente para `/setup`. Se o usuário tiver a flag `must_change_password`, obriga o redirecionamento para `/change-password`.
* **Elementos da Página:**
  * Box moderno com logotipo e chamada de boas-vindas.
  * Campos de E-mail e Senha (com botão de alternar visibilidade de caracteres).
  * Botão "Entrar no Sistema".
  * Feedback via snackbar em caso de credenciais inválidas ou erro de conexão.

---

### 3. Alteração Obrigatória / Voluntária de Senha
* **Rota:** `/change-password`
* **Componente:** [`ChangePasswordComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/auth/change-password/change-password.component.ts)
* **Controle de Acesso:** [`authGuard`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/core/auth/auth.guard.ts) (Apenas usuários autenticados).
* **O que faz no sistema:**
  Permite ao usuário atualizar sua própria senha ou cumpre a exigência de primeiro acesso gerada pelo reset administrativo.
* **Elementos da Página:**
  * Card com aviso de segurança.
  * Campos: Senha Atual, Nova Senha (mínimo 8 dígitos) e Confirmação da Nova Senha.
  * Validação dinâmica de confirmação e botão "Atualizar Senha".

---

### 4. Painel Principal (Dashboard)
* **Rota:** `/dashboard` (Rota padrão `/`)
* **Componente:** [`Dashboard`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/dashboard/dashboard.component.ts)
* **Controle de Acesso:** Livre para qualquer usuário autenticado (adapta a exibição conforme o perfil).
* **O que faz no sistema:**
  Hub central de métricas e produtividade. Apresenta indicadores em tempo real (chamados, ativos, estoque e auditorias), atalhos rápidos e alertas preventivos.
* **Regras de Visão por Perfil:**
  * **Técnico / Gestor / Admin:** Vê todos os chamados abertos e em atendimento no sistema, volume total do parque tecnológico, alertas de estoque crítico e contagem de auditorias ativas.
  * **Solicitante Comum:** O card de chamados vira "Meus Chamados Pendentes", a tabela mostra apenas os chamados abertos por ele ou destinados ao seu setor, e a lateral oculta o estoque para exibir o card de **Autoatendimento TI** com links para abrir chamado e consultar histórico.
* **Elementos da Página:**
  * **Banner de Boas-vindas:** Exibe data completa, saudação e botões de ação rápida: "Abrir Chamado" e "Novo Ativo" (se tiver permissão `assets.write`).
  * **Grid de Cards de KPIs (Indicadores):**
    1. *Chamados Pendentes:* Total de tickets abertos + em atendimento, com badge de alerta para abertos.
    2. *Parque de Ativos:* Total de equipamentos cadastrados, quantidade "Em Uso" e quantidade "Em Estoque Disponível".
    3. *Estoque & Insumos:* Total de itens cadastrados e badge dinâmico: verde se estoque regular, ou vermelho `X em alerta` exigindo reposição imediata.
    4. *Auditorias de Inventário:* Quantidade de auditorias físicas em andamento na empresa.
  * **Tabela de Chamados Recentes:**
    * Colunas: Assunto, Status (com chips coloridos: Aberto, Em Atendimento, Resolvido, Encerrado), Prioridade (Baixa, Média, Alta, Crítica), Data de Criação e Botão de Ação Direta para a sala de atendimento (`/service-desk/:id`).
    * Linhas clicáveis interativas com efeito hover.
    * Estado vazio (`noDataRow`) com ilustração caso não haja tickets.
  * **Painel Lateral de Alertas e Acesso Rápido:**
    * *Insumos Críticos:* Lista os 4 primeiros itens cujo saldo atingiu ou caiu abaixo da cota mínima (`min_quantity`), com quantidade em destaque e link para o item.
    * *Acesso Rápido:* Botões para Consultar Patrimônio, Conferências de Inventário e Unidades & Colaboradores.

---

### 5. Service Desk — Listagem de Chamados
* **Rota:** `/service-desk`
* **Componente:** [`TicketListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/service-desk/ticket-list/ticket-list.component.ts)
* **Controle de Acesso:** Usuários autenticados (`service_desk.tickets.read`).
* **O que faz no sistema:**
  Exibe a fila de atendimento de chamados de suporte. Se o usuário for técnico/gestor/admin, lista todos os chamados; se for solicitante, isola a listagem para mostrar apenas chamados abertos por ele ou pelo seu setor de trabalho.
* **Elementos da Página:**
  * Cabeçalho com título, subtítulo e botão destacado "Abrir Chamado".
  * Tabela de chamados contendo:
    * **Assunto:** Título do ticket.
    * **Solicitante:** Nome do colaborador solicitante.
    * **Status:** Badges temáticos para `Aberto`, `Em Atendimento`, `Pendente`, `Resolvido` e `Encerrado`.
    * **Prioridade:** Tags visuais de prioridade com códigos de cores (`Baixa`, `Média`, `Alta`, `Crítica`).
    * **Criado em:** Data e hora de abertura formatadas (`dd/MM/yyyy HH:mm`).
    * **Ações:** Botão com ícone de balão de chat levando diretamente à tela de detalhes do atendimento.
  * Linhas clicáveis com redirecionamento para o chamado.

---

### 6. Service Desk — Abertura de Chamado
* **Rota:** `/service-desk/new`
* **Componente:** [`TicketCreateComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/service-desk/ticket-create/ticket-create.component.ts)
* **Controle de Acesso:** `service_desk.tickets.create`.
* **O que faz no sistema:**
  Formulário guiado para abertura de novas solicitações de TI, integrando seleção de categoria, formulários de pré-requisitos dinâmicos, vinculação de equipamentos e anexo de evidências.
* **Elementos da Página:**
  * **Identificação do Solicitante:** Informações do colaborador logado.
  * **Seleção de Categoria de Atendimento:** Lista categorias cadastradas com descrição explicativa e roteamento padrão.
  * **Pré-requisitos e Campos Dinâmicos (Renderizador Reativo):**
    * Ao selecionar uma categoria que possui `form_schema` configurado, a página renderiza dinamicamente os campos exigidos (textos, seletores, números, caixas de seleção, datas).
    * Bloqueia a submissão com validação em tempo real caso algum pré-requisito marcado como obrigatório não seja atendido.
  * **Vínculo com Equipamento Patrimonial (Ativo):**
    * *Para Solicitantes Comuns:* Apresenta dropdown contendo exclusivamente os equipamentos atribuídos em custódia para si próprio (`GET /api/v1/assets/me`).
    * *Para Técnicos/Admin:* Apresenta a lista global de ativos patrimoniais.
    * *Pré-seleção Automática:* Se a página for aberta a partir de um ativo (`?asset_id=...`), o equipamento já vem selecionado e travado.
  * **Título e Descrição Detalhada:** Campos para detalhamento do problema com formatação rica.
  * **Prioridade Sugerida:** Seleção de urgência do atendimento.
  * **Uploader de Evidências / Anexos:**
    * Zona para seleção de múltiplos arquivos (fotos do defeito, documentos, relatórios de erro, PDFs).
    * Lista de chips com nome do arquivo, tamanho e botão para remover antes de submeter.
  * Botões de "Cancelar" e "Abrir Chamado" (com desativação enquanto faz upload de arquivos).

---

### 7. Service Desk — Atendimento e Detalhes do Chamado
* **Rota:** `/service-desk/:id`
* **Componente:** [`TicketDetailComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/service-desk/ticket-detail/ticket-detail.component.ts)
* **Controle de Acesso:** Usuários com acesso ao chamado (autor, setor destinatário, técnicos ou administradores).
* **O que faz no sistema:**
  Central multimídia e operacional do atendimento. Reúne comunicação direta, notas internas de engenharia, movimentação de ativos, consumo de peças do estoque, histórico auditado e disparo de mensagens via WhatsApp.
* **Elementos da Página:**
  * **Cabeçalho de Status:**
    * Protocolo do chamado, categoria, solicitante e responsável atual.
    * Seletor de mudança de status (`Aberto` -> `Em Atendimento` -> `Resolvido` -> `Encerrado`), com abertura de modal para justificativa obrigatória.
    * Botão "Encerrar Chamado" disponível para o próprio solicitante após resolução.
  * **Ações Rápidas do Cabeçalho:**
    * **Disparo WhatsApp Rápido (Exclusivo Técnico/Admin):** Abre modal inteligente que verifica o telefone do colaborador, permite selecionar um template pronto (`TICKET_IN_PROGRESS`, `AWAITING_USER`, `REMOTE_ACCESS`, `TICKET_RESOLVED`, etc.), preenche tags contextuais em tempo real, exibe aviso de proteção anti-ban ativa e registra o envio automaticamente como mensagem no chamado.
    * **Vincular / Desvincular Ativo:** Modal de busca e associação de equipamentos patrimoniais ao ticket.
  * **Navegação por Abas:**
    1. **Aba Atendimento / Chat:**
       * Linha de mensagens públicas entre técnico e usuário.
       * **Notas Internas (DEC-012):** Caixa de seleção "Nota Interna" com destaque em fundo amarelo, visível estritamente para técnicos e administradores (oculta para o solicitante e bloqueada contra vazamento em notificações de e-mail).
       * Upload de fotos/arquivos diretamente na caixa de mensagem.
    2. **Aba Pré-requisitos Preenchidos:**
       * Exibe os campos customizados que foram informados pelo solicitante no momento da abertura do chamado.
    3. **Aba Insumos & Peças Consumidas:**
       * Permite ao atendente selecionar um item do estoque, informar a quantidade aplicada no conserto e lançar a baixa automática no estoque (`StockService`).
       * Tabela de insumos gastos com data e responsável.
    4. **Aba Ações no Ativo Vinculado:**
       * Se houver ativo patrimonial associado, permite acionar a máquina de estados diretamente do chamado: reservar para troca, entregar ao usuário, recolher em devolução ou enviar para manutenção.
    5. **Aba Linha do Tempo (Histórico Completo):**
       * Timeline cronológica consolidando criação, alterações de status, troca de responsável, materiais consumidos, notas e mensagens.
    6. **Aba Anexos & Evidências:**
       * Galeria de documentos anexados com download autenticado via Token Bearer.

---

### 8. Service Desk — Gestão de Categorias e Construtor de Formulários
* **Rota:** `/service-desk/categories`
* **Componente:** [`CategoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/service-desk/category-list/category-list.component.ts)
* **Controle de Acesso:** `service_desk.tickets.manage`.
* **O que faz no sistema:**
  Permite cadastrar as categorias de chamados do catálogo de serviços, definir o setor de triagem automática e criar visualmente formulários com pré-requisitos dinâmicos para cada categoria.
* **Elementos da Página:**
  * **Painel Esquerdo (Formulário & Form Builder):**
    * Nome da Categoria e Descrição.
    * Setor Responsável Padrão (roteia novos chamados diretamente para a fila daquele departamento).
    * **Barra de Presets Rápidos em 1 Clique:**
      * *💻 Troca de Hardware:* insere campos de Patrimônio Antigo, Motivo da Troca e Confirmação de Backup.
      * *🔐 Acesso a Sistema:* insere campos de Nome do Software, Perfil Solicitado e Matrícula do Aprovador.
      * *⚠️ Incidente Crítico:* insere campos de Impacto Operacional, Usuários Parados e Evidência de Erro.
    * **Lista Interativa de Campos:**
      * Adicionar campo personalizado.
      * Definir Título, Tipo (`text`, `textarea`, `number`, `select`, `checkbox`, `date`), Texto de Ajuda/Placeholder e opções para listas suspensas.
      * Flag "Pré-requisito Obrigatório" (impede abertura de chamado se não preenchido).
      * Reordenação e exclusão de campos.
    * **Live Preview em Tempo Real:**
      * Caixa lateral que simula exatamente como o formulário será renderizado para o solicitante.
  * **Painel Direito (Listagem de Categorias Cadastradas):**
    * Tabela com nome, setor vinculado, contagem de pré-requisitos configurados e botões de Edição e Exclusão.

---

### 9. Patrimônio e Ativos — Listagem de Equipamentos
* **Rota:** `/assets`
* **Componente:** [`AssetListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/asset-list/asset-list.component.ts)
* **Controle de Acesso:** `assets.read`.
* **O que faz no sistema:**
  Visão geral de todo o hardware e patrimônio físico da organização (computadores, servidores, switches, monitores, licenças, dispositivos móveis).
* **Elementos da Página:**
  * Cabeçalho com atalhos para "Categorias de Ativos" e "Novo Ativo".
  * Barra de busca rápida que filtra simultaneamente por patrimônio, nome, categoria, unidade ou colaborador custodiante.
  * Tabela de Equipamentos:
    * **Patrimônio:** Tag/código do bem (`#PAT-...`).
    * **Nome do Ativo / Modelo:** Descrição e fabricante.
    * **Categoria:** Classificação do equipamento.
    * **Unidade:** Unidade física onde o equipamento se localiza.
    * **Responsável / Custodiante:** Nome do colaborador em posse do bem ou etiqueta "Em Estoque".
    * **Status do Ciclo de Vida:** Badges estilizados para `Em Estoque` (azul), `Reservado` (amarelo), `Em Uso` (verde), `Aguardando Inspeção` (laranja), `Em Manutenção` (vermelho) e `Baixado` (cinza).
    * **Ações:**
      * *Gerar Termo de Cautela:* Ícone de documento (disponível quando o equipamento possui colaborador atribuído).
      * *Visualização Rápida (Modal):* Abre o popup [`AssetQuickViewDialog`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/asset-quick-view-dialog/asset-quick-view-dialog.component.ts) sem sair da lista.
      * *Página Completa:* Redireciona para `/assets/:id`.

---

### 10. Patrimônio e Ativos — Visualização Rápida (Modal Dialog)
* **Componente:** [`AssetQuickViewDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/asset-quick-view-dialog/asset-quick-view-dialog.component.ts)
* **Controle de Acesso:** Disparado a partir da listagem de ativos.
* **O que faz no sistema:**
  Modal de inspeção rápida para técnicos em atendimento, exibindo especificações essenciais sem perder o contexto da tabela de equipamentos.
* **Elementos da Página:**
  * Cabeçalho com nome do bem, tag de patrimônio e badge de status.
  * Grid de resumo: Unidade/Lotação, Custodiante Atual, Fabricante, Modelo, Número de Série e Vencimento da Garantia (com contador de dias restantes).
  * Especificações Técnicas em chips visuais (CPU, RAM, Disco, Sistema Operacional).
  * Botões de ação no rodapé: "Gerar Termo", "Abrir Chamado com este Ativo" e "Ver Ficha Completa".

---

### 11. Patrimônio e Ativos — Cadastro de Equipamento
* **Rota:** `/assets/new`
* **Componente:** [`AssetCreateComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/asset-create/asset-create.component.ts)
* **Controle de Acesso:** `assets.write`.
* **O que faz no sistema:**
  Formulário para tombamento e incorporação de novos equipamentos ao patrimônio da empresa.
* **Elementos da Página:**
  * Dados Cadastrais: Número de Patrimônio (Tag), Nome/Modelo, Categoria, Unidade Física de Alocação e Colaborador Inicial (opcional).
  * **Formulário de Especificações Técnicas Dinâmicas:** Ao selecionar a categoria (ex: Computador, Switch, Notebook), os campos específicos definidos no `spec_schema` daquela categoria são montados dinamicamente no formulário.
  * Botões "Cancelar" e "Cadastrar Ativo".

---

### 12. Patrimônio e Ativos — Ficha Detalhada, Ciclo de Vida e Termos
* **Rota:** `/assets/:id`
* **Componente:** [`AssetDetailComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/asset-detail/asset-detail.component.ts)
* **Controle de Acesso:** `assets.read`.
* **O que faz no sistema:**
  Prontuário técnico completo do equipamento, máquina de estados do ciclo de vida, gestão do termo de responsabilidade física/digital e linha do tempo de custódia.
* **Elementos da Página:**
  * **Cabeçalho:** Identificação, status do ciclo de vida, botões de ação e botão "Abrir Chamado" pré-vinculando o equipamento.
  * **Barra de Ciclo de Vida e Operações:**
    * *Reservar Ativo:* Abre modal para selecionar colaborador futuro e notas (muda para `RESERVED`).
    * *Cancelar Reserva:* Devolve o item para o estoque disponível (`IN_STOCK`).
    * *Entregar Ativo:* Confirma a entrega ao colaborador (muda para `IN_USE`).
    * *Devolver Ativo:* Registra a entrega física pelo colaborador e envia para quarentena técnica (muda para `PENDING_INSPECTION`).
    * *Inspecionar Ativo:* Modal de inspeção onde o técnico aprova (retorna a `IN_STOCK`) ou reprova (encaminha para `MAINTENANCE`).
  * **Card de Gestão do Termo de Responsabilidade & Cautela:**
    * Passo 1: Botão "Gerar Termo Oficial" (abre o documento formal HTML com dados da empresa, colaborador, especificações e termos de zelo para impressão/PDF via `GET /api/v1/assets/{id}/responsibility-statement`).
    * Passo 2: Coleta de Assinatura Externa (Clicksign, DocuSign, Gov.br ou física).
    * Passo 3: Indicador de status: `Termo Assinado Anexado` (verde) vs `Aguardando Anexo do Termo` (âmbar).
    * Botão de upload direto do termo assinado com barra de progresso e botão para visualizar documento anexado.
  * **Grid de Informações Gerais e Especificações:**
    * Unidade, Custodiante, Fabricante, Modelo, Serial, Valor de Aquisição e Data de Garantia com dias restantes.
    * Grid com especificações técnicas (ícones contextuais para CPU, RAM, HD/SSD, SO, etc.).
  * **Navegação por Abas:**
    1. *Linha do Tempo de Movimentações:* Histórico de cada mudança de estado (Cadastro, Reserva, Entrega, Devolução, Inspeção, Manutenção) com data, autor e notas.
    2. *Chamados Relacionados:* Tabela listando todos os chamados em que o equipamento já esteve envolvido.
    3. *Anexos & Documentos:* Galeria unificada de notas fiscais, manuais e fotos do bem.

---

### 13. Patrimônio e Ativos — Categorias de Ativos & Schema Builder
* **Rota:** `/assets/categories`
* **Componente:** [`AssetCategoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/assets/category-list/category-list.component.ts)
* **Controle de Acesso:** `assets.read` / `assets.write`.
* **O que faz no sistema:**
  Permite cadastrar as famílias de equipamentos (ex: Notebooks, Servidores, Impressoras) e construir o schema JSONB de campos técnicos específicos exigidos no cadastro desses bens.
* **Elementos da Página:**
  * Formulário de criação/edição de categorias.
  * Presets rápidos de campos para computadores, dispositivos móveis e equipamentos de rede.
  * Construtor de campos técnicos dinâmicos (Nome do campo, Rótulo e Flag obrigatório).
  * Tabela de categorias cadastradas com contador de campos e ações de edição e exclusão.

---

### 14. Estoque & Insumos — Listagem de Materiais
* **Rota:** `/stock`
* **Componente:** [`StockListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/stock-list/stock-list.component.ts)
* **Controle de Acesso:** `stock.read`.
* **O que faz no sistema:**
  Controle quantitativo de materiais de consumo, cabos, periféricos, toners e peças de reposição de TI.
* **Elementos da Página:**
  * Cabeçalho com botão "Novo Item".
  * Barra de busca rápida por nome do insumo ou unidade física.
  * Tabela de Estoque:
    * **Item:** Nome do material.
    * **Unidade Física:** Local onde o lote está estocado.
    * **Quantidade:** Saldo atual / Cota mínima ideal (`/ min X`).
    * **Status:** Chip visual verde (`Normal`) ou chip vermelho pulsante com ícone de alerta (`Estoque Baixo`) quando o saldo é menor ou igual à quantidade mínima.
    * **Ações:** Botão para abrir o painel de movimentações do insumo (`/stock/:id`).

---

### 15. Estoque & Insumos — Cadastro de Insumo
* **Rota:** `/stock/new`
* **Componente:** [`StockCreateComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/stock-create/stock-create.component.ts)
* **Controle de Acesso:** `stock.write`.
* **O que faz no sistema:**
  Cadastra um novo produto ou material no inventário de almoxarifado de TI.
* **Elementos da Página:**
  * Nome do item, descrição e unidade física de estocagem.
  * Quantidade inicial e quantidade mínima de segurança (ponto de pedido).
  * Seletor de Categoria de Estoque com suporte a especificações técnicas dinâmicas.
  * Botões "Cancelar" e "Cadastrar Item".

---

### 16. Estoque & Insumos — Ficha do Insumo e Lançamento de Movimentação
* **Rota:** `/stock/:id`
* **Componente:** [`StockDetailComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/stock-detail/stock-detail.component.ts)
* **Controle de Acesso:** `stock.read` / `stock.write`.
* **O que faz no sistema:**
  Painel do material para visualização do saldo em tempo real, lançamento de entradas/saídas/ajustes manuais e conferência do extrato histórico.
* **Elementos da Página:**
  * **Card de Detalhes:** Descrição, saldo atual em estoque e cota mínima recomendada com badge de alerta.
  * **Card de Lançamento de Movimentação:**
    * Formulário com Seletor de Tipo: `Entrada (+)` [compra/recebimento], `Saída (-)` [consumo avulso], `Ajuste / Correção (+)` [acerto de inventário].
    * Quantidade a movimentar.
    * Justificativa / Nota (número de nota fiscal, ordem de compra ou destino).
    * Botão "Lançar Movimento" que atualiza instantaneamente o saldo e o histórico.
  * **Linha do Tempo de Movimentações:**
    * Extrato cronológico com marcadores de cores (verde para entradas, vermelho para saídas, azul para ajustes), quantidade debitada/creditada, data/hora e justificativa.

---

### 17. Estoque & Insumos — Categorias de Insumos & Schemas Técnicos *(RECURSO NO CÓDIGO)*
* **Componente:** [`StockCategoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/category-list/category-list.component.ts)
* **Status Atual:** **Implementado no código (860 linhas de código completo), porém atualmente sem rota em `app.routes.ts` e sem botão de atalho na interface de estoque.** *(Ver seção de funções removidas/ocultas)*.
* **O que a tela faz:**
  Permite cadastrar categorias de materiais (ex: Periféricos, Cabos, Toners, Peças) e definir presets e campos dinâmicos de especificações técnicas para os insumos.

---

### 18. Inventário Periódico — Painel de Auditorias
* **Rota:** `/inventory`
* **Componente:** [`InventoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/inventory/inventory-list/inventory-list.component.ts)
* **Controle de Acesso:** `inventory.read`.
* **O que faz no sistema:**
  Gestão de campanhas de conferência física cega ou assistida de ativos e insumos em cada unidade da empresa para compliance e prevenção de extravios.
* **Elementos da Página:**
  * Cabeçalho com botão "Nova Auditoria" (abre dialog para nomear a conferência, escolher a unidade e designar o auditor responsável).
  * Barra de filtro por nome, unidade ou status.
  * Tabela de Auditorias:
    * **Nome da Auditoria:** Título da campanha.
    * **Unidade:** Filial ou sede auditada.
    * **Status:** Badges para `Aberta` (aguardando início), `Em Andamento` (conferência ativa), `Concluída` (fechada) e `Cancelada`.
    * **Datas:** Data de abertura e data de encerramento.
    * **Ações:** Botão para acessar a mesa de auditoria item a item (`/inventory/:id`).

---

### 19. Inventário Periódico — Execução e Apuração de Auditoria
* **Rota:** `/inventory/:id`
* **Componente:** [`InventoryDetailComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/inventory/inventory-detail/inventory-detail.component.ts)
* **Controle de Acesso:** `inventory.read` / `inventory.write`.
* **O que faz no sistema:**
  Mesa operacional onde o auditor realiza a checagem física item por item contra o cadastro contábil do sistema e consolida as sobras e faltas.
* **Elementos da Página:**
  * **Barra de Gestão de Ciclo da Auditoria:**
    * Informações da unidade e auditor responsável.
    * Botão "Iniciar Auditoria" (muda status para `IN_PROGRESS`).
    * Botão "Povoar Itens da Unidade": Consulta automática do banco de dados trazendo todos os ativos e insumos alocados naquela unidade como lista-base de contagem.
    * Botão "Encerrar Auditoria": Trava a conferência e consolida o relatório.
    * Botão "Cancelar Auditoria".
  * **Formulário de Conferência / Adição de Item:**
    * Seleção do tipo (Ativo ou Insumo).
    * Identificação do item, status físico real encontrado, quantidade real e notas do auditor.
  * **Tabela de Apuração / Conformidade:**
    * Colunas: Item Auditado, Esperado (cadastro contábil), Real (encontrado em campo), Notas e Resultado de Conformidade (`Em Conformidade`, `Divergente`, `Não Encontrado / Extraviado`).

---

### 20. Organização — Unidades
* **Rota:** `/organization`
* **Componente:** [`UnitList`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/unit-list/unit-list.component.ts)
* **Controle de Acesso:** `organization.units.read`.
* **O que faz no sistema:**
  Cadastro das filiais, polos, sedes e escritórios regionais da empresa.
* **Elementos da Página:**
  * Tabela contendo Código da Unidade, Razão Social/Nome da Unidade, Status (`Ativo`/`Inativo`) e Ações.
  * Botão "Nova Unidade" que dispara o modal [`UnitDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/unit-list/unit-dialog.component.ts).
  * Ações de Edição e Inativação com confirmação de segurança.

---

### 21. Organização — Setores
* **Rota:** `/organization/sectors`
* **Componente:** [`SectorList`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/sector-list/sector-list.component.ts)
* **Controle de Acesso:** `organization.sectors.read`.
* **O que faz no sistema:**
  Cadastro dos setores, departamentos e centros de custo pertencentes a cada unidade (ex: RH, Financeiro, Engenharia, Suporte).
* **Elementos da Página:**
  * Tabela com Unidade Vinculada, Código do Setor, Nome do Setor, Status e Ações.
  * Modal [`SectorDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/sector-list/sector-dialog.component.ts) para criação/edição.
  * Ações de edição e inativação segura.

---

### 22. Organização — Colaboradores
* **Rota:** `/organization/employees`
* **Componente:** [`EmployeeList`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/employee-list/employee-list.component.ts)
* **Controle de Acesso:** `organization.employees.read`.
* **O que faz no sistema:**
  Cadastro dos funcionários da empresa, guardiões de patrimônio e solicitantes de suporte.
* **Elementos da Página:**
  * Tabela contendo: Setor, Matrícula Funcional (`REG`), Nome Completo, Telefone/WhatsApp (usado pelo bot), Cargo e Status.
  * Modal [`EmployeeDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/organization/employee-list/employee-dialog.component.ts) para inclusão/edição.
  * Ações de edição e inativação.

---

### 23. Identidade e Segurança — Gestão de Usuários
* **Rota:** `/identity/users`
* **Componente:** [`UserList`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/identity/user-list/user-list.component.ts)
* **Controle de Acesso:** `identity.users.read`.
* **O que faz no sistema:**
  Gerenciamento de contas de login de operadores do sistema, vínculo com colaboradores e atribuição de perfis de permissão.
* **Elementos da Página:**
  * Tabela com: E-mail de login, Perfis (Roles) atribuídos, Badge Administrador, Status de Ativação e Coluna de Ações.
  * Modal [`UserDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/identity/user-list/user-dialog.component.ts) para cadastrar usuário com vinculação a colaborador existente e seleção de perfil.
  * **Ação de Reset de Senha:** Botão que redefine a senha do operador para uma senha temporária padronizada e obriga a alteração no próximo login (`must_change_password`).
  * Ação de Inativação de conta.

---

### 24. Identidade e Segurança — Perfis (Roles & Matriz RBAC)
* **Rota:** `/identity/roles`
* **Componente:** [`RoleList`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/identity/role-list/role-list.component.ts)
* **Controle de Acesso:** `identity.roles.read`.
* **O que faz no sistema:**
  Configuração de perfis de acesso personalizados e vinculação de permissões granulares do sistema.
* **Elementos da Página:**
  * Tabela com Nome do Perfil, Descrição e Chips das permissões concedidas.
  * Modal [`RoleDialogComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/identity/role-list/role-dialog.component.ts) para criação/edição com seleção por caixas de seleção de cada uma das 35 permissões granulares.
  * Ações de edição e exclusão.

---

### 25. Central de Administração do Sistema
* **Rota:** `/admin`
* **Componente:** [`AdminComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/admin/admin.component.ts)
* **Controle de Acesso:** `identity.roles.read` (Restrito a Administradores).
* **O que faz no sistema:**
  Painel de controle unificado com 7 macro-módulos integrados em abas para manutenção, segurança, integrações e governança de dados.

#### Aba 1: WhatsApp & Suíte Anti-Ban
* **Sub-Aba Conexão & Gateway:**
  * Seletor de Gateway (`Evolution API`, `Meta Cloud API` ou `Mock` de desenvolvimento).
  * Status da Integração (Toggle liga/desliga).
  * Live Connection State Banner: Exibe em tempo real o estado da conexão (`CONNECTED`, `DISCONNECTED`, `FAILED`), botão "Verificar" e botão "Conectar WhatsApp (QR Code)" que abre popup para escanear a sessão do WhatsApp Web diretamente na tela.
  * Campos de API URL, Nome da Instância e Mensagem de Boas-vindas.
  * Ferramenta de Envio de Mensagem de Teste imediato.
* **Sub-Aba 🛡️ Escudo Anti-Ban & Cadência:**
  * **Kill Switch de Emergência:** Interruptor vermelho que cessa instantaneamente qualquer disparo em massa sem perder mensagens na fila.
  * Ativação do Escudo Anti-Ban.
  * Intervalo humanizado com variação randômica (jitter) entre envios (`min_delay_seconds` e `max_delay_seconds`).
  * Emulação de presença humana via status `"digitando..."` antes do envio.
  * Controle de cadência máxima por minuto e tempo de resfriamento (cooldown) por destinatário para não saturar o mesmo colaborador.
* **Sub-Aba Templates & Respostas Rápidas:**
  * Cadastro e edição de templates categorizados por módulo (`SERVICE_DESK`, `NOTIFICATIONS`, `GENERAL`).
  * Suporte a interpolação de tags contextuais: `{{solicitante}}`, `{{protocolo}}`, `{{titulo}}`, `{{status}}`, `{{atendente}}`, `{{unidade}}`, `{{observacao}}`, `{{empresa}}`.
  * **Simulador Interativo estilo WhatsApp:** Mock chat visual em tempo real que exibe os balões de conversa idênticos ao aplicativo mobile conforme o operador digita o template.
* **Sub-Aba Monitor da Fila Outbox:**
  * Painel ao vivo com contadores de mensagens `Pendentes`, `Enviando`, `Enviadas`, `Falhas` e `Canceladas`.
  * Tabela com histórico de envios, botão de cancelamento de itens pendentes e botão de reprocessamento imediato de falhas.

#### Aba 2: Importação de Dados CSV
* Assistente Wizard em 3 passos progressivos:
  * **Passo 1:** Seleção da Entidade a importar (Colaboradores, Ativos Patrimoniais ou Insumos de Estoque) e upload do arquivo `.csv`.
  * **Passo 2:** Detecção automática de delimitador (`;` ou `,`) e codificação (UTF-8, Latin-1), seletor de política de duplicidades (`Pular registro existente`, `Atualizar registro existente` ou `Abortar com erro`), e mapeamento de colunas (vincula cada coluna da planilha ao campo correspondente do sistema).
  * **Passo 3:** Pré-visualização das 5 primeiras linhas em tabela, botão de **Simulação Prévia (Dry Run)** que testa validações sem salvar no banco, e botão de Execução Real com relatório de sucessos e linhas com inconsistência.

#### Aba 3: Exportação de Dados CSV
* Sanitização automática contra vulnerabilidade de *CSV Formula Injection* (prefixa caracteres perigosos `=`, `+`, `-`, `@` com apóstrofo).
* Seleção da entidade (Chamados, Ativos, Estoque, Colaboradores, Auditorias).
* Filtro por intervalo de datas.
* Escolha do delimitador (`;` formatado para Microsoft Excel no Brasil ou `,` para padrão internacional).
* Injeção de marca de ordem de byte UTF-8 BOM (`\xef\xbb\xbf`) garantindo abertura perfeita de caracteres acentuados no Excel.

#### Aba 4: Backups do Banco de Dados
* Criação sob demanda de snapshot nativo do PostgreSQL compactado em `.sql.gz`.
* Geração e gravação do Hash criptográfico SHA-256 para cada arquivo para auditoria de integridade física.
* Tabela de histórico de backups com tamanho formatado (KB/MB), data/hora, autor e hash.
* Rota de download autenticado de backups.
* Exclusão de backups antigos com confirmação.
* Guia de restauração via terminal (disaster recovery).

#### Aba 5: Perfis & Matriz RBAC
* Visão didática e comparativa dos 4 perfis nativos: Administrador (35 permissões), Gestor (13 permissões), Atendente (7 permissões) e Solicitante (2 permissões).
* Atalhos rápidos para gerenciamento granular em `/identity/roles` e `/identity/users`.

#### Aba 6: Ambientes & Dados (Gestão Demo e Limpeza Segura)
* Exibe o status atual do ambiente (Produção vs Demonstração).
* Contadores de dados fictícios gerados.
* **Limpeza Segura de Dados de Demonstração:**
  * Exige verificação prévia de que existe backup recente no banco.
  * Trava de segurança: exige a digitação exata da frase de confirmação `LIMPAR DADOS DE DEMONSTRACAO` para habilitar o botão.
  * Realiza a purga cirúrgica de dados de teste (chamados, ativos fictícios, insumos fictícios), **preservando integralmente** contas de administradores, permissões, configurações de sistema e parametrizações de SMTP/WhatsApp.

#### Aba 7: Servidor de E-mail (SMTP)
* Configurações de conexão: Host, Porta (587 TLS / 465 SSL / 25), Usuário, Senha, E-mail do Remetente e Nome de Exibição.
* Toggle de ativação do envio de notificações por e-mail.
* Botão de envio de e-mail de teste para validação imediata da caixa postal.
* Cumprimento estrito da regra de privacidade DEC-012 (notas internas nunca são despachadas por e-mail para solicitantes).

---

## 🔍 Funções e Recursos: Histórico, Alterações e Recursos Ocultos no Código

Durante a varredura minuciosa do código-fonte e do histórico de versionamento (git), foram identificados os seguintes comportamentos, decisões técnicas e componentes órfãos ou modificados:

| Recurso / Função | Situação Identificada | Detalhes Técnicos & Localização no Código |
| :--- | :--- | :--- |
| **Categorias de Estoque & Insumos** | **Criado no Código, mas sem Rota e sem Menu** | O componente [`StockCategoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/category-list/category-list.component.ts) foi totalmente desenvolvido no commit `70b2384` (860 linhas de código com CRUD, presets de periféricos/cabos/toners e campos dinâmicos). No entanto, **não foi adicionada a rota `stock/categories` em `app.routes.ts` nem o botão na barra lateral ou na tela de estoque**. O recurso existe e funciona no backend, mas está invisível para os usuários na interface. |
| **Categorias de Ativos** | **Havia sumido e foi restaurada** | No commit `864af3e`, a tela de Categorias de Ativos havia ficado inacessível e foi restaurada com a criação da rota `/assets/categories` e adição do botão correspondente na listagem de ativos e na barra lateral. |
| **Harmonização do Ciclo de Vida de Ativos** | **Funções duplicadas removidas** | No commit `a544af7`, métodos legados `getStatusBadgeClass` e `getStatusLabel` em `AssetDetailComponent` foram removidos e harmonizados, pois não contemplavam os status novos do ciclo de vida (`RESERVED` e `PENDING_INSPECTION`), gerando inconsistências visuais nos badges. |
| **Exclusão de Registros Organizacionais (Soft Delete)** | **Funções de Delete Físico substituídas por Inativação** | Nas telas de Unidades, Setores, Colaboradores e Usuários, os botões de ação excluem de forma lógica (`is_active = False`) em vez de deletar linhas do PostgreSQL. Isso foi implementado para proteger a integridade referencial com chamados antigos e termos de responsabilidade já emitidos. |
| **Autoatendimento de Ativos para Solicitantes** | **Permissão adaptada no fluxo** | Originalmente, para vincular um ativo na abertura de chamado, o usuário precisava da permissão `assets.read`. Como solicitantes não possuem essa permissão, foi criado o endpoint restrito `GET /api/v1/assets/me`, permitindo que o usuário visualize e vincule apenas os equipamentos sob sua própria guarda. |
| **Salvaguarda de Limpeza Demo** | **Trava de segurança implementada** | O botão de exclusão de dados demo não executa diretamente: ele fica desabilitado até que o operador digite a string exata `LIMPAR DADOS DE DEMONSTRACAO` e tenha ao menos 1 backup de banco gerado no histórico. |
| **Emissão de Termo sem Assinatura Digital** | **Fluxo físico + digital integrado** | O sistema não obriga a compra de certificados ICP-Brasil: permite emitir o termo formal padronizado em HTML para impressão física ou download em PDF, e disponibiliza o campo de upload para anexar o termo assinado digitalmente (Clicksign, Gov.br) ou escaneado. |

---

## 📊 Matriz Consolidada de Rotas e Navegação

| Rota no Navegador | Componente Angular Principal | Menu na Barra Lateral | Permissão Necessária | Perfil Típico de Acesso |
| :--- | :--- | :--- | :--- | :--- |
| `/setup` | `SetupComponent` | *Oculto (Só abre sem admin)* | Nenhuma (guard de setup) | Instalador / Primeiro Admin |
| `/login` | `LoginComponent` | *Oculto (Tela pública)* | Nenhuma (guestGuard) | Todos os usuários |
| `/change-password` | `ChangePasswordComponent` | Menu do Usuário (Topo) | Autenticado | Todos os usuários |
| `/dashboard` | `Dashboard` | Principal > Dashboard | Autenticado | Todos (visão adaptada) |
| `/service-desk` | `TicketListComponent` | Service Desk > Chamados | Autenticado | Todos (visão adaptada) |
| `/service-desk/new` | `TicketCreateComponent` | Service Desk > Abrir Chamado | `service_desk.tickets.create` | Todos os perfis |
| `/service-desk/:id` | `TicketDetailComponent` | *Sub-rota direta de chamado* | Acesso ao chamado | Solicitante e Atendentes |
| `/service-desk/categories` | `CategoryListComponent` | Service Desk > Categorias | `service_desk.tickets.manage` | Técnicos e Administradores |
| `/assets` | `AssetListComponent` | Operações > Patrimônio & Ativos | `assets.read` | Técnicos, Gestores e Admin |
| `/assets/new` | `AssetCreateComponent` | Botão em `/assets` | `assets.write` | Técnicos e Administradores |
| `/assets/:id` | `AssetDetailComponent` | *Sub-rota direta do ativo* | `assets.read` | Técnicos, Gestores e Admin |
| `/assets/categories` | `AssetCategoryListComponent` | Operações > Categorias de Ativos | `assets.read` | Técnicos e Administradores |
| `/stock` | `StockListComponent` | Operações > Estoque & Insumos | `stock.read` | Técnicos, Gestores e Admin |
| `/stock/new` | `StockCreateComponent` | Botão em `/stock` | `stock.write` | Técnicos e Administradores |
| `/stock/:id` | `StockDetailComponent` | *Sub-rota direta do item* | `stock.read` | Técnicos, Gestores e Admin |
| *`/stock/categories`* | `StockCategoryListComponent` | *(Oculto no código - Sem rota)* | `stock.write` *(Recomendada)* | *(Técnicos e Administradores)* |
| `/inventory` | `InventoryListComponent` | Operações > Inventário Periódico | `inventory.read` | Gestores e Administradores |
| `/inventory/:id` | `InventoryDetailComponent` | *Sub-rota direta da auditoria* | `inventory.read` | Auditores e Gestores |
| `/organization` | `UnitList` | Organização > Unidades | `organization.units.read` | Administradores e Gestores |
| `/organization/sectors` | `SectorList` | Organização > Setores | `organization.sectors.read` | Administradores e Gestores |
| `/organization/employees` | `EmployeeList` | Organização > Colaboradores | `organization.employees.read` | Administradores e Gestores |
| `/identity/users` | `UserList` | Administração > Usuários | `identity.users.read` | Administradores |
| `/identity/roles` | `RoleList` | Administração > Perfis (Roles) | `identity.roles.read` | Administradores |
| `/admin` | `AdminComponent` | Administração > Painel Administrativo | `identity.roles.read` | Administradores |

---

## 💡 Recomendações e Próximos Passos Sugeridos

1. **Ativação da Rota de Categorias de Estoque:**
   Como a tela [`StockCategoryListComponent`](file:///c:/Projetos/plataforma-gestao-ti/frontend/src/app/features/stock/category-list/category-list.component.ts) já está 100% implementada no frontend com suporte a schemas de especificações técnicas, recomenda-se adicionar a rota `{ path: 'stock/categories', ... }` em `app.routes.ts`, adicionar o botão no cabeçalho de `StockListComponent` e incluir o link na `SidebarComponent`.
2. **Uso deste Documento:**
   Este arquivo `Oque_tem_gestao_ti.md` serve como referência arquitetural e operacional para homologação, treinamento de operadores e suporte a novos desenvolvimentos.
