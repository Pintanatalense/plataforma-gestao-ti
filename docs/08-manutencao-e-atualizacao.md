# 08. Manutenção, Atualização e Rollback

Este documento estabelece os procedimentos operacionais para a manutenção de rotina, atualização de versão e planos de contingência (rollback) da **Plataforma de Gestão de TI**.

---

## 1. Ciclo Padrão de Atualização do Sistema

Todas as atualizações do sistema devem ser executadas fora do horário de pico comercial e precedidas de um backup verificado.

### Passo 1: Geração de Backup Pré-Atualização
Antes de modificar qualquer código ou aplicar migrações:
```bash
docker exec -it gestao-ti-api python -c "
import asyncio
from app.database import AsyncSessionLocal
from app.backup.services import BackupService
async def run():
    async with AsyncSessionLocal() as session:
        b = await BackupService(session).create_backup(notes='Backup pré-atualização de versão')
        print('Backup gerado com sucesso:', b.filename)
asyncio.run(run())
"
```

### Passo 2: Obtenção do Código Atualizado
```bash
cd /opt/plataforma-gestao-ti
git fetch origin
git pull origin main
```

### Passo 2.1 (uma vez): papéis de banco separados (ADR-022)
A partir desta versão o backend, o worker e a Evolution **não usam mais o superusuário** do PostgreSQL. O `.env` precisa de três senhas novas; sem elas o `docker compose up` para com `Defina DB_..._PASSWORD no .env`. Escolha um caminho:

* rode o instalador de novo (`scripts/install.sh` ou `scripts/install.ps1`): ele mantém o `.env` e só **acrescenta** as senhas que faltam; ou
* acrescente à mão (gere cada uma com `openssl rand -hex 16`):
  ```bash
  DB_OWNER_PASSWORD=...
  DB_APP_PASSWORD=...
  DB_EVOLUTION_PASSWORD=...
  ```

No próximo `up`, o serviço `db-init` cria os papéis `gestao_owner` (dono das tabelas), `gestao_app` (backend e worker) e `gestao_evolution` (schema `evolution_api`), passa a posse das tabelas existentes ao dono e aplica as permissões. Nenhum dado é alterado. Guarde as senhas junto com o `.env` (cópia fora do servidor).

### Passo 3: Rebuild e Subida dos Containers
```bash
docker compose up -d --build
```

### Passo 4: Migrações do Banco de Dados
As migrations rodam **sozinhas** no serviço `db-init`, com o papel dono, antes de o backend subir (o backend não tem permissão de alterar a estrutura). Para conferir:
```bash
docker compose logs db-init          # "Papéis de banco: ..." e as migrations aplicadas
docker compose exec backend alembic current   # deve terminar em (head)
```
Para rodar de novo sem reiniciar o resto: `docker compose run --rm db-init` (ou `make migrate`).

### Passo 5: Verificação Pós-Atualização
```bash
curl -f http://localhost/api/v1/health || echo "ERRO NO HEALTHCHECK"
```

---

## 2. Política de Não-Destrutividade em Atualizações

* **Sem Truncates ou Deletes Automáticos:** Nenhuma migração ou script de inicialização do sistema executa exclusão de dados reais em atualizações.
* **Preservação de Configurações:** Os parâmetros de conexões SMTP e WhatsApp residem no PostgreSQL e permanecem inalterados entre atualizações de containers.

---

## 3. Procedimento de Rollback (Reversão de Falhas)

Caso uma nova versão apresente instabilidade ou quebra de compatibilidade em produção:

### 3.1. Reversão do Código e Imagens
```bash
# 1. Retornar ao commit ou tag estável anterior
git checkout <TAG_VERSAO_ANTERIOR>

# 2. Reconstruir e subir os containers da versão anterior
docker compose up -d --build
```

### 3.2. Reversão do Banco de Dados (Se Houve Migração)
Se a versão com falha aplicou migrações de esquema incompatíveis com a versão estável:

```bash
# Opção A: Downgrade via Alembic (se o script de downgrade existir), com o papel dono
docker compose run --rm db-init alembic downgrade -1

# Opção B: Restauração do Backup Pré-Atualização (Método Recomendado)
# com o backup copiado para o host (baixado pela tela de Backups):
scripts/restore-backup.sh /caminho/backup_gestao_ti_PRE_ATUALIZACAO.sql.gz
```

Voltar o **código** para uma versão anterior aos papéis separados funciona sem passo extra: a versão antiga conecta com o superusuário, que acessa tudo independentemente do dono das tabelas.

### 3.3. Voltar a usar o superusuário (papéis de banco)
Se os papéis separados (ADR-022) causarem um problema que precise de contorno imediato, sem mexer em dados: no `.env`, use o superusuário nos três papéis e suba de novo.

```bash
DB_OWNER_USER=postgres          # o mesmo valor de POSTGRES_USER
DB_OWNER_PASSWORD=<POSTGRES_PASSWORD>
DB_APP_USER=postgres
DB_APP_PASSWORD=<POSTGRES_PASSWORD>
DB_EVOLUTION_USER=postgres
DB_EVOLUTION_PASSWORD=<POSTGRES_PASSWORD>
```
```bash
docker compose up -d
```
O `db-init` ignora papel igual ao superusuário. Para voltar aos papéis separados, restaure os valores anteriores e rode `docker compose up -d`: posse e permissões são corrigidas sozinhas.

---

## 4. Comandos de Manutenção Rotineira

* **Agenda do worker** ([ADR-024](decisions/ADR-024-worker-agenda.md)): cada execução de job fica em `job_runs` (status, tentativa, duração, erro). Pela API: `GET /api/v1/notifications/admin/jobs` (inclui `retry_attempt`) e `GET /api/v1/notifications/admin/jobs/<nome>/runs`. `timeout` = passou do tempo máximo e foi encerrado; `interrupted` = o worker caiu no meio (a execução é retomada sozinha, com nova tentativa). Para separar entregas e agenda em dois contêineres, rode um com `WORKER_ROLE=delivery` e outro com `WORKER_ROLE=jobs` (cada um com o seu heartbeat: `components.worker` e `components.scheduler` no `/api/v1/health`).

* **Monitoramento de Logs em Tempo Real:**
  ```bash
  docker compose logs -f --tail=100 backend
  ```
* **Reinicialização Segura dos Serviços:**
  ```bash
  docker compose restart backend nginx
  ```
* **Limpeza de Imagens Órfãs do Docker:**
  ```bash
  docker image prune -f
  ```

## 5. Ambientes: desenvolvimento × piloto

Cada ambiente é um projeto Docker Compose com nome, arquivo de variáveis, portas e volumes próprios. Nunca compartilham banco, `SECRET_KEY` nem `APP_ENCRYPTION_KEY`.

| Ambiente | Onde | Projeto Compose | Arquivo | Portas (HTTP/HTTPS) | Uso |
|---|---|---|---|---|---|
| Desenvolvimento | máquina de desenvolvimento | `gti-dev` | `.env.dev` | 8090 / 8453 | validar PRs com PostgreSQL real; dados descartáveis |
| Piloto | máquina da empresa | `gti-piloto` | `.env` | 80 / 443 | uso real; só recebe versões marcadas e aprovadas |

```bash
# desenvolvimento
docker compose --env-file .env.dev -p gti-dev up -d --build
# piloto (na máquina da empresa, após clonar a versão aprovada)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Regras:

* O `.env`, `.env.dev` e qualquer `.env.*` ficam fora do Git (ver `.gitignore`); gere segredos novos para cada ambiente.
* Antes de atualizar o piloto: `make backup`, atualizar o código (seção 1) e conferir `docs/12-roteiro-de-testes.md`.
* "Zerar toda a base" (Admin > Ambientes) apaga os dados de trabalho e mantém usuários e configurações; use ao passar do teste para o uso real. Ele gera um backup antes.
