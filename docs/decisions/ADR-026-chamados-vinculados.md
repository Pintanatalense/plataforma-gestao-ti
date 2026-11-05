# ADR-026 — Chamados vinculados: principal e subchamados para vários setores

**Status:** Aceito; implementado em partes. A parte 2a (vínculo, cancelamento, substituição, obrigatoriedade e avisos)
está neste PR. Ficam para os próximos PRs: 2b (idempotência), 2c (indicadores de SLA por tipo), 3 (anexos restritos),
4 (modelos de atendimento) e 5 (telas).
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

## Alternativas descartadas

- **Tabela de vínculo N:N.** Permitiria vários níveis e vários pais, que não são necessários. Um nível simplifica a
  trava, o progresso e a autorização.
- **Fechar o principal automaticamente.** Esconderia a decisão de quem administra o processo.
- **Reabrir ou apagar o cancelado ao substituir.** Perderia o histórico de por que a etapa foi cancelada.

## Consequências

- **Indicadores de SLA.** Um ciclo `CANCELED` sai do cálculo de cumprimento. A separação por tipo (avulso, principal ou
  subchamado) entra na parte 2c.
- **Volta da migration.** Subchamados cancelados viram `CLOSED`, e ciclos cancelados viram `SUPERSEDED`. Os vínculos se
  perdem, mas nenhum chamado é apagado.
- **Telas.** O frontend atual ainda não mostra subchamados; isso fica para o PR 5. Até lá, a API já funciona.

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
