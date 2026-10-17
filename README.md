# Plataforma Modular de Gestão de TI

Service desk, gestão de ativos, estoque, inventário e integração com WhatsApp para a TI de uma empresa (single tenant).
Estado técnico detalhado e navegação do código: [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md). Riscos e dívida: [`docs/AUDIT.md`](docs/AUDIT.md). Decisões: [`docs/decisions/`](docs/decisions/).

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic |
| Banco | PostgreSQL 16 |
| Frontend | Angular 22 + Angular Material |
| Entrega | Docker Compose, Nginx |

## Instalação

Pré-requisito: Docker com Compose v2.

```bash
cp .env.example .env
# edite o .env: POSTGRES_PASSWORD e SECRET_KEY são OBRIGATÓRIOS
#   SECRET_KEY:  openssl rand -hex 32   (o sistema recusa valores de exemplo ou curtos)
docker compose up -d --build
```

Abra `http://<servidor>` (porta `HTTP_PORT`, padrão 80). No primeiro acesso a tela de **configuração inicial** cria o administrador.
O Nginx é a única porta publicada; banco e API ficam na rede interna do Compose. O build do frontend acontece dentro da imagem do Nginx.

Migrations e seed rodam sozinhos ao iniciar o backend (`backend/docker-entrypoint.sh`); uma falha derruba o container em vez de ser ignorada.

## Atualização

```bash
git pull
docker compose up -d --build
docker compose logs -f backend
```

### Ao migrar de uma versão anterior à Fase 0

- **`.env`:** defina `SECRET_KEY` (≥ 32 caracteres, sem "CHANGE-ME") e `POSTGRES_PASSWORD` = a senha atual do banco. Sem isso o Compose não sobe.
- **Anexos:** antes ficavam em `./backend/uploads` no host; agora vivem no volume `attachments_data` (`/data/attachments`) com outra estrutura de nomes. Copie os arquivos antigos para o volume e mantenha o mesmo caminho relativo registrado na tabela `attachments`
  (`file_path`) — os nomes novos não usam extensão, os antigos sim, então a cópia direta preserva os arquivos antigos.
- **Logo:** reenvie a logomarca em Administração (apenas PNG/JPEG).
- **Portas:** 5432 e 8000 deixaram de ser publicadas. Para desenvolvimento use `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`.
- **Banco já migrado:** a nova migration de união (`88d09e47595a`) e a de bloqueio de login (`i9d0e1f2a3b4`) são aplicadas automaticamente.
- **Perfis:** o seed não sobrescreve mais as permissões dos perfis existentes.
- **Chamados:** atendentes passam a ver apenas chamados do próprio setor, atribuídos a eles ou abertos por eles (quem precisa ver todos recebe `service_desk.tickets.read_all`).
- **WhatsApp:** o webhook exige o cabeçalho `X-Webhook-Secret` igual ao segredo cadastrado em Administração; o vínculo de número por matrícula foi removido (cadastre o telefone no colaborador).

## Backup e restauração

- Gerar: tela **Administração → Backups** (ou `POST /api/v1/system/backups/generate`). Cada arquivo `.sql.gz` tem SHA-256 registrado.
- **Restaurar é um procedimento offline** (a API não restaura mais: o `DROP/CREATE` travava as requisições):

  ```bash
  docker compose cp backend:/data/backups/<arquivo>.sql.gz .
  scripts/restore-backup.sh ./<arquivo>.sql.gz   # make restore FILE=./<arquivo>.sql.gz
  ```

  O script faz um dump de segurança, para o backend, restaura em transação única (aborta no primeiro erro) e religa o backend.
- O backup cobre **somente o banco**. Anexos e logo estão nos volumes `attachments_data` e `static_data`: inclua-os na rotina de backup do servidor.
- Backup automático/agendado ainda não existe (previsto no ADR-013).

## Desenvolvimento

```bash
make fe-install && make fe-build          # frontend (ou cd frontend && npm start)
cd backend && uv sync && uv run pytest    # testes (SQLite em memória)
```

Testes que exigem PostgreSQL (`-m pg`, concorrência de estoque) rodam com `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test`.
Base de testes/homologação (QA) em PostgreSQL descartável: `make test-db-up`, `make test-pg`, `make seed-test` — ver [`docs/11-base-de-testes-e-homologacao.md`](docs/11-base-de-testes-e-homologacao.md).
Criar migration: `make migration MSG="descrição"`; aplicar: `make migrate`.

## Licença

Proprietário — uso interno. Veja `LICENSE.md`.
