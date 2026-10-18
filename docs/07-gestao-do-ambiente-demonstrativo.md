# 07. Gestão do Ambiente Demonstrativo e Limpeza Segura

Este guia aborda os mecanismos de alternância entre o **Ambiente Demonstrativo (Demo)** e o **Ambiente Empresarial (Produção)**, detalhando o funcionamento do botão de limpeza segura e da recarga idempotente.

---

## 1. Princípios de Separação de Ambientes

Para evitar que dados fictícios sejam confundidos com dados reais da empresa contratante:
1. **Identificação Explícita:** Todas as tabelas operacionais possuem o discriminador booleano `is_demo`.
2. **Sinalização Visual:** Sempre que o sistema estiver no modo `DEMO`, um selo dourado em destaque (**AMBIENTE DEMO**) é exibido no cabeçalho superior para todos os usuários logados.
3. **Classificação Estrita:** O sistema não realiza deleções genéricas (`TRUNCATE` ou `DELETE` sem filtro). Configurações e cadastros reais são catalogados separadamente.

---

## 2. Indicadores do Diagnóstico de Dados

Acessando **Administração > Ambientes & Dados**, o administrador visualiza em tempo real:
* **Modo Atual do Sistema:** `DEMO` ou `PRODUCTION`.
* **Quantitativo de Registros de Demonstração:** Contagem precisa por tabela (`sd_ticket`, `assets`, `stk_items`, `employees`, `user_accounts`, `sectors`, `units`, `companies`).
* **Garantia de Recuperação (Status do Backup):** Valida se existe um backup íntegro gerado recentemente.

---

## 3. Botão "Limpar Dados de Demonstração"

A funcionalidade **“Limpar dados de demonstração”** prepara o sistema para uma nova empresa sem a necessidade de reinstalação da infraestrutura.

### 3.1. Requisitos de Segurança Obrigatórios
* **Controle de Acesso:** Exclusivo para usuários com a permissão administrativa `system.backup.manage`.
* **Bloqueio por Falta de Backup:** Se não houver nenhum backup recente utilizável no diretório `/data/backups/`, o botão de limpeza é **bloqueado automaticamente**.
* **Pré-Visualização do Impacto:** Um modal apresenta detalhadamente quais registros serão removidos e quais serão preservados.
* **Confirmação Dupla Obrigatória:** O administrador deve digitar exatamente a frase de segurança:
  ```text
  LIMPAR DADOS DE DEMONSTRACAO
  ```
* **Log de Auditoria:** O evento `system.demo.cleaned` é registrado de forma indelével na auditoria com data, hora, IP de origem e identificação do administrador.

### 3.2. Mecânica Interna da Limpeza Segura
A operação executa uma transação atômica que:
1. Valida a existência e legibilidade do último backup.
2. Desassocia o `employee_id` da conta do administrador principal, garantindo que o login continue funcionando perfeitamente.
3. Desvincula relacionamentos auto-referenciais (`manager_id` em colaboradores e `default_sector_id` em categorias).
4. Remove os arquivos físicos de anexos vinculados a chamados de demonstração.
5. Exclui em cascata controlada apenas os registros marcados com `is_demo = True`.
6. **Preserva rigorosamente:**
   * Usuários administradores (`UserAccount` onde `is_demo = False`);
   * Parâmetros do sistema (`system_settings`), incluindo credenciais SMTP e chaves de WhatsApp;
   * Trilha de auditoria (`audit_logs`);
   * Histórico de backups (`database_backups`).
7. Atualiza o parâmetro `system_mode` para `PRODUCTION`.

---

## 4. Recarga de Dados Demonstrativos (Seed)

Caso a empresa queira utilizar o sistema para treinar novos técnicos ou realizar demonstrações para a diretoria:

1. Acesse **Administração > Ambientes & Dados**.
2. Clique no botão **Recarregar Dados Demonstrativos**.
3. O serviço injeta um conjunto de exemplo (todos marcados `is_demo`):
   * 1 empresa de exemplo (`TechCorp Soluções Empresariais Ltda.`) e a unidade "Filial Operacional - RN"; a **Matriz** criada na instalação é a unidade real e não é marcada como exemplo;
   * 8 setores de exemplo (Financeiro, Comercial, Diretoria, RH, Administrativo, Operacional, Manutenção, TI);
   * 8 colaboradores com contas de exemplo (senha `Demo@2026`; só para conhecer) e o colaborador do administrador;
   * 5 ativos (notebooks) com garantias variadas, duas perto de vencer;
   * 5 insumos de estoque, três no mínimo ou abaixo (alimentam o alerta de estoque baixo);
   * 6 chamados em vários estágios (aberto, em atendimento, pendente, resolvido, encerrado) para o setor de TI de exemplo.
   Os chamados são gravados direto, sem disparar notificações.
4. Recarregar apaga o exemplo anterior (com a mesma proteção de backup da limpeza) e cria de novo, sem duplicar.
5. O **catálogo inicial** (setor de TI e categorias de chamado e de ativo, criado no assistente) nunca é tratado como exemplo: ao limpar, as categorias voltam a apontar para o setor de TI real.
