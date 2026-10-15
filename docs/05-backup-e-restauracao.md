# 05. Backup, Restauração e Recuperação de Desastres (DR)

Este documento define a estratégia operacional de proteção de dados, procedimentos de contingência e recuperação para a **Plataforma de Gestão de TI**.

---

## 1. Arquitetura do Mecanismo de Backup

A plataforma utiliza o utilitário nativo `pg_dump` do PostgreSQL acoplado a compressão em fluxo `gzip` e cálculo em tempo real do hash criptográfico **SHA-256**.

* **Diretório Persistente:** `/data/backups/` (montado no volume Docker `backups_data`).
* **Padrão de Nomenclatura:** `backup_gestao_ti_YYYYMMDD_HHMMSS.sql.gz`.
* **Metadados:** Cada backup é catalogado na tabela `database_backups` com tamanho, hash SHA-256, status (`SUCCESS`/`FAILED`) e identificação do administrador responsável.

---

## 2. Como Gerar um Backup

### 2.1. Pela Interface Gráfica
1. Acesse **Administração > Backup e Restauração**.
2. Clique no botão **Gerar Novo Backup**.
3. O sistema gerará o dump compactado, validará o hash e atualizará a listagem.
4. Você pode fazer o download do arquivo `.sql.gz` diretamente pelo botão de download na tabela.

### 2.2. Pela API REST
```bash
curl -X POST "http://localhost/api/v1/system/backup" \
  -H "Authorization: Bearer <TOKEN_ADMIN>"
```

### 2.3. Pela Linha de Comando (CLI no Host)
Caso o container da API esteja indisponível e seja necessário gerar um dump manual direto do banco:

```bash
docker exec -t gestao-ti-db pg_dump -U postgres -d gestao_ti --clean --if-exists | gzip > /opt/backups/backup_manual_$(date +%Y%m%d_%H%M%S).sql.gz
```

---

## 3. Validação de Integridade

Cada backup gerado tem sua integridade verificada calculando a soma SHA-256 do arquivo em disco e comparando com o registro catalogado:

1. **Pela Interface:** Clique no botão **Verificar** ao lado do backup desejado.
2. **Pela Linha de Comando:**
   ```bash
   sha256sum /var/lib/docker/volumes/plataforma-gestao-ti_backups_data/_data/backup_gestao_ti_*.sql.gz
   ```

---

## 4. Procedimentos de Restauração (Disaster Recovery)

> [!WARNING]
> A restauração substitui o estado atual do banco de dados pelos registros do backup selecionado. Realize esta operação com prévia autorização.

### 4.1. Restauração Automática via API
A plataforma disponibiliza um endpoint seguro para restauração controlada:

```bash
curl -X POST "http://localhost/api/v1/system/backup/restore/<BACKUP_ID>" \
  -H "Authorization: Bearer <TOKEN_ADMIN>"
```

### 4.2. Procedimento de Restauração Manual (Disaster Recovery)
Se o servidor for recriado do zero a partir de uma instalação limpa:

1. Transfira o arquivo de backup `.sql.gz` para o host.
2. Certifique-se de que os containers do banco estão operacionais:
   ```bash
   docker compose up -d postgres
   ```
3. Descompacte e aplique o dump diretamente no banco de dados:
   ```bash
   gunzip -c backup_gestao_ti_YYYYMMDD_HHMMSS.sql.gz | docker exec -i gestao-ti-db psql -U postgres -d gestao_ti
   ```
4. Reinicie os serviços da API para renovar os pools de conexão:
   ```bash
   docker compose restart backend
   ```

### 4.3. Teste em Ambiente Isolado
Para validar uma restauração sem impactar o ambiente operacional:
```bash
# 1. Cria banco temporário de teste
docker exec -i gestao-ti-db psql -U postgres -c "CREATE DATABASE gestao_ti_valida_dr;"

# 2. Restaura o dump no banco de teste
gunzip -c backup_gestao_ti_YYYYMMDD_HHMMSS.sql.gz | docker exec -i gestao-ti-db psql -U postgres -d gestao_ti_valida_dr

# 3. Confere a contagem de tabelas
docker exec -i gestao-ti-db psql -U postgres -d gestao_ti_valida_dr -c "SELECT count(*) FROM user_accounts; SELECT count(*) FROM sd_ticket;"

# 4. Remove o banco temporário
docker exec -i gestao-ti-db psql -U postgres -c "DROP DATABASE gestao_ti_valida_dr;"
```

---

## 5. Política de Retenção Recomendada

Para garantir conformidade e continuidade de negócios:
* **Frequência Diária:** Backup automatizado via cron às 02h00.
* **Retenção Local:** Manter os últimos 7 backups no volume `backups_data`.
* **Cópia Off-site:** Sincronizar semanalmente os dumps para armazenamento externo criptografado (S3, Cloud Storage ou storage NFS isolado).
