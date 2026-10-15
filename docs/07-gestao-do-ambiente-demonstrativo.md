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
3. O serviço injeta um conjunto coeso e consistente contendo:
   * 1 Empresa Modelo (`Empresa Modelo Demonstração S.A.`);
   * 2 Unidades operacionais (Matriz Curitiba e Filial São Paulo);
   * 8 Setores organizacionais (TI, RH, Financeiro, Vendas, etc.);
   * 8 Contas de usuários e colaboradores com cargos e ramais fictícios;
   * 16 Categorias de chamados com formulários dinâmicos;
   * 10 Ativos de hardware (notebooks, desktops, switches) com números de série e notas fiscais simuladas;
   * 10 Chamados em diferentes estágios (Aberto, Em Atendimento, Pendente, Resolvido).
4. A carga é **idempotente**: executá-la repetidas vezes atualiza os registros existentes sem gerar duplicidades ou conflitos de chave primária.
