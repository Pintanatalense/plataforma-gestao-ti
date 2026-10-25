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

## 2. Durante o desenvolvimento

- Escreva ou ajuste os testes junto com o código, incluindo o cenário de falha.
- Para iterar rápido, rode só o que importa (`uv run pytest tests/<área>`, `npm run test -- <spec>`). Isso **não**
  substitui o portão do item 3.

## 3. Portão antes de publicar (obrigatório)

```bash
bash scripts/ci-local.sh        # ou: make ci-local
```

- Roda em contêineres as mesmas verificações do CI para as áreas alteradas. Mexeu em `.github/workflows/`, CI ou
  infraestrutura: o modo padrão já roda tudo; use `--all` em caso de dúvida.
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
