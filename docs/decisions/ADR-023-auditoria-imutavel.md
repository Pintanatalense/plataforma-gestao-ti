# ADR-023 — Auditoria imutável (só inserção, cadeia de hash e retenção como único DELETE)

**Status:** Aceito e implementado (2026-10-26)
**Data:** 2026-10-26
**Origem:** Plano de Evolução, requisito S4 (Fase 0, PR 11). **Depende de:** ADR-022 (papéis de banco).

## Contexto

Depois do PR 9 a trilha tem ator, IP confiável, categoria e retenção, mas qualquer código da aplicação ainda podia alterar ou apagar registros (`UPDATE`/`DELETE` em `audit_logs`), e a limpeza da demonstração apagava a trilha operacional. Sem proteção no banco, uma falha ou um invasor na aplicação apaga o próprio rastro.

## Decisão

**1. Só inserção, no banco.**
- O papel da aplicação (`gestao_app`) tem só `SELECT` e `INSERT` em `audit_logs` e só `SELECT` em `audit_chain_state` (`app/db_roles.py`).
- O gatilho `audit_logs_guard` recusa `UPDATE` e `DELETE` para **qualquer** papel, inclusive o dono das tabelas, fora das duas funções abaixo; o gatilho `audit_logs_no_truncate` recusa `TRUNCATE`. Uma inserção não pode trazer o selo pronto.
- A limpeza da demonstração e da carga de QA não apaga mais nenhuma auditoria.

**2. Selo em cadeia de hash, uma cadeia por categoria.** A função `audit_seal` (job `audit.seal`, a cada minuto) pega os registros ainda sem selo em ordem de criação e grava `chain_pos` (posição na cadeia da categoria), `prev_hash` e `row_hash = sha256(prev_hash ‖ id ‖ evento ‖ entidade ‖ dados ‖ ator ‖ categoria ‖ IP ‖ requisição ‖ data)`. `audit_chain_state` guarda o fim de cada cadeia e a **âncora** (o hash do último registro apagado pela retenção). Uma cadeia por categoria porque cada categoria tem seu prazo: a retenção apaga sempre o **começo** da cadeia, sem abrir buracos no meio.

O selo é feito depois da inserção, num passo único e serializado (*advisory lock*), e não no momento de gravar. Assim as requisições não disputam um bloqueio global até o commit, que causaria fila e risco de deadlock.

**3. Retenção como único DELETE.** `audit_purge(categoria, dias, posição)`:
- exige o prazo mínimo da categoria (segurança 1825 dias, operacional 30), independentemente do que a aplicação pedir;
- só apaga o começo selado da cadeia, até a posição pedida;
- recusa se algum desses registros ainda estiver no prazo (o "agora" é o do banco);
- move a âncora.

A aplicação exporta antes o arquivo `.jsonl.gz` com `.sha256`, agora com o selo de cada linha.

**4. Verificação.** `audit_verify()` recalcula cada cadeia a partir da âncora e aponta o primeiro problema: posição ausente, elo que não confere, conteúdo alterado ou fim da cadeia diferente do registrado. O job `audit.verify` (diário, 04:30) roda a verificação e grava o fim de cada cadeia (posição e hash) no log. Se houver problema, registra `audit.integrity_failed` (segurança) e avisa os administradores com prioridade crítica. `GET /api/v1/audit/integrity` (`audit.read`) mostra o mesmo resultado.

As funções que escrevem (`audit_seal`, `audit_purge`) são `SECURITY DEFINER` do dono, com `search_path` fixo; `EXECUTE` foi retirado de `PUBLIC` e dado só à aplicação. O modo que libera o gatilho (`gti.audit_mode`) é ligado com `set_config` local dentro da função e desligado ao sair.

## Limites (o que isto NÃO garante)

- **Superusuário do PostgreSQL** pode desligar o gatilho, alterar registros e recalcular a cadeia e o estado. A proteção é contra a aplicação, o dono e erros. Contra o superusuário, a cadeia **acusa** alterações (o teste prova com gatilho desligado), mas só até ele reescrever tudo. Por isso o fim da cadeia vai para o log todo dia: guardado fora do servidor, serve de âncora externa.
- Registros recém-gravados ficam **sem selo por até ~1 minuto**. Nesse intervalo só o gatilho os protege (a aplicação já não tem `UPDATE`/`DELETE`).
- Migrations futuras que precisem corrigir a auditoria terão de desligar o gatilho de forma explícita e registrada e selar de novo.

## Alternativas descartadas

- **Hash calculado na inserção (gatilho com bloqueio global):** serializa toda transação que audita até o commit; risco de deadlock com bloqueios de linha tomados antes.
- **Cadeia única para todas as categorias:** a retenção por categoria abriria buracos no meio da cadeia.
- **Assinatura com chave da aplicação (HMAC):** quem controla a aplicação controla a chave; não acrescenta contra o cenário que importa.

## Consequências

- Migration `y5c6d7e8f9a0b` (V1 congelada em `app/audit/chain_ddl.py`). Volta: remove gatilhos, funções e o selo; os registros ficam.
- Instalações existentes: o job `audit.seal` sela o histórico já gravado em lotes de 5000, logo depois da atualização.
- Os testes em PostgreSQL ganham o mesmo gatilho e as mesmas funções pelo `create_all`.
