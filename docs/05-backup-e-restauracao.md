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

### 2.3. Pela linha de comando: banco **e** arquivos (recomendado para cópia completa)
```bash
make backup            # ou: scripts/backup.sh
```
Gera em `./backups` (ou `BACKUP_DIR`):
* `backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz` — banco, no mesmo formato dos backups da tela;
* `arquivos_AAAAMMDD_HHMMSS.tar.gz` — **anexos e logomarca** (volumes `attachments_data` e `static_data`).

Cada arquivo é verificado ao final (gzip íntegro; dump com a marca `dump complete`; tar legível) e, se algo falhar, nada fica pela metade. Requer os serviços `postgres` e `backend` no ar. No Windows, use o Git Bash. **Mudança:** `make backup` antes gravava `backups/backup_*.sql` (sem gzip, só banco); agora grava `backup_gestao_ti_*.sql.gz` e `arquivos_*.tar.gz` — ajuste rotinas que dependiam do formato antigo.

Só o banco, sem os scripts:
```bash
docker compose exec -T postgres pg_dump -U postgres -d gestao_ti --clean --if-exists | gzip > backup_manual_$(date +%Y%m%d_%H%M%S).sql.gz
```

---

## 3. Verificar a integridade

* **API:** `GET /api/v1/system/backups/<ID>/verify` recalcula o SHA-256 do arquivo e compara com o registrado (`is_valid`). **Ainda não há botão na tela** (previsto em P3-4).
* **Linha de comando:** `docker compose exec backend sha256sum /data/backups/backup_gestao_ti_*.sql.gz`.

A verificação só prova que o arquivo não mudou; **não prova que ele restaura**. Faça o teste da seção 5 periodicamente.

---

## 4. Restaurar

> [!WARNING]
> A restauração **substitui** o estado atual do banco (e dos arquivos, se informados). Faça com autorização e, de preferência, em janela de manutenção.

**Não existe restauração pela API nem pela tela.** O caminho suportado é o script, a partir da pasta do projeto:

```bash
scripts/restore-backup.sh backups/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz backups/arquivos_AAAAMMDD_HHMMSS.tar.gz
# ou: make restore FILE=backups/backup_....sql.gz FILES=backups/arquivos_....tar.gz
```
O segundo arquivo (anexos e logomarca) é opcional; sem ele só o banco é restaurado e o script avisa.

O que o script faz, em ordem (**nada é alterado antes do passo 3**):
1. valida os arquivos (`gzip -t` / `tar -t`) e recusa um tar com caminhos fora de `data/attachments` e `app/static` (ou com `..`);
2. grava cópias de segurança **no diretório atual** e confere que estão completas: `pre-restore-<data>.sql.gz` (banco) e, se for restaurar arquivos, `pre-restore-arquivos-<data>.tar.gz` (anexos e logo **atuais**). Se alguma falhar, **para antes de mexer em qualquer coisa**;
3. para o `backend` **e o `worker`**;
4. restaura o banco em transação única (`ON_ERROR_STOP`): se falhar, nada é aplicado e os serviços voltam;
5. sobe o `backend` e, se houver o segundo arquivo, extrai numa pasta temporária e **só então** troca o conteúdo de anexos/logomarca (inclusive arquivos ocultos); se a extração falhar, os arquivos atuais continuam intactos;
6. sobe o `worker`.

**Se falhar depois do passo 4** (banco já restaurado, arquivos não): o script para com o `worker` desligado, informa onde estão as cópias `pre-restore-*` e o que fazer. Corrija a causa e repita o comando; só depois `docker compose start worker`. As cópias de segurança **não são apagadas** — remova-as quando confirmar que o sistema está correto.

Em servidor recriado do zero: instale (`scripts/install.sh`), garanta o **mesmo `APP_ENCRYPTION_KEY`** do ambiente original (seção 6), suba apenas o banco (`docker compose up -d postgres`) e rode o script.

---

## 5. Provar que o backup restaura (sem afetar o ambiente)

```bash
make verify-backup FILE=backups/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz   # ou: scripts/verify-backup.sh ...
```
Cria um banco temporário, aplica o backup nele, confere tabelas, usuários e a revisão de migration e **remove o banco temporário** (o banco em uso não é tocado). Saída esperada: `OK: N tabelas, N usuários, migration <rev>` (o número de tabelas muda com o esquema). Agende periodicamente: o SHA-256 só prova que o arquivo não mudou, não que ele restaura.

---

## 6. Segredos: sem eles o backup não basta

As credenciais de SMTP, Telegram, WhatsApp, Slack e as chaves do pop-up do navegador ficam **cifradas no banco** com `APP_ENCRYPTION_KEY` (arquivo `.env`). Se o `.env` for perdido, o backup restaura os dados, mas essas credenciais ficam ilegíveis e precisam ser reconfiguradas.

* Guarde uma cópia do `.env` (principalmente `APP_ENCRYPTION_KEY`, `SECRET_KEY`, `POSTGRES_PASSWORD`) **separada** dos backups, em local seguro.
* Mudar `SECRET_KEY` apenas desloga todos; mudar `APP_ENCRYPTION_KEY` invalida as credenciais cifradas.

---

## 7. O que NÃO está coberto hoje (riscos conhecidos)

1. **Anexos e logo não entram no backup da tela / do job das 02:00** (que cobrem só o banco). Use `make backup` (seção 2.3) para a cópia completa.
2. **Sem cópia fora do servidor.** Os backups ficam no mesmo host do banco; falha do disco perde tudo. Copie periodicamente `./backups` (ou o volume `backups_data`) para outro local, idealmente criptografado.
3. **Sem teste automático e agendado de restauração** e sem metas de **RPO/RTO** definidas. Defina-as e agende o `make verify-backup`.
4. O backup **não é criptografado** e a geração pela tela carrega o dump em memória (atenção em bases grandes).
5. Dumps `*.sql.gz`, `arquivos_*.tar.gz` e `pre-restore-*` podem conter dados reais: o `.gitignore` ignora `*.sql.gz` e `pre-restore-*`; nunca os coloque em repositório.

Plano de correção do restante: `docs/plans/plano-diretor.md`, Fase 5.
