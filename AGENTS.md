# Fluxo para agentes de IA

Regras para qualquer agente (Claude Code, Codex, Hermes e outros) que altere este repositório. Valem junto com o
[CONTRIBUTING.md](CONTRIBUTING.md), que continua sendo a referência de padrões, banco, segredos e revisão.

**Princípio:** o agente descobre e corrige os próprios erros **antes** de publicar. O CI do GitHub é a validação
independente que confirma o trabalho, não a ferramenta para encontrar erros. A decisão de integrar é sempre humana.

## 1. Antes de começar

- Confira o estado real: `git status`, `gh pr list`, a branch atual. Não presuma que um PR ou branch ainda está como
  estava na sessão anterior.
- Leia as ADRs e trechos do CONTRIBUTING que a mudança toca. Mudança de arquitetura, dados ou segurança começa por ADR
  ou proposta aprovada.
- Uma mudança lógica por branch (`fix/…`, `feat/…`, `docs/…`, `ci/…`, `chore/…`), a partir da `main` ou do PR de que
  depende (PR empilhado, declarado na descrição).
- **Um PR por módulo.** As etapas de uma mesma entrega (por exemplo, a Central de Mensagens ou os chamados vinculados)
  podem ser commits ou branches separados durante o trabalho, mas são publicadas juntas num PR só. O responsável
  testa o módulo completo no sistema, e o portão completo roda uma vez por PR, não uma vez por etapa.

## Antes de implementar: reuso e dono das regras

- Consulte `docs/architecture/mapa-logico-gero.md` e identifique a capacidade, o dono da regra e o contrato reutilizável.
- Registre no plano ou no PR: reutilizar, estender, adaptar ou criar, com justificativa. Criar um novo dono de regra exige justificativa explícita.
- Informe se a mudança altera dado oficial, apenas consulta/projeta ou apenas coordena um processo.
- Verifique consumidores e testes; inclua cenários negativos de permissão quando houver acesso.
- Atualize o mapa no mesmo PR que alterar capacidade, contrato, dono, tabela, rota, evento ou permissão.
- O mapa é índice de evidências; em divergência com código e testes, vale o código e o mapa é corrigido por PR.
- Na revisão, confira o registro de reuso contra o diff: novo dono de regra sem justificativa ou contrato duplicado impede a aprovação técnica.

## 2. Durante o desenvolvimento

- Escreva ou ajuste os testes junto com o código, incluindo o cenário de falha.
- Para iterar rápido, rode só o que importa (`uv run pytest tests/<área>`, `npm run test -- <spec>`). Entre as
  etapas de um módulo, esses testes direcionados bastam. Eles **não** substituem o portão do item 3 antes da publicação.

## 3. Portão antes de publicar (obrigatório)

```bash
bash scripts/ci-local.sh        # ou: make ci-local
```

- Roda em contêineres as mesmas verificações do CI para as áreas alteradas. Mexeu em `.github/workflows/`, CI ou
  infraestrutura: o modo padrão já roda tudo; use `--all` em caso de dúvida.
- PR de módulo: rode `bash scripts/ci-local.sh --all` no commit que vai ser publicado. Uma correção depois disso exige
  uma nova rodada antes do push.
- **Falhou?** Leia o log indicado (`.ci-local/*.log`), ache a causa raiz, corrija **todas** as falhas e rode de novo.
  Repita até `RESULTADO: tudo passou`. Só então faça o push.
- É proibido, para "passar": pular ou desligar teste, marcar `skip`/`xfail` sem motivo registrado, afrouxar asserção,
  usar `--no-verify`, ou mudar o workflow para não rodar a verificação.
- Teste instável: investigue. Se não for possível corrigir agora, registre no PR com evidência; não esconda.

## 4. Publicar

- Commits coesos e semânticos. Correções de revisão vão juntas, num commit, depois de um novo `ci-local` verde.
- Não há limite artificial de pushes: publique quando houver uma rodada de trabalho validada; não publique para testar.
- Descrição do PR pelo modelo, com a saída de `.ci-local/ultimo-resultado.txt` **do commit publicado** (a linha
  `Commit:` traz o SHA e não pode dizer "alterações não commitadas") e só com o que foi de fato verificado. O que não
  foi verificado aparece como tal.

## 5. CI e revisão

- CI vermelho com `ci-local` verde: é diferença de ambiente ou defeito real. Investigue e registre a causa.
  Reexecutar ("re-run") só para falha comprovadamente transitória, uma vez, dizendo por quê.
- Não dispare `workflow_dispatch` nem reexecuções sem pedido do responsável: cada execução gasta minutos
  (`docs/ci-consumo.md`).
- O agente **não** mescla PR, não aprova o próprio PR, não liga auto-merge e não altera workflows, orçamento,
  permissões ou proteção de branch sem autorização explícita do responsável para aquele caso.

## 6. Segurança

- Testes e migrations só em banco descartável (o `ci-local` cria um; o guarda dos testes recusa outros).
- Nunca coloque senha, token, chave ou dump em código, testes, logs, commits ou PRs.
- Ações em ambientes reais (servidores, bancos, integrações) só com pedido explícito para aquela ação.
