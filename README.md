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
# edite o .env: POSTGRES_PASSWORD, SECRET_KEY e APP_ENCRYPTION_KEY são OBRIGATÓRIOS
#   SECRET_KEY:  openssl rand -hex 32   (o sistema recusa valores de exemplo ou curtos)
#   APP_ENCRYPTION_KEY:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   (guarde uma cópia da APP_ENCRYPTION_KEY FORA do servidor: sem ela a senha SMTP gravada não pode ser lida)
docker compose up -d --build
```

Abra `http://<servidor>` (porta `HTTP_PORT`, padrão 80). No primeiro acesso a tela de **configuração inicial** cria o administrador.
O Nginx é a única porta publicada; banco e API ficam na rede interna do Compose. O build do frontend acontece dentro da imagem do Nginx.

O serviço **`worker`** (mesma imagem, 1 réplica) envia as notificações (sino e e-mail), executa o **backup diário às 02:00** (fuso `APP_TIMEZONE`, padrão America/Fortaleza) e a limpeza de dados antigos às 03:30. Saúde: `docker compose ps` (healthcheck por heartbeat) e `components.worker` em `/api/v1/health`.

Migrations e seed rodam sozinhos ao iniciar o backend (`backend/docker-entrypoint.sh`); uma falha derruba o container em vez de ser ignorada.

## Atualização

```bash
git pull
docker compose up -d --build
docker compose logs -f backend
```

### Ao migrar de uma versão anterior à Fase A (hub de notificações)

- **`.env`:** defina `APP_ENCRYPTION_KEY` (veja a instalação). O Compose não sobe sem ela.
- **E-mail:** a configuração SMTP antiga (senha em texto puro em `system_settings`) é movida pela migration `j0e1f2a3b4c5` para `channel_configs`, com a senha cifrada. Nada a fazer; reconfigurar só se a migration for aplicada com outra chave depois.
- **Worker:** `docker compose up -d --build` já cria o serviço `worker`. Sem ele as notificações ficam em fila (`deliveries` PENDING) e nenhum backup agendado roda.
- **Notificações:** chamados novos, atribuições, mudanças de status e respostas passam a gerar notificações no sino (e e-mail, se o SMTP estiver habilitado). Os e-mails não saem mais dentro da requisição.

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

## Notificações e Telegram

- **Caixa de entrada e preferências:** menu Notificações. Avisos por e-mail respeitam o horário de silêncio de cada pessoa (padrão 20h–07h); falhas críticas (ex.: backup) ignoram o silêncio.
- **Administração** (`notifications.manage`): Notificações → Entregas e regras — entregas com reenvio, regras com simulador, saúde dos canais e agenda do worker.
- **Telegram (opcional, gratuito):**
  1. No Telegram, converse com o `@BotFather`, crie o bot e copie o token.
  2. Em Entregas e regras → Saúde dos canais → Telegram: cole o token, habilite e salve. O sistema valida o token e descobre o `@` do bot.
  3. Cada pessoa vai em Notificações → Minhas preferências, gera o código e envia `/vincular CÓDIGO` ao bot.
  4. A partir daí ela recebe avisos e pode abrir, consultar e responder chamados pelo chat, com as mesmas permissões que tem no sistema.
  - A entrada usa *long polling* a partir do worker: não é preciso domínio, HTTPS nem porta aberta. O servidor só precisa de saída para `api.telegram.org`.

## Backup e restauração

- Gerar: tela **Administração → Backups** (ou `POST /api/v1/system/backups/generate`). Cada arquivo `.sql.gz` tem SHA-256 registrado.
- **Restaurar é um procedimento offline** (a API não restaura mais: o `DROP/CREATE` travava as requisições):

  ```bash
  docker compose cp backend:/data/backups/<arquivo>.sql.gz .
  scripts/restore-backup.sh ./<arquivo>.sql.gz   # make restore FILE=./<arquivo>.sql.gz
  ```

  O script faz um dump de segurança, para o backend, restaura em transação única (aborta no primeiro erro) e religa o backend.
- O backup cobre **somente o banco**. Anexos e logo estão nos volumes `attachments_data` e `static_data`: inclua-os na rotina de backup do servidor.
- **Backup automático:** o worker gera um backup por dia às 02:00; falha dispara notificação crítica (sino + e-mail) aos administradores. A retenção segue `BACKUP_MAX_KEEP`. Os arquivos ficam no volume `backups_data`: copie-os para fora do servidor.

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
