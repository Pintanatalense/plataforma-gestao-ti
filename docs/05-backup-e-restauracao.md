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
| Escopo | **banco** (`backup_gestao_ti_*.sql.gz`, incluindo o schema `evolution_api`) **e anexos + logomarca** (`arquivos_gestao_ti_*.tar.gz`, mesmo formato do `scripts/restore-backup.sh`). O pacote de arquivos fica só nos `BACKUP_FILES_MAX_KEEP=3` backups mais recentes (anexos ocupam espaço); os mais antigos ficam só com o banco. `BACKUP_INCLUDE_FILES=false` desliga o pacote. Links simbólicos não entram |
| Fora do backup, de propósito | o `.env` (senhas e `APP_ENCRYPTION_KEY`: cópia cifrada à parte, seção 6) e o volume `evolution_instances` (sessão do WhatsApp: recriável lendo o QR code de novo, ~1 minuto) |
| Papel do banco | o `pg_dump` roda com o papel da **aplicação** (`gestao_app`), que lê todas as tabelas, inclusive o schema da Evolution (só leitura); ver [ADR-022](decisions/ADR-022-papeis-de-banco.md) |

---

## 2. Gerar um backup

### 2.1. Pela interface
Administração → **Backups do Banco de Dados** → **Gerar Backup Agora**. A tabela lista os arquivos, com download do banco, download dos anexos e logomarca (ícone de pasta, nos backups que guardam o pacote) e exclusão.

### 2.2. Pela API
Permissão `system.backup.manage` (gerar, listar, verificar, excluir); o download exige `system.backup.download`. As duas são **críticas**: valem só por concessão individual, mesmo para administradores (ver `docs/09`, seção 2):

```bash
curl -X POST "http://localhost/api/v1/system/backups/generate" -H "Authorization: Bearer <TOKEN>"
curl "http://localhost/api/v1/system/backups"                        -H "Authorization: Bearer <TOKEN>"
curl "http://localhost/api/v1/system/backups/<ID>/download" -o backup.sql.gz -H "Authorization: Bearer <TOKEN>"
curl "http://localhost/api/v1/system/backups/<ID>/download-files" -o arquivos.tar.gz -H "Authorization: Bearer <TOKEN>"
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

* **API e tela:** `GET /api/v1/system/backups/<ID>/verify` (botão "Verificar integridade") recalcula o SHA-256 do banco **e do pacote de arquivos** e compara com o registrado (`is_valid` só é verdadeiro se os dois conferem; `files_valid` mostra o pacote).
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
3. cria/atualiza os papéis de banco (o dump cita o papel dono e o da Evolution; ADR-022) e para o `backend` **e o `worker`**;
4. restaura o banco em transação única (`ON_ERROR_STOP`): se falhar, nada é aplicado e os serviços voltam. Em seguida roda o `db-init`: devolve a posse das tabelas ao papel dono, reaplica as permissões da aplicação e aplica as migrations que faltarem (um backup de versão anterior sobe para a versão atual);
5. sobe o `backend` e, se houver o segundo arquivo, extrai numa pasta temporária e **só então** troca o conteúdo de anexos/logomarca (inclusive arquivos ocultos); se a extração falhar, os arquivos atuais continuam intactos;
6. sobe o `worker`.

**Se falhar depois do passo 4** (banco já restaurado, arquivos não): o script para com o `worker` desligado, informa onde estão as cópias `pre-restore-*` e o que fazer. Corrija a causa e repita o comando; só depois `docker compose start worker`. As cópias de segurança **não são apagadas** — remova-as quando confirmar que o sistema está correto.

Em servidor recriado do zero: instale (`scripts/install.sh`), garanta o **mesmo `APP_ENCRYPTION_KEY`** do ambiente original (seção 6), suba apenas o banco (`docker compose up -d postgres`) e rode o script.

---

## 5. Provar que o backup restaura (sem afetar o ambiente)

```bash
make verify-backup FILE=backups/backup_gestao_ti_AAAAMMDD_HHMMSS.sql.gz FILES=backups/arquivos_gestao_ti_AAAAMMDD_HHMMSS.tar.gz
# ou: scripts/verify-backup.sh <banco.sql.gz> [arquivos.tar.gz]
```
Cria um banco temporário, aplica o backup nele, confere tabelas, usuários, revisão de migration e a **cadeia da auditoria** (ADR-023) e, com o pacote de arquivos, que **todo anexo registrado no banco está no pacote**. Depois **remove o banco temporário** (o banco em uso não é tocado). Saída esperada: `OK: N tabelas, N usuários, migration <rev>, auditoria íntegra, N anexo(s) no banco e todos no pacote`.

**Agende** (o SHA-256 só prova que o arquivo não mudou, não que ele restaura). Exemplo de cron semanal no servidor, com os arquivos copiados do volume `backups_data`:
```bash
# /etc/cron.d/gestao-ti-verifica-backup  (domingo, 05:00)
0 5 * * 0 root cd /opt/plataforma-gestao-ti && scripts/verify-backup.sh "$(ls -t backups/backup_gestao_ti_*.sql.gz | head -1)" "$(ls -t backups/arquivos_gestao_ti_*.tar.gz | head -1)" >> /var/log/gestao-ti-verifica-backup.log 2>&1
```
O teste não roda dentro do worker de propósito: criar um banco temporário exige o superusuário, que a aplicação não tem (ADR-022). O teste de fumaça do projeto (`scripts/smoke-test.sh`, item 11) faz esse ciclo inteiro a cada mudança: gera o backup pela tela, baixa o banco e o pacote, restaura num banco temporário e confere. **Simulado manual trimestral recomendado:** restauração completa em outra máquina (seção 4, "servidor recriado do zero").

---

## 6. Segredos: sem eles o backup não basta

As credenciais de SMTP, Telegram, WhatsApp, Slack e as chaves do pop-up do navegador ficam **cifradas no banco** com `APP_ENCRYPTION_KEY` (arquivo `.env`). Se o `.env` for perdido, o backup restaura os dados, mas essas credenciais ficam ilegíveis e precisam ser reconfiguradas.

* Guarde uma cópia do `.env` **separada** dos backups e **cifrada**:
  ```bash
  make backup-secrets          # ou: scripts/backup-secrets.sh [pasta]   (padrão: ./backups-segredos)
  ```
  Gera `segredos_gestao_ti_<data>.env.enc` (AES-256, senha pedida pelo `openssl`) e `.sha256`, e confere que a cópia abre idêntica. O script recusa gravar dentro de `./backups`. Leve o arquivo para **fora do servidor** e guarde a senha em outro lugar (cofre de senhas): sem ela a cópia não abre. Para restaurar: `openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in segredos_....env.enc -out .env && chmod 600 .env`.
* Guarde também a `APP_ENCRYPTION_KEY` offline (cofre ou impressa): é a única que não pode ser refeita.
* Mudar `SECRET_KEY` apenas desloga todos; mudar `APP_ENCRYPTION_KEY` invalida as credenciais cifradas.

---

## 7. O que NÃO está coberto hoje (riscos conhecidos)

1. **Sem cópia fora do servidor automática.** Os backups ficam no mesmo host do banco; falha do disco perde tudo. Copie periodicamente o volume `backups_data` (e a cópia cifrada do `.env`) para outro local.
2. **Teste de restauração agendado depende do cron do servidor** (seção 5) e não há metas de **RPO/RTO** definidas.
3. O backup do banco e dos anexos **não é criptografado** (só a cópia do `.env` é); a geração pela tela carrega o dump em memória (atenção em bases grandes).
4. **Rotação da `APP_ENCRYPTION_KEY`** (recifrar com uma chave nova) ainda não tem procedimento.
5. O volume `evolution_instances` não entra: depois de restaurar em outra máquina, leia o QR code do WhatsApp de novo se a sessão não voltar.
6. Dumps `*.sql.gz`, `arquivos_*.tar.gz`, `pre-restore-*` e as cópias `*.env.enc` podem conter dados reais ou segredos: o `.gitignore` ignora `*.sql.gz`, `pre-restore-*`, `backups-segredos/` e `*.env.enc`; nunca os coloque em repositório.
