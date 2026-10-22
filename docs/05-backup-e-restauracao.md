# 05. Backup, Restauração e Recuperação de Desastres (DR)

Estratégia operacional de proteção de dados da **Plataforma de Gestão de TI**. Este documento descreve **o que o sistema faz hoje** e, na seção 7, o que ainda **não** está coberto.

> Nos comandos abaixo, use `docker compose` a partir da pasta do projeto (onde está o `docker-compose.yml`). Os serviços se chamam `postgres`, `backend`, `worker` e `nginx`; **não há `container_name` fixo**, então comandos com `docker exec <nome>` não funcionam.

---

## 1. O que existe

| Item | Situação (conferido no código) |
|---|---|
| Motor | `pg_dump` compactado com gzip; SHA-256 calculado e guardado (`backend/app/backup/services.py`) |
| Onde fica | volume Docker `backups_data`, montado em `/data/backups` no `backend` e no `worker` |
| Nome do arquivo | `backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz` (horário UTC) |
| Catálogo | tabela `db_backups` (arquivo, tamanho, SHA-256, status, quem gerou) |
| Agendamento | job `backup.daily` do worker, **todo dia às 02:00** (não é cron); o resultado avisa os administradores (falha = prioridade crítica) |
| Retenção | por quantidade: mantém os `BACKUP_MAX_KEEP=15` mais recentes com sucesso e apaga os demais ao gerar um novo. `BACKUP_RETENTION_DAYS` existe em `config.py`, mas **não é usado** (retenção por dias não está implementada) |
| Escopo | **somente o banco de dados** (ver seção 7) |

---

## 2. Gerar um backup

### 2.1. Pela interface
Administração → **Backups do Banco de Dados** → **Gerar Backup Agora**. A tabela lista os arquivos, com download e exclusão.

### 2.2. Pela API
Permissão `system.backup.manage` (gerar, listar, verificar, excluir); o download exige `system.backup.download`:

```bash
curl -X POST "http://localhost/api/v1/system/backups/generate" -H "Authorization: Bearer <TOKEN>"
curl "http://localhost/api/v1/system/backups"                        -H "Authorization: Bearer <TOKEN>"
curl "http://localhost/api/v1/system/backups/<ID>/download" -o backup.sql.gz -H "Authorization: Bearer <TOKEN>"
curl -X DELETE "http://localhost/api/v1/system/backups/<ID>"         -H "Authorization: Bearer <TOKEN>"
```

### 2.3. Manual, direto do banco (API indisponível)
```bash
docker compose exec -T postgres pg_dump -U postgres -d gestao_ti --clean --if-exists | gzip > backup_manual_$(date +%Y%m%d_%H%M%S).sql.gz
```

> **Atenção:** `make backup` gera um `.sql` **sem gzip e sem `--clean`**, que **não** serve para `make restore`/`scripts/restore-backup.sh` (exigem `.sql.gz`). Use o comando acima ou a tela. Correção prevista no plano diretor (P2-7).

---

## 3. Verificar a integridade

* **API:** `GET /api/v1/system/backups/<ID>/verify` recalcula o SHA-256 do arquivo e compara com o registrado (`is_valid`). **Ainda não há botão na tela** (previsto em P3-4).
* **Linha de comando:** `docker compose exec backend sha256sum /data/backups/backup_gestao_ti_*.sql.gz`.

A verificação só prova que o arquivo não mudou; **não prova que ele restaura**. Faça o teste da seção 5 periodicamente.

---

## 4. Restaurar

> [!WARNING]
> A restauração **substitui** o estado atual do banco. Faça com autorização e, de preferência, em janela de manutenção.

**Não existe restauração pela API nem pela tela.** O caminho suportado é o script:

```bash
scripts/restore-backup.sh /caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz
# ou: make restore FILE=/caminho/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz
```

O script valida o `.gz`, grava um dump de segurança `pre-restore-<data>.sql.gz` **no diretório atual**, para o `backend`, restaura em transação única (`ON_ERROR_STOP`; se falhar, nada é aplicado) e religa o `backend`.

Cuidados:
* O script **não para o `worker`**. Rode `docker compose stop worker` antes e `docker compose start worker` depois (correção prevista em P2-7).
* Restaura **só o banco**: anexos e logo ficam nos volumes `attachments_data` e `static_data`.
* Em servidor recriado do zero: instale (`scripts/install.sh`), garanta o **mesmo `APP_ENCRYPTION_KEY`** do ambiente original (seção 6), suba apenas o banco (`docker compose up -d postgres`) e então rode o script.

---

## 5. Testar a restauração sem afetar o ambiente

```bash
# 1. banco temporário
docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE gestao_ti_valida_dr;"

# 2. restaura o dump nele (sem --single-transaction o psql continua após erros: confira a saída)
gunzip -c backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz | docker compose exec -T postgres psql -U postgres -d gestao_ti_valida_dr -v ON_ERROR_STOP=1 --single-transaction -q

# 3. confere dados
docker compose exec -T postgres psql -U postgres -d gestao_ti_valida_dr -c "SELECT count(*) FROM user_accounts;" -c "SELECT count(*) FROM sd_ticket;"

# 4. remove
docker compose exec -T postgres psql -U postgres -c "DROP DATABASE gestao_ti_valida_dr;"
```

---

## 6. Segredos: sem eles o backup não basta

As credenciais de SMTP, Telegram, WhatsApp, Slack e as chaves do pop-up do navegador ficam **cifradas no banco** com `APP_ENCRYPTION_KEY` (arquivo `.env`). Se o `.env` for perdido, o backup restaura os dados, mas essas credenciais ficam ilegíveis e precisam ser reconfiguradas.

* Guarde uma cópia do `.env` (principalmente `APP_ENCRYPTION_KEY`, `SECRET_KEY`, `POSTGRES_PASSWORD`) **separada** dos backups, em local seguro.
* Mudar `SECRET_KEY` apenas desloga todos; mudar `APP_ENCRYPTION_KEY` invalida as credenciais cifradas.

---

## 7. O que NÃO está coberto hoje (riscos conhecidos)

1. **Anexos e logo não entram no backup.** Faça cópia dos volumes à parte, por exemplo (ajuste o prefixo conforme `docker volume ls`):
   ```bash
   docker run --rm -v <projeto>_attachments_data:/data -v "$PWD":/backup alpine tar czf /backup/anexos_$(date +%Y%m%d).tar.gz -C /data .
   docker run --rm -v <projeto>_static_data:/data      -v "$PWD":/backup alpine tar czf /backup/static_$(date +%Y%m%d).tar.gz -C /data .
   ```
2. **Sem cópia fora do servidor.** Os backups ficam no mesmo host do banco; falha do disco perde tudo. Copie periodicamente os `.sql.gz` e as cópias dos volumes para outro local (idealmente criptografado).
3. **Sem teste automático de restauração** e sem metas de **RPO/RTO** definidas. Defina-as e agende o teste da seção 5.
4. O backup **não é criptografado** e a geração carrega o dump em memória (atenção em bases grandes).
5. Dumps `*.sql.gz` e `pre-restore-*` podem conter dados reais: o `.gitignore` os ignora, mas nunca os coloque em repositório.

O plano de correção está em `docs/plans/plano-diretor.md` (itens P2-7 e Fase 5).
