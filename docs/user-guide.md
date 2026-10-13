# Manual de Operação e Guia do Usuário — Plataforma de Gestão de TI

Este guia orienta os usuários e operadores do sistema sobre as funcionalidades, papéis de acesso e os principais fluxos de trabalho da plataforma.

---

## 👥 1. Perfis de Acesso e Responsabilidades

| Perfil | Descrição e Escopo |
|---|---|
| **Colaborador** | Abre chamados de suporte técnico, acompanha o status das suas solicitações, interage via chat público do ticket e visualiza os ativos sob sua responsabilidade. |
| **Técnico de Suporte** | Atende a fila de chamados, envia mensagens públicas e notas internas, associa ativos e materiais consumidos ao ticket, registra movimentações de equipamentos e consulta estoque. |
| **Gestor de TI** | Visualiza métricas gerais no Dashboard, aprova movimentações e descarte de patrimônio, gerencia cotas de estoque e agenda inventários periódicos. |
| **Administrador** | Acesso irrestrito a todas as áreas, incluindo cadastro da organização (empresa, unidades, setores), governança de identidades (criação de usuários e perfis/RBAC) e auditoria geral do sistema. |

---

## 🎫 2. Fluxo: Service Desk (Gestão de Chamados)

### 2.1 Abertura de Chamado (Colaborador / Técnico)
1. Acesse o menu lateral em **Service Desk > Chamados**.
2. Clique no botão **Novo Chamado** (ou use o atalho rápido no **Dashboard**).
3. Preencha o título do problema, descrição detalhada, nível de prioridade (*Baixa, Média, Alta ou Crítica*) e selecione a categoria correspondente.
4. Clique em **Salvar** para registrar o ticket na fila de triagem.

### 2.2 Atendimento e Interações (Técnico)
1. Na listagem de chamados, clique no ícone de visualização do ticket desejado.
2. Na tela de atendimento estilo chat:
   - **Mensagens Públicas:** Visíveis para o solicitante do chamado e para a equipe técnica.
   - **Notas Internas (Lock):** Visíveis estritamente para a equipe técnica e administradores, ideais para pareceres técnicos, diagnósticos e orçamentos.
3. Atualize o status do chamado (*Em Atendimento, Pendente, Resolvido ou Fechado*) conforme o progresso.
4. Faça upload de arquivos, logs ou prints na aba de **Anexos**.

---

## 💻 3. Fluxo: Gestão Patrimonial e Ativos

### 3.1 Cadastrar Novo Ativo
1. Acesse **Operações & Físico > Patrimônio & Ativos**.
2. Clique em **Novo Ativo**.
3. Informe a Tag de Patrimônio (ex: `PAT-1020`), o nome do equipamento e selecione a categoria.
   - *Nota:* As especificações técnicas em JSONB (ex: CPU, Memória RAM, Armazenamento, SO) são carregadas dinamicamente de acordo com o esquema da categoria selecionada.
4. Escolha a unidade física e, se aplicável, o colaborador responsável.
5. Clique em **Salvar Ativo**.

### 3.2 Movimentações e Linha do Tempo
1. Acesse o detalhe do ativo clicando em **Ver Detalhes**.
2. Na aba **Histórico de Movimentações**, confira todas as transições de posse e status registradas automaticamente.
3. Tipos de movimentação suportados pela API:
   - **Atribuição (Assignment):** Entrega do ativo a um colaborador responsável.
   - **Devolução (Return):** Retorno do ativo para estoque disponível.
   - **Transferência (Transfer):** Mudança de unidade física ou troca de colaborador.
   - **Manutenção (Maintenance):** Envio para conserto ou reparo técnico.
   - **Baixa (Decommission):** Descarte ou sucateamento do equipamento.

---

## 📦 4. Fluxo: Estoque e Insumos

### 4.1 Cadastro de Insumos
1. Acesse **Operações & Físico > Estoque & Insumos**.
2. Clique em **Novo Item** e informe o nome (ex: *Teclado USB, Patch Cord Cat6 2m*), a unidade física e a cota mínima de alerta (`min_quantity`).
3. Informe a quantidade inicial em estoque.

### 4.2 Lançamento de Movimentação de Estoque
1. Na lista de insumos, clique no ícone de ajuste do item desejado.
2. Na coluna **Registrar Movimentação**:
   - Selecione o tipo: **Entrada (+)**, **Saída (-)** ou **Ajuste / Correção (+)**.
   - Digite a quantidade e a justificativa/nota fiscal.
   - Clique em **Lançar Movimento**.
3. O saldo é atualizado imediatamente e registrado na linha do tempo do insumo.

---

## 📋 5. Fluxo: Inventário Periódico

1. Acesse **Operações & Físico > Inventário Periódico**.
2. Clique em **Nova Auditoria**: defina o título da auditoria, a unidade física e o auditor responsável.
3. Abra a auditoria criada e clique em **Iniciar Auditoria**.
4. Conforme a checagem presencial ou por leitor de código de barras:
   - Clique em **Adicionar Item à Conferência**.
   - Selecione o Ativo ou Insumo e registre o status real encontrado ou a quantidade física contada.
   - O sistema classifica automaticamente os itens em **Conforme** ou **Divergente**.
5. Ao concluir a verificação de todos os itens da unidade, clique em **Finalizar Auditoria** para consolidar o relatório.

---

## ⚙️ 6. Administração e Governança

* **Unidades e Setores:** Cadastre a matriz e filiais em **Organização > Unidades** e crie os departamentos em **Organização > Setores**.
* **Colaboradores:** Gerencie os funcionários da empresa e seus vínculos contratuais em **Organização > Colaboradores**.
* **Usuários do Sistema:** Em **Segurança & Acessos > Usuários**, vincule colaboradores a contas de acesso (`email`/`senha`) e determine se possuem privilégios de Administrador.
* **Perfis (Roles) e Permissões:** Em **Segurança & Acessos > Perfis**, customize grupos de permissão (ex: *Técnico N1*, *Gestor Predial*) com controle fino de permissões de leitura/escrita por módulo.
* **Primeiro Acesso:** Usuários cadastrados com `must_change_password=True` são redirecionados automaticamente para a tela de troca de senha no primeiro login.
