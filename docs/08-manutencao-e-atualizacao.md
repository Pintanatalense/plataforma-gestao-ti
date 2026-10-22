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

### Passo 3: Rebuild e Subida dos Containers
```bash
docker compose up -d --build
```

### Passo 4: Aplicação de Migrações do Banco de Dados
O processo de migração do Alembic é idempotente e estritamente aditivo:
```bash
docker compose exec backend alembic upgrade head
```

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
# Opção A: Downgrade via Alembic (se o script de downgrade existir)
docker compose exec backend alembic downgrade -1

# Opção B: Restauração do Backup Pré-Atualização (Método Recomendado)
# com o backup copiado para o host (baixado pela tela de Backups):
scripts/restore-backup.sh /caminho/backup_gestao_ti_PRE_ATUALIZACAO.sql.gz
```

---

## 4. Comandos de Manutenção Rotineira

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
