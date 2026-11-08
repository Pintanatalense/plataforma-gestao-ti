# MOD-04: Service Desk

> Estado real e dono das regras: ver [mapa lógico](../architecture/mapa-logico-gero.md).

## Visão Geral
O módulo **Service Desk** é responsável por centralizar e gerenciar as solicitações de suporte, incidentes e dúvidas dos colaboradores da organização. Ele serve como o canal oficial de comunicação entre os usuários finais e a equipe de TI, permitindo um acompanhamento claro de status, prazos (SLAs) e histórico de resoluções.

## Entidades Principais

### 1. Chamado (`Ticket`)
Representa a solicitação central ou o incidente reportado.
- **Campos Principais:** Título, Descrição, Prioridade, Status, Data de Abertura, Data de Fechamento.
- **Relacionamentos:**
  - `requester_id` (Colaborador - MOD-02): Quem abriu o chamado.
  - `assignee_id` (Usuário/Técnico - MOD-03): Membro da TI responsável pelo atendimento.
  - `category_id`: Categoria do problema para facilitar triagem (ex: Rede, Hardware, Software).

### 2. Interação de Chamado (`TicketInteraction`)
Representa a linha do tempo e o histórico de comunicação de um chamado.
- **Campos Principais:** Mensagem, Autor, Data, Flag de Visibilidade (Público vs. Interno).

## Ciclo de Vida (Status do Chamado)
Os chamados seguirão, por padrão, a seguinte máquina de estados de status:
1. **Aberto (Opened):** Chamado recém-criado pelo colaborador; ainda não atribuído.
2. **Em Andamento (In Progress):** Um técnico assumiu a responsabilidade e está investigando/trabalhando na solução.
3. **Aguardando (Pending):** A TI está aguardando retorno do colaborador solicitante, ou dependência de terceiros (ex: fornecedor). O SLA geralmente é pausado neste estado.
4. **Resolvido (Resolved):** O técnico forneceu a solução, aguardando validação automática ou manual do fechamento.
5. **Fechado (Closed):** Chamado encerrado definitivamente. Não aceita novas interações.

## Regras de Negócio e Segurança
1. **Isolamento de Visão (Colaborador):** Usuários com papel padrão (não-técnicos) só podem visualizar chamados onde eles mesmos constem como solicitantes.
2. **Visão Técnica (Técnico/Gestor):** Usuários com permissões da TI podem visualizar todos os chamados da empresa ou das unidades as quais têm acesso.
3. **Interações (Publicas vs Internas):** Interações podem ser marcadas como internas. Elas ficarão visíveis estritamente para a equipe técnica. Ver `DEC-012` para detalhes.

## Integrações (Dependências)
- **MOD-02 (Organização):** Identificação dos departamentos e filiais afetados, assim como a matriz do funcionário (colaborador) solicitante.
- **MOD-03 (Identidade):** Controle de Acesso (técnicos vs colaboradores).
- **MOD-05/06 (Ativos):** O chamado pode ser vinculado a ativos de TI (tabela `sd_ticket_assets`; ver `DEC-006`).
- **MOD-10 (Anexos):** Envio de arquivos ao chamado, com anexo restrito ao setor que atende (ver ADR-026).
