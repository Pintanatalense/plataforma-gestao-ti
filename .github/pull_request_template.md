## Problema
<!-- O que está errado ou faltando, e qual o impacto. Cite o item do plano (docs/plans/plano-evolucao.md), se houver. -->

## O que muda
<!-- Resumo objetivo. Liste o que NÃO entra neste PR. -->

## Validação (evidência, não intenção)
<!-- Comandos executados e resultados: testes (n passed), alembic upgrade/downgrade com dados, build, teste manual. -->
- [ ] `bash scripts/ci-local.sh` verde **no commit publicado** (cole abaixo o `.ci-local/ultimo-resultado.txt`)
- [ ] Testes automatizados novos ou ajustados, incluindo cenário de falha
- [ ] Testes do backend e do frontend passando; CI verde
- [ ] Migration testada com dados (upgrade → downgrade → upgrade) e `alembic check` limpo — ou "sem migration"
- [ ] Autorização e validação de entradas verificadas — ou "não se aplica"
- [ ] Documentação e/ou ADR atualizados — ou "não se aplica"

## Reuso e dono das regras
<!-- Consulte docs/architecture/mapa-logico-gero.md antes de implementar. Se o PR só corrige bug interno
     sem mudar contrato, dono, tabela, rota, evento ou permissão, escreva "sem mudança de capacidade". -->
- [ ] Capacidade(s) do mapa tocadas (CAP-___) e decisão: **reutilizar | estender | adaptar | criar** — por quê
- [ ] O dono da regra continua o mesmo — ou a mudança está justificada e o mapa atualizado neste PR
- [ ] Consumidores verificados (busca dos símbolos alterados) e testes de regressão/negativos listados
- [ ] Mapa lógico atualizado neste PR — ou "sem mudança de capacidade"

## Limitações e riscos residuais
<!-- O que continua sem cobertura; impacto em instalações existentes. -->

## Rollback
<!-- Normalmente: reverter o PR. Se houver migration ou dados, diga como voltar. -->
