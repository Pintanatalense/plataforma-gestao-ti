# ADR-026 — Chamados vinculados: principal e subchamados para vários setores

**Status:** Aceito; implementado em partes.
- **Feito:** 2a (vínculo, cancelamento, substituição, obrigatoriedade e avisos), 2b (idempotência), 2c (indicadores de SLA), 3 (anexos restritos), 4 (modelos de atendimento) e 5 (telas).
**Data:** 2026-11-05
**Depende de:** criador do chamado e direcionamento por categoria (PR 1 da série), ADR-013 (outbox e notificações),
ADR-017 (SLA).

## Contexto

Um processo que envolve vários departamentos hoje vira chamados soltos, sem acompanhamento consolidado. Exemplos:
uma admissão, uma compra ou uma mudança de sala.

O pedido é um mecanismo **genérico**:
- qualquer chamado principal gera N subchamados;
- cada subchamado pode ter qualquer categoria e ir para qualquer setor autorizado;
- o solicitante acompanha tudo;
- cada setor trabalha isolado.

Nenhuma regra de processo específico entra no código.

## Decisão

### Vínculo

**Colunas novas em `sd_ticket`:**
- `parent_ticket_id`: FK para o próprio `sd_ticket`, `ON DELETE RESTRICT`, indexada. Uma `CHECK` impede o chamado de
  ser pai de si mesmo.
- `is_required`: etapa obrigatória, padrão `true`.
- `replaces_ticket_id`: aponta para a etapa cancelada que este subchamado substitui.

**Regras do vínculo:**
- **Um nível só.** Um subchamado não tem subchamados.
- **O filho é um chamado comum**, com fila, responsável, status, SLA, histórico e auditoria próprios.
- **O filho herda do principal** o solicitante e a origem.
- **O criador do filho** é quem o acrescentou.

**Criação.** Os filhos passam pelo mesmo núcleo de criação do chamado comum:
- direcionamento por categoria, com `route_any_sector` para usar outro setor;
- formulário da categoria;
- SLA;
- auditoria e outbox.

**Pontos de entrada:**
- `POST /tickets` com `children`;
- `POST /tickets/{id}/children` depois da abertura, permitido ao solicitante, ao criador e ao setor do principal.

Cada lote é uma transação: um filho inválido desfaz tudo.

**Trava.** A inclusão de filhos e o encerramento do principal fazem `SELECT … FOR UPDATE` na linha do principal antes
de validar:
- inclusão depois do encerramento: 409;
- encerramento depois da inclusão: vê o filho novo pendente e é recusado.

### Encerramento, cancelamento e obrigatoriedade

**Encerramento do principal.** O principal só vai para `RESOLVED` ou `CLOSED` sem etapa obrigatória pendente. Uma
etapa pendente é qualquer filho obrigatório fora de `RESOLVED` e `CLOSED`, **inclusive cancelado**. Não há fechamento
automático, só aviso.

**`CANCELED`.** É um status terminal, só para subchamados nesta versão.
- **Rota:** `POST /tickets/{id}/cancel`.
- **Justificativa:** obrigatória, com 10 caracteres ou mais. Fica gravada como interação pública no filho.
- **Quem cancela:** o setor do filho, ou o setor do principal.
- **Cancelamento por outro departamento.** O setor do principal pode cancelar uma etapa de outro departamento, porque
  é ele quem administra o processo. Essa é uma decisão consciente, com três condições:
  - a justificativa é sempre exigida;
  - quem cancelou e o setor dele ficam na auditoria;
  - o setor do filho é avisado.

  Fora isso, o setor do principal não ganha nenhum poder sobre o filho: não lê notas internas, não altera e não atribui.
- **Dois eventos:**
  - `ticket.canceled`, no filho, vai ao responsável e ao setor do filho;
  - `ticket.child_canceled`, no principal, vai ao responsável, ao solicitante e ao criador do principal.
- **SLA:** o ciclo aberto termina como `CANCELED`, fora dos indicadores de cumprimento.

**Destravar uma etapa obrigatória cancelada.** Só o setor do principal decide, e há dois caminhos. Os dois preservam
todo o histórico.
- **Substituir** (`POST /tickets/{id}/replace`): cria um filho novo e obrigatório com `replaces_ticket_id`. O cancelado
  continua `CANCELED`, com interações e auditoria intactas, e passa a não obrigatório com o motivo "substituído por #N".
  Só um filho cancelado e ainda não substituído pode ser substituído.
- **Dispensar** (`PATCH /tickets/{id}/requirement`): torna a etapa não obrigatória, com justificativa. A mesma rota
  torna uma etapa obrigatória de novo, exceto uma cancelada.

**Progresso.** `children_progress` traz `total`, `done`, `canceled`, `required_pending` e `overdue`. Vem no detalhe do
principal e em `GET /tickets/{id}/children`.

### Quem vê e quem faz o quê (`service_desk/access.py`)

| Nível | Quem | O que vê ou faz |
|---|---|---|
| `track` | quem vê o principal | `GET /tickets/{id}/children`: resumo de cada filho (status, setor, categoria, obrigatório, responsável, prazo e atraso), sem descrição, interações nem anexos |
| `shared` | solicitante e criador do principal, em todos os filhos; criador de um filho, só nele | detalhe do filho, com interações públicas, e comentário público |
| `internal` | setor do filho, responsável, `read_all` | notas internas do filho |

**Regras complementares:**
- O atendente do setor do principal recebe 403 no detalhe dos filhos de outros setores.
- Solicitante e criadores não alteram um filho.
- Em subchamados, a nota interna é só do setor dele, mesmo para quem tem a permissão de notas internas em outro setor.
- O campo `parent_ticket_id` só aparece na resposta para quem pode ver o principal.

### Avisos

**`ticket.children_created`.** É emitido no principal, uma vez por lote. Vai ao solicitante e ao seletor novo
`creator`, que é quem abriu o principal. Como o motor não avisa o autor da ação, quem acabou de incluir os filhos não
recebe o próprio aviso.

**`ticket.created` de cada filho.** Continua indo ao setor dele. O payload agora traz `parent_ticket_id`, e a regra
padrão `ticket.created.requester` passa a exigir `parent_ticket_id = null`. Assim o solicitante não recebe um aviso por
filho. A migration só muda essa regra se ela ainda está como veio de fábrica.

**`ticket.child_completed`.** Vai ao responsável, ao solicitante e ao criador do principal. Quando zera as etapas
obrigatórias, vai também ao setor do principal, por uma segunda regra com `all_required_done = true`.

### Idempotência (parte 2b, `app/service_desk/idempotency.py`)

**Cabeçalho.** `POST /tickets` e `POST /tickets/{id}/children` aceitam o cabeçalho `Idempotency-Key`, um UUID por
intenção de envio. A tela repete a mesma chave nas novas tentativas.

**Tabela `sd_idempotency_keys`.** A unicidade é `UNIQUE (user_id, key)`, válida em todas as rotas. Cada linha guarda:
- a operação: `endpoint` e `target_id`;
- o hash do corpo;
- os chamados criados.

**Fluxo.** A chave é reservada **antes** de criar qualquer coisa, com
`INSERT … ON CONFLICT (user_id, key) DO NOTHING RETURNING id`. Assim não há erro de unicidade nem transação abortada.
- **Reserva vazia:** outra requisição tem a chave. A linha é lida com `FOR SHARE`, que espera a outra terminar:
  - mesma operação e mesmo corpo: devolve os mesmos chamados, com 200 e `Idempotent-Replay: true`;
  - outra rota, outro principal ou outro corpo: 422;
  - a outra desfez a reserva: tenta reservar mais uma vez.
- **Reserva feita:** a requisição cria os chamados e grava o resultado na mesma transação. Um erro desfaz tudo, inclusive
  a chave.
- **Sem cabeçalho:** o comportamento é o de antes.

**Limpeza.** O job `retention.cleanup` apaga as chaves com mais de 48 h.

### Indicadores de SLA (parte 2c, `app/sla/report.py`)

**Indicadores do período.** O relatório separa os ciclos encerrados no período:
- **por tipo** (`by_kind`): avulso, principal e subchamado. O tempo total do processo é o do principal, quando a
  categoria dele tem política. Recomendação: usar no principal uma política que pause em `PENDING` enquanto espera os
  filhos; isso não é automático.
- **subchamados por setor responsável** (`child_by_sector`): o tempo de atendimento de cada departamento.

**Situação atual dos principais abertos** (`processes`). São dois sinais separados:
- `process_overdue`: o SLA do próprio principal venceu;
- `steps_overdue`: há etapa obrigatória atrasada.

O `children_progress` de cada principal traz os mesmos dois sinais.

### Anexos restritos (parte 3, `app/attachments/access.py`)

**Campo.** `attachments.is_internal`, com padrão `false`: os anexos existentes continuam como estão.

**Quem envia.** Só quem vê as notas internas do chamado marca um anexo como restrito. Num subchamado, isso vale só
para o setor dele. Anexo de ativo não pode ser restrito.

**Quem não vê as notas internas.** Para essa pessoa, o anexo restrito não existe:
- a listagem não o mostra; o filtro é feito na consulta;
- o download e a exclusão por id dão **404**, para não confirmar que ele existe.

**Regra central.** Tudo isso vive em `ensure_attachment_access`, o ponto único por onde passa toda rota de anexo,
inclusive as futuras.

### Modelos de atendimento (parte 4, `app/service_desk/templates.py`)

**Tabelas.** `sd_ticket_templates` guarda nome, descrição e situação. `sd_ticket_template_items` guarda cada item:
categoria, setor opcional, título, descrição, campos padrão, obrigatoriedade e ordem.

**Rotas** (`/ticket-templates`):
- qualquer usuário lê os modelos ativos;
- quem tem `service_desk.templates.manage` cria, substitui e desativa. Desativar não apaga nada.

**O modelo só pré-preenche a tela.** A abertura recebe a lista explícita de subchamados, e cada item passa pelas regras
de sempre. Um item com setor fora do padrão da categoria é recusado para quem não tem `route_any_sector`, mesmo vindo de
um modelo.

**Rastreio.** O `template_id` do principal fica gravado e precisa estar ativo na abertura.

**Nomes de processo.** Nenhum existe no código; os modelos são dados.

## Alternativas descartadas

- **Tabela de vínculo N:N.** Permitiria vários níveis e vários pais, que não são necessários. Um nível simplifica a
  trava, o progresso e a autorização.
- **Fechar o principal automaticamente.** Esconderia a decisão de quem administra o processo.
- **Reabrir ou apagar o cancelado ao substituir.** Perderia o histórico de por que a etapa foi cancelada.

## Consequências

- **Indicadores de SLA.** Um ciclo `CANCELED` sai do cálculo de cumprimento.
- **Volta da migration.** Subchamados cancelados viram `CLOSED`, e ciclos cancelados viram `SUPERSEDED`. Os vínculos se
  perdem, mas nenhum chamado é apagado.
- **Telas (parte 5):**
  - **Abertura:** campo Solicitante (com `create_on_behalf`), seção Subchamados com "Usar modelo" e a chave de idempotência por envio.
  - **Detalhe:** painel de subchamados com progresso e as ações de cancelar, dispensar e substituir, e a faixa "Subchamado de #N".
  - **Anexos:** opção "Restrito ao setor" para quem atende.
  - **Modelos:** tela em *Service Desk > Modelos de Atendimento*.

## Critérios de aceite

Os critérios estão em `backend/tests/service_desk/test_linked_tickets.py`:
- abertura com filhos;
- transação única;
- visibilidade por setor;
- criador diferente do solicitante;
- inclusão posterior;
- inclusão depois do encerramento (409);
- encerramento travado e destravado;
- cancelamento com e sem justificativa;
- substituição;
- dispensa;
- avisos consolidados;
- SLA cancelado;
- um nível só;
- direcionamento dos filhos;
- concorrência real entre incluir e encerrar, no PostgreSQL;
- migration de ida e volta.
