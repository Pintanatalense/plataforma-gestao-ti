# ADR-024 — Worker: papéis, execuções com concessão, subprocesso com tempo máximo e nova tentativa

**Status:** Aceito e implementado (2026-10-26)
**Data:** 2026-10-26
**Origem:** Plano de Evolução, seção 3.5 (Fase 0, PR 12). Complementa o ADR-013 §4.5 (uma réplica do worker).

## Contexto

O worker rodava tudo num único laço: expandir eventos, enviar entregas e **esperar** cada job vencido terminar. Daí vinham três problemas:

- um backup demorado ou um job preso atrasava todas as notificações;
- um trecho bloqueante travava o processo inteiro, e um timeout do `asyncio` não interrompe código bloqueante;
- uma queda no meio de um job não deixava rastro nem tinha nova tentativa.

Integrações futuras (Proxmox, Zabbix) vão agravar isso.

## Decisão

**Dois laços independentes**, cada um com seu heartbeat:
- `notifier`: entregas (fan-out, envio, recuperação de entregas travadas, Telegram);
- `scheduler`: agenda.

Papel por `WORKER_ROLE` / `--role`:
- `all` (padrão): os dois laços num contêiner;
- `delivery` ou `jobs`: um laço só, para separar em dois contêineres.

`/api/v1/health` mostra `components.worker` e `components.scheduler`. O `--healthcheck` do contêiner exige os heartbeats do seu papel.

**`job_runs`:**
- uma linha por execução (`running`, `ok`, `error`, `timeout`, `interrupted`), com tentativa, duração, erro e worker;
- no máximo uma `running` por job, garantido por índice único parcial;
- a concessão (`lease_until`, 60 s) é renovada a cada 20 s enquanto a execução roda;
- concessão vencida (worker caiu ou travou) vira `interrupted`.

**Cada execução reservada vira uma tarefa própria**, e o laço da agenda segue reservando os outros jobs: um backup de 30 minutos não segura o selo da auditoria, que roda a cada minuto.

**Isolamento:**
- **subprocesso** por execução (`python -m app.worker --run-job`) para os jobs que chamam programas externos, podem demorar ou ter trecho bloqueante (`backup.daily`, `audit.retention`, `audit.verify`, `retention.cleanup`). Passou do tempo máximo, o grupo de processos inteiro recebe SIGTERM e, 5 s depois, SIGKILL; assim o `pg_dump` não fica órfão;
- os demais rodam no processo, com `asyncio.wait_for`;
- tempo máximo por job: 30 min (backup, retenção e verificação), 15 min (limpeza), 1 min (WhatsApp), 5 min (padrão).

**Nova tentativa:**
- falha, tempo esgotado ou interrupção tentam de novo em 1 e depois 2 minutos, sem passar da próxima execução normal;
- na 3ª falha seguida o job volta à agenda normal, com log de erro;
- `scheduled_jobs.retry_attempt` guarda a sequência. Os jobs já gravam por condição ou upsert, então repetir não duplica resultado.

**Histórico:** `GET /api/v1/notifications/admin/jobs/{nome}/runs`.

## Alternativas descartadas

- **Fila externa (Celery/RQ + Redis):** mais um serviço para operar, sem necessidade com uma réplica e poucos jobs.
- **Thread por job:** não dá para matar uma thread presa; o subprocesso dá.
- **Subprocesso para todos os jobs:** cada um custa ~1–3 s de importação e memória; jobs curtos e assíncronos não precisam.

## Consequências

- Migration `z6d7e8f9a0b1c` (só acrescenta; volta remove `job_runs` e `retry_attempt`).
- Ao parar o worker, as execuções em andamento são canceladas (o subprocesso é encerrado) e retomadas pela recuperação de concessão vencida no próximo início.
- Pendente: tela com o histórico de execuções (a API já existe).
