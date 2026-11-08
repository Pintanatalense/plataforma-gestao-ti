# MOD-06 — Movimentações

> Estado real e dono das regras: ver [mapa lógico](../architecture/mapa-logico-gero.md).

O módulo de movimentações gerencia o histórico e o rastreamento das transições dos ativos de TI (MOD-05).

## Modelagem

### AssetMovement
- Registra qualquer alteração de localização (unidade) ou responsável (colaborador) por um ativo.
- O campo `movement_type` classifica a ação:
  - `ASSIGNMENT` (Entrega/Atribuição ao colaborador)
  - `RETURN` (Devolução ao estoque)
  - `TRANSFER` (Transferência entre unidades ou colaboradores)
  - `MAINTENANCE` (Envio para manutenção)
  - `DECOMMISSION` (Baixa do ativo)
- Rastreia também as mudanças de status (de `status_from` para `status_to`).
- Salva o autor da transação (quem realizou a movimentação no sistema).

## Integração
- **MOD-05 (Ativos):** Não pode haver atualização direta no `unit_id`, `employee_id` ou `status` de um ativo sem gerar um correspondente `AssetMovement`. Isso assegura uma trilha de auditoria para os bens patrimoniais.
