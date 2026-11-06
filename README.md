# Plataforma Modular de Gestão de TI

Plataforma **self-hosted** para a área de TI de uma empresa (single tenant): atendimento de chamados com SLA, patrimônio, estoque, inventário e comunicação por e-mail, WhatsApp, Telegram, Slack e navegador, com auditoria imutável e backup completo.

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic |
| Banco | PostgreSQL 16 |
| Frontend | Angular 22 + Angular Material |
| Entrega | Docker Compose, Nginx (única porta publicada) |

**Sumário:** [Funcionalidades](#funcionalidades) · [Instalação](#instalação) · [Primeiro acesso](#primeiro-acesso) · [Canais de comunicação](#canais-de-comunicação) · [Operação](#operação) · [Atualização](#atualização) · [Desenvolvimento](#desenvolvimento) · [Documentação](#documentação)

---

## Funcionalidades

Tudo o que está nesta seção está implementado e foi testado (testes automatizados e verificação manual). O histórico detalhado de cada entrega está no [CHANGELOG](CHANGELOG.md).

### Service Desk e SLA

- **Chamados** com formulários dinâmicos por categoria, respostas públicas e notas internas, anexos, vínculo com ativos, consumo de estoque e reabertura controlada por prazo.
- **Visibilidade por setor:** o atendente vê os chamados do próprio setor, os atribuídos a ele e os que abriu; ver todos exige permissão específica.
- **SLA com horas úteis:** políticas (prazo de primeira resposta e de resolução por prioridade, alerta de proximidade, pausa por status, reabertura), calendários com expediente, almoço e feriados, política por categoria e selo de SLA no chamado.
- **Alertas automáticos** (job `sla.check`, a cada 5 minutos): registra violações e avisa a equipe quando o prazo está perto de vencer e quando é violado, uma vez por fato.
- **Relatório de chamados** com período: abertos por status e categoria, cumprimento do SLA, tempos médios de primeira resposta e resolução, e lista dos chamados em risco ou atrasados.

### Patrimônio, estoque e inventário

- **Ativos** com categorias, especificações flexíveis, movimentações, garantias e **Termo de Responsabilidade** com modelo editável.
- **Estoque de insumos** com mínimo por item e alertas de nível baixo e de garantias a 30 e 7 dias do vencimento.
- **Inventário periódico** e **importação de inventário do GLPI**.
- **Organização:** empresa, unidades, setores e colaboradores.

### Central de Mensagens e notificações

- **Hub de notificações** com caixa de entrada (sino), preferências por pessoa, horário de silêncio, regras com simulador, reenvio de entregas e saúde dos canais.
- **Escalonamento** (se ninguém responder em X minutos, avisa outras pessoas) e **canal alternativo** quando a entrega falha de vez.
- **Central de Mensagens:** envio manual com modelos e variáveis, **prévia por destinatário**, teste para si mesmo, histórico com andamento e cancelamento.
- **Agendamento** único ou recorrente (diário, dias da semana, mensal), com calendário de dias úteis do SLA, edição, pausa, retomada e cancelamento. Quem recebe é conferido a cada envio.
- **Entrega confirmada:** o histórico separa *aceita pelo gateway*, *entregue* e *lida* quando o canal confirma.
- **Gateways** com capacidades de cada canal e limite de ritmo ajustável; vigilância periódica de todos os canais com aviso aos administradores.

### Canais

| Canal | Envio | Entrada (abrir e responder chamados pelo chat) |
|---|---|---|
| E-mail (SMTP) | Sim | — |
| WhatsApp (Meta Cloud API ou Evolution API) | Sim | Sim |
| Telegram | Sim (gratuito) | Sim (long polling, sem domínio nem porta aberta) |
| Slack | Sim | Sim |
| Navegador (Web Push) | Sim | — |

Cada pessoa vincula o próprio canal por código, e o bot respeita as mesmas permissões que ela tem no sistema.

### Segurança e conformidade

- **Permissões granulares** em português, agrupadas por módulo, com nome, descrição e risco. A tela *Acesso* mostra o acesso efetivo de cada conta e de onde vem cada permissão.
- **Permissões críticas por concessão individual** (backups, importação, zerar a base), com motivo, auditoria e aviso aos administradores.
- **Auditoria imutável:** a aplicação só insere e lê; um gatilho no banco recusa alterar ou apagar, e cada registro entra numa cadeia de hash verificada diariamente. Retenção por categoria, com exportação antes de apagar.
- **Papéis de banco separados** (dono, aplicação, Evolution): a aplicação não usa o superusuário do PostgreSQL.
- **IP do cliente confiável** (não pode ser forjado), documentação da API desligada por padrão, sessão com revogação e recuperação de senha.

### Operação

- **Worker** com laços independentes (entregas e agenda), execuções registradas, concessão renovada e retomada após queda; nenhum job roda em dobro.
- **Backup completo:** banco, anexos e logomarca, com SHA-256, verificação de integridade, cópia cifrada do `.env` e restauração testada. Backup diário automático às 02:00.
- **Ambiente de demonstração** separável, com backup automático antes de apagar o exemplo.

---

## Instalação

Pré-requisito: Docker com Compose v2 (no Windows, Docker Desktop). Em Linux, o instalador oferece instalar o Docker se faltar.

### Instalação guiada (recomendado)

Um comando gera o `.env` com senhas aleatórias, sobe o sistema e espera ele responder:

```bash
git clone <url-do-repositorio> plataforma-gestao-ti && cd plataforma-gestao-ti
scripts/install.sh                 # Linux, macOS, WSL, Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1      # Windows
```

| Opção | Efeito |
|---|---|
| `--port 8080` (`-Port` no Windows) | Porta HTTP publicada (padrão 80) |
| `--https [hosts]` | HTTPS com certificado autoassinado; hosts extras separados por vírgula |
| `--yes` | Instala o que faltar sem perguntar |
| `--check` / `--dry-run` / `--env-only` | Só verifica, só mostra o que faria, ou só gera o `.env` |

O script nunca sobrescreve um `.env` existente e pode ser repetido.

> **Guarde uma cópia da `APP_ENCRYPTION_KEY` fora do servidor.** Sem ela, as senhas de canais gravadas (como o SMTP) não podem ser lidas.

### Instalação manual

```bash
cp .env.example .env
# Obrigatórios: POSTGRES_PASSWORD, SECRET_KEY, APP_ENCRYPTION_KEY,
#               DB_OWNER_PASSWORD, DB_APP_PASSWORD, DB_EVOLUTION_PASSWORD
#   SECRET_KEY:          openssl rand -hex 32   (valores de exemplo ou curtos são recusados)
#   APP_ENCRYPTION_KEY:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d --build
```

O Nginx é a única porta publicada (`HTTP_PORT`, padrão 80); banco e API ficam na rede interna do Compose. O serviço `db-init` cria os papéis de banco e roda as migrations a cada `up`; uma falha derruba o container em vez de ser ignorada.

---

## Primeiro acesso

Abra `http://<servidor>`. O **assistente** cria o administrador e pede uma escolha:

| Opção | O que você recebe |
|---|---|
| **Base limpa** (uso real) | Nome da empresa, setor de TI e categorias iniciais de chamados e ativos (editáveis). Nenhum dado fictício. |
| **Modelo de exemplo** | Colaboradores, chamados, ativos e insumos fictícios (senha `Demo@2026`, só para conhecer) e alertas funcionando. Em Administração → Ambientes & Dados é possível apagar só o exemplo. |

---

## Canais de comunicação

Configuração em **Administração → Canais de comunicação** (uma aba por canal). Passo a passo completo em [`docs/04-configuracao-de-integracoes.md`](docs/04-configuracao-de-integracoes.md).

- **E-mail:** SMTP com senha cifrada, recuperação de senha e respeito ao horário de silêncio (falhas críticas ignoram o silêncio).
- **Telegram:** crie o bot no `@BotFather`, cole o token na aba Telegram, e cada pessoa gera o código em *Minhas preferências* e envia `/vincular CÓDIGO` ao bot. Só precisa de saída para `api.telegram.org`.
- **WhatsApp:** Meta Cloud API (oficial, exige HTTPS público para o webhook) ou Evolution API (opcional, sem custo por mensagem, **não oficial**: use chip dedicado; `docker compose --profile whatsapp up -d`). O vínculo é por `vincular CÓDIGO`.
- **Slack:** app com escopos `chat:write` e `im:history`, evento `message.im`; cole o token e o Signing Secret. Exige HTTPS público.
- **Web Push:** cada pessoa ativa em *Minhas preferências*. Funciona em `localhost` ou HTTPS (`scripts/install.sh --https`).

---

## Operação

### Worker e agenda

O serviço `worker` envia notificações, executa o backup diário (02:00, fuso `APP_TIMEZONE`, padrão America/Fortaleza), a limpeza (03:30) e a vigilância dos canais e do SLA. Saúde: `docker compose ps` e `components.worker` em `/api/v1/health`.

### Backup e restauração

- **Gerar:** Administração → Backups. O pacote traz o banco (`.sql.gz`) e, nos mais recentes, os anexos e a logomarca (`arquivos_gestao_ti_*.tar.gz`), todos com SHA-256. A retenção segue `BACKUP_MAX_KEEP`.
- **Cópia dos segredos:** `make backup-secrets` gera o `.env` cifrado, à parte.
- **Restaurar é um procedimento offline:**

  ```bash
  docker compose cp backend:/data/backups/<arquivo>.sql.gz .
  scripts/restore-backup.sh ./<arquivo>.sql.gz   # make restore FILE=./<arquivo>.sql.gz
  ```

  O script faz um dump de segurança, para o backend, restaura em transação única (aborta no primeiro erro) e religa. `scripts/verify-backup.sh` confere a integridade, a cadeia da auditoria e os anexos.
- Os arquivos ficam no volume `backups_data`: **copie-os para fora do servidor**.

---

## Atualização

```bash
git pull
docker compose up -d --build
docker compose logs -f backend
```

Migrations e seed rodam sozinhos. Faça backup antes de atualizar. Cada versão traz no [CHANGELOG](CHANGELOG.md) o que muda e o que exige ação (marcado como **Atualização**). Roteiro completo em [`docs/08-manutencao-e-atualizacao.md`](docs/08-manutencao-e-atualizacao.md).

<details>
<summary>Notas de migração de versões antigas</summary>

### Anterior à Fase D (WhatsApp pela Meta)

- O bot antigo (Evolution/Mock, QR Code, "anti-ban", `wa_outbox`, `wa_sessions`, `wa_configs`) foi removido; a migration `m3b4c5d6e7f8` apaga essas tabelas e é **irreversível**. As respostas rápidas (`wa_templates`) continuam. A Evolution voltou depois como provedor opcional (perfil `whatsapp`).
- O webhook passou a ser o da Meta (`GET` handshake + `POST` assinado com `X-Hub-Signature-256`).
- Cada pessoa precisa vincular o próprio WhatsApp por código.

### Anterior à Fase A (hub de notificações)

- Defina `APP_ENCRYPTION_KEY` no `.env`; o Compose não sobe sem ela.
- A configuração SMTP antiga é movida pela migration `j0e1f2a3b4c5` para `channel_configs`, com a senha cifrada.
- Sem o serviço `worker`, as notificações ficam em fila e nenhum backup agendado roda.

### Anterior à Fase 0

- Defina `SECRET_KEY` (≥ 32 caracteres, sem "CHANGE-ME") e `POSTGRES_PASSWORD` igual à senha atual do banco.
- Anexos saíram de `./backend/uploads` para o volume `attachments_data`; copie os antigos mantendo o caminho relativo registrado em `attachments.file_path`.
- Reenvie a logomarca em Administração (PNG/JPEG). As portas 5432 e 8000 deixaram de ser publicadas; em desenvolvimento use `docker-compose.dev.yml`.

</details>

---

## Desenvolvimento

```bash
make fe-install && make fe-build          # frontend (ou cd frontend && npm start)
cd backend && uv sync && uv run pytest    # testes (SQLite em memória)
make ci-local                             # mesmas verificações do CI, em contêineres (obrigatório antes de publicar)
```

- Testes com PostgreSQL (`-m pg`, concorrência de estoque): `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test`.
- Base de homologação (QA) descartável: `make test-db-up`, `make test-pg`, `make seed-test` — ver [`docs/11-base-de-testes-e-homologacao.md`](docs/11-base-de-testes-e-homologacao.md).
- Migrations: `make migration MSG="descrição"` e `make migrate`.
- Padrões, revisão e fluxo para agentes de IA: [`CONTRIBUTING.md`](CONTRIBUTING.md) e [`AGENTS.md`](AGENTS.md).

---

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/01-arquitetura-do-sistema.md`](docs/01-arquitetura-do-sistema.md) | Arquitetura e módulos |
| [`docs/02-instalacao-do-sistema.md`](docs/02-instalacao-do-sistema.md) | Instalação detalhada e HTTPS |
| [`docs/03-configuracao-administrativa.md`](docs/03-configuracao-administrativa.md) | Configuração administrativa |
| [`docs/04-configuracao-de-integracoes.md`](docs/04-configuracao-de-integracoes.md) | WhatsApp, Telegram, Slack |
| [`docs/05-backup-e-restauracao.md`](docs/05-backup-e-restauracao.md) | Backup e restauração |
| [`docs/06-manual-de-utilizacao.md`](docs/06-manual-de-utilizacao.md) | Manual do Service Desk |
| [`docs/09-seguranca-e-auditoria.md`](docs/09-seguranca-e-auditoria.md) | Segurança e auditoria |
| [`docs/10-solucao-de-problemas.md`](docs/10-solucao-de-problemas.md) | Solução de problemas |
| [`docs/decisions/`](docs/decisions/) | Decisões de arquitetura (ADRs) |
| [`CHANGELOG.md`](CHANGELOG.md) | Histórico de versões |

---

## Licença

Proprietário — uso interno. Todos os direitos reservados. Veja [`LICENSE.md`](LICENSE.md).

Developed by Hedú • InfraNuvem • 2026
https://infranuvem.com.br
