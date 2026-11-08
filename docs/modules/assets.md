# MOD-05 — Gestão Patrimonial (Ativos)

> Estado real e dono das regras: ver [mapa lógico](../architecture/mapa-logico-gero.md).

Este módulo é responsável por gerenciar o ciclo de vida e características técnicas dos ativos de TI (computadores, monitores, servidores, celulares, etc).

## Decisões de Arquitetura

Conforme a [ADR-005](../decisions/ADR-005-jsonb-asset-specs.md), as especificações técnicas de cada categoria de ativo (como processador e RAM para notebooks, portas e PoE para switches) são salvas de forma flexível utilizando a coluna `JSONB` no PostgreSQL.

## Modelagem

### AssetCategory
- Representa a categoria de um equipamento (ex: "Notebook", "Monitor").
- Define as especificações exigidas na propriedade `spec_schema` usando um formato de validação para os atributos (geralmente interpretado no backend).

### Asset
- Representa o equipamento físico e individual.
- Identificado exclusivamente pelo número de patrimônio (`tag`).
- Possui status que reflete seu ciclo de vida (Em Estoque, Em Uso, Manutenção, Baixado).
- Detém um JSONB `technical_specs` que deve seguir o esquema de sua `AssetCategory`.
- Relaciona-se com a `Unit` (Unidade onde se encontra fisicamente) e o `Employee` (responsável).

## Relacionamentos

- **MOD-02 Organização:** Ativos são alocados em unidades (`Unit`) e vinculados a colaboradores (`Employee`).
- **MOD-04 Service Desk:** É possível associar um ticket a um ativo para rastrear históricos de chamados.
- **MOD-06 Movimentações:** Toda mudança de status, unidade ou colaborador gera um registro no histórico de movimentações.
