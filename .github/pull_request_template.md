## Problema
<!-- O que está errado ou faltando, e qual o impacto. Cite o item do plano diretor (docs/plans/plano-diretor.md), se houver. -->

## O que muda
<!-- Resumo objetivo. Liste o que NÃO entra neste PR. -->

## Validação (evidência, não intenção)
<!-- Comandos executados e resultados: testes (n passed), alembic upgrade/downgrade com dados, build, teste manual. -->
- [ ] Testes automatizados novos ou ajustados, incluindo cenário de falha
- [ ] Testes do backend e do frontend passando; CI verde
- [ ] Migration testada com dados (upgrade → downgrade → upgrade) e `alembic check` limpo — ou "sem migration"
- [ ] Autorização e validação de entradas verificadas — ou "não se aplica"
- [ ] Documentação e/ou ADR atualizados — ou "não se aplica"

## Limitações e riscos residuais
<!-- O que continua sem cobertura; impacto em instalações existentes. -->

## Rollback
<!-- Normalmente: reverter o PR. Se houver migration ou dados, diga como voltar. -->
