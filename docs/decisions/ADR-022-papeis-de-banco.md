# ADR-022 — Papéis de banco separados (dono, aplicação e Evolution)

**Status:** Aceito e implementado (2026-10-26)
**Data:** 2026-10-26
**Origem:** Plano de Evolução, requisito S3 (Fase 0, PR 10). Pré-requisito da auditoria imutável (PR 11) e do backup completo (PR 13).

## Contexto

Backend, worker **e Evolution** conectavam ao PostgreSQL com o mesmo `POSTGRES_USER`, que é o **superusuário** criado pela imagem. Consequências:

- uma injeção de SQL, um bug ou uma dependência comprometida no backend podia apagar tabelas, alterar a estrutura, ler arquivos do servidor (`COPY ... FROM`), criar papéis ou desligar gatilhos;
- a Evolution (código de terceiros, exposta ao WhatsApp) podia ler e alterar todas as tabelas do sistema;
- a auditoria imutável planejada (S4) não tem efeito se a aplicação é superusuária: superusuário ignora permissões e pode desligar gatilhos.

## Decisão

Três papéis com função única, mais o superusuário restrito à preparação:

| Papel (padrão) | Quem usa | Pode | Não pode |
|---|---|---|---|
| superusuário (`POSTGRES_USER`) | só o serviço `db-init` | criar/atualizar papéis e posse | — (não fica com nenhum serviço permanente) |
| **dono** (`gestao_owner`) | `db-init` (migrations) | ser dono das tabelas do schema `public`; DDL | ser superusuário, criar banco ou papel |
| **aplicação** (`gestao_app`) | backend e worker | SELECT/INSERT/UPDATE/DELETE nas tabelas e sequências do `public`; SELECT em `alembic_version`; SELECT no schema `evolution_api` | DDL, TRUNCATE, gravar em `alembic_version`, gravar no schema da Evolution |
| **Evolution** (`gestao_evolution`) | Evolution API | ser dona do schema `evolution_api` (as migrations dela) | ler ou gravar qualquer tabela do `public` |

**Serviço `db-init`** (mesma imagem do backend, `restart: "no"`), a cada `docker compose up`:

1. `python -m app.db_roles` (como superusuário): cria ou atualiza os papéis (senha e atributos `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`), tira `CREATE` do `public` de todos menos do dono, **transfere ao dono** tabelas, visões, sequências, tipos e funções do `public` que pertençam a outro papel, cria/transfere o schema `evolution_api` à Evolution, aplica as permissões da aplicação e os *default privileges* (o que o dono criar depois já nasce com as permissões da aplicação);
2. `alembic upgrade head` como **dono**;
3. `python -m app.db_roles` de novo (a tabela `alembic_version` só existe depois da primeira migration e precisa ficar só leitura para a aplicação).

Backend e Evolution só sobem depois de o `db-init` terminar bem (`service_completed_successfully`). O backend não roda mais migrations (`RUN_MIGRATIONS=false`); o seed roda com o papel da aplicação (só dados).

**Idempotente:** o mesmo passo serve para instalação nova, atualização de instalação antiga (tudo do superusuário), backup antigo restaurado e troca de senha (mudou no `.env`, muda no banco no próximo `up`). Execuções simultâneas são serializadas por *advisory lock*; o `CREATE/ALTER ROLE` roda com `log_statement = 'none'` para a senha não ir ao log do PostgreSQL.

**Senhas:** obrigatórias no `.env` (`DB_OWNER_PASSWORD`, `DB_APP_PASSWORD`, `DB_EVOLUTION_PASSWORD`; o Compose recusa subir sem elas), de 16 a 128 caracteres só com `A-Z a-z 0-9 . _ ~ -` (vão dentro da URL de conexão). Os instaladores geram as que faltam, inclusive numa instalação existente.

**Backup pela tela:** o `pg_dump` roda com o papel da aplicação. Por isso ela lê (só lê) o schema `evolution_api`: o backup continua com a sessão do WhatsApp, como antes. A aplicação já tem a chave da API da Evolution, então essa leitura não amplia o que ela controla.

## Volta (rollback)

Sem mexer em dados: no `.env`, `DB_OWNER_USER`, `DB_APP_USER` e `DB_EVOLUTION_USER` = valor de `POSTGRES_USER` e as três senhas = `POSTGRES_PASSWORD`; depois `docker compose up -d`. Papel igual ao superusuário é ignorado pelo `db-init`; as tabelas continuam do dono, o que não impede o superusuário de nada. Para voltar aos papéis separados, restaure os valores; o `db-init` corrige posse e permissões.

## Alternativas descartadas

- **Script em `docker-entrypoint-initdb.d`:** só roda com volume vazio; não resolve instalações existentes nem troca de senha.
- **Backend com as duas credenciais (dono para migrar, aplicação para servir):** o contêiner exposto continuaria com a senha que altera a estrutura.
- **`REASSIGN OWNED BY postgres`:** o PostgreSQL não permite reatribuir objetos do superusuário de inicialização; a transferência é feita objeto a objeto, só nos schemas `public` e `evolution_api`.
- **Backup pela tela sem o schema da Evolution (`-N evolution_api`):** mudaria o conteúdo do backup (perderia a sessão do WhatsApp) e a decisão sobre o volume da Evolution é do PR 13.

## Consequências

- O backend e o worker não alteram estrutura nem apagam tabelas em massa; a Evolution fica restrita ao próprio schema.
- Atualizar uma instalação exige as três senhas novas no `.env` (instalador ou manual) — roteiro em [08 — Manutenção e atualização](../08-manutencao-e-atualizacao.md).
- `make migrate` e `make rollback` passam a usar o `db-init` (`docker compose run --rm db-init`).
- `scripts/restore-backup.sh` roda o `db-init` depois de restaurar o banco (backups antigos trazem tudo do superusuário).
- Base para o PR 11: retirar da aplicação UPDATE/DELETE em `audit_logs` passa a ter efeito.
- Fora deste ADR: monitoramento externo do banco (ex.: Zabbix) continua com o papel que o operador criar; o `db-init` não revoga `CONNECT` de `PUBLIC`.
