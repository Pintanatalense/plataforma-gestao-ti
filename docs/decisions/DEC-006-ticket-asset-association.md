# DEC-006 — Associação Chamado ↔ Ativo

**Status:** Aceito
**Data:** 2026-10-08

## Contexto

Para o funcionamento integrado do Service Desk (MOD-04) e Gestão Patrimonial (MOD-05), é necessário que chamados possam ser abertos e relacionados a equipamentos físicos. Exemplos:
- Chamado de "Lentidão" vinculado a um "Notebook" específico.
- Chamado para reparo vinculado a uma "Impressora".

## Decisão

Foi definida uma relação muitos-para-muitos entre `sd_ticket` e `assets`.
Para isso, será criada uma tabela associativa `sd_ticket_assets` contendo as chaves `ticket_id` e `asset_id`.

## Justificativa

- Um chamado pode envolver múltiplos ativos (ex: "Trocar notebooks e docas de 5 usuários do setor X").
- Um ativo, ao longo do seu ciclo de vida, passará por diversos chamados de suporte.
- Uma tabela relacional dedicada mantém a independência e facilita relatórios de histórico (ex: "quantos chamados este ativo teve nos últimos 12 meses?").

## Consequências

- O frontend de Service Desk deve possuir um componente de busca/seleção de ativos (por patrimônio, usuário, etc).
- O módulo Service Desk ganha dependência de leitura no módulo de Ativos, que deve ser tratada preferencialmente nos schemas e endpoints.
