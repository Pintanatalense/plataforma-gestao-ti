# 10. Guia de Solução de Problemas (Troubleshooting)

Este guia prático fornece instruções passo a passo para identificar, diagnosticar e solucionar as principais ocorrências operacionais da **Plataforma de Gestão de TI**.

---

## 1. Problemas com Banco de Dados e Conectividade

### Sintoma: API retornando `HTTP 500` com erro de conexão ao PostgreSQL
* **Causa Provável:** O container `gestao-ti-db` não inicializou a tempo, está reiniciando ou as credenciais do `.env` divergiram do banco já inicializado.
* **Comandos de Diagnóstico:**
  ```bash
  docker compose ps
  docker logs gestao-ti-db --tail 50
  ```
* **Solução:**
  1. Verifique se o container do banco está em estado `healthy`:
     ```bash
     docker inspect --format='{{.State.Health.Status}}' gestao-ti-db
     ```
  2. Teste a conexão manual pelo cliente psql:
     ```bash
     docker exec -it gestao-ti-db psql -U postgres -d gestao_ti -c "SELECT 1;"
     ```
  3. Caso o PostgreSQL recuse a autenticação após alteração de senha no `.env`, lembre-se de que a alteração de senha em container já inicializado exige comando `ALTER USER` dentro do banco.

---

## 2. Falhas no Envio de E-mails e Notificações (SMTP)

### Sintoma: Teste de envio SMTP falha com `Authentication failed` ou `Timeout`
* **Causa 1 (Gmail / Office365):** Tentativa de utilizar a senha padrão da conta ao invés de uma **Senha de Aplicativo (App Password)** dedicada com 2FA.
  * **Solução:** No provedor de e-mail corporativo, acesse as configurações de segurança, gere uma *Senha de Aplicativo* exclusiva para o sistema e cole-a no campo Senha do painel administrativo.
* **Causa 2 (Porta ou Tipo de Segurança Incompatíveis):**
  * Porta `587` requer segurança **`STARTTLS`**.
  * Porta `465` requer segurança **`SSL_TLS`**.
  * Porta `25` requer segurança **`NONE`**.
* **Comando de Teste Manual na API:**
  ```bash
  docker exec -it gestao-ti-api python -c "
  import asyncio
  from app.database import AsyncSessionLocal
  from app.notifications.email_service import EmailService, SmtpTestEmailRequest
  async def run():
      async with AsyncSessionLocal() as session:
          s = EmailService(session)
          ok, msg = await s.test_smtp(SmtpTestEmailRequest(target_email='admin@empresa.com.br'))
          print('Resultado:', ok, msg)
  asyncio.run(run())
  "
  ```

---

## 3. Problemas na Integração com WhatsApp (Evolution API)

### Sintoma: Status exibindo `FAILED` ou `DISCONNECTED`
* **Causa 1 (Container não iniciado):** A Evolution API não foi iniciada com o perfil correspondente.
  * **Solução:** Execute `docker compose --profile evolution up -d`.
* **Causa 2 (URL incorreta):** A API do sistema roda na mesma rede interna Docker que a Evolution API. A URL recomendada no painel é `http://gestao-ti-evolution:8084` (ou `http://host.docker.internal:8084`).
* **Causa 3 (Instância desconectada):** O smartphone foi desconectado ou a sessão foi revogada.
  * **Solução:** Na aba **WhatsApp & Anti-Ban > Conexão & Gateway**, clique em **Conectar WhatsApp (QR Code)** e escaneie o novo código gerado.

---

## 4. Botão "Limpar Dados de Demonstração" Bloqueado

### Sintoma: O botão aparece desabilitado ou exibe aviso de bloqueio
* **Causa 1 (Ausência de Backup Recente):** O sistema impede a limpeza por segurança se não houver um backup íntegro gerado recentemente.
  * **Solução:** Acesse a aba **Backup e Restauração**, clique em **Gerar Novo Backup** e aguarde a conclusão. Em seguida, retorne à aba **Ambientes & Dados** e clique em **Atualizar Diagnóstico**.
* **Causa 2 (Frase de Confirmação Incorreta):** O modal exige estritamente a frase `LIMPAR DADOS DE DEMONSTRACAO` em maiúsculas e sem acento.

---

## 5. Falhas no Upload de Arquivos e Anexos

### Sintoma: Erro ao anexar prints ou evidências em chamados
* **Causa:** Falta de permissões de escrita no diretório `/data/attachments` dentro do container da API.
* **Solução:**
  ```bash
  docker exec -u 0 gestao-ti-api chown -R 1000:1000 /data/attachments
  docker exec -u 0 gestao-ti-api chmod -R 775 /data/attachments
  ```

---

## 6. Critérios para Escalonamento de Incidentes

| Nível de Severidade | Critério de Ocorrência | Ação Imediata |
| :--- | :--- | :--- |
| **Severidade 1 (Crítica)** | Queda total do banco de dados ou indisponibilidade completa do portal web. | Acionar DevOps/DBA; verificar recursos de disco e aplicar procedimento de restauração de desastres (DR). |
| **Severidade 2 (Alta)** | Falha nos envios de e-mails de chamados ou instabilidade da Evolution API. | Validar credenciais no painel administrativo; reiniciar container de integração sem paralisar o Service Desk. |
| **Severidade 3 (Baixa)** | Dúvidas em parametrização de templates ou configuração de setores. | Consultar manual de utilização (Doc 06) ou documentação administrativa (Doc 03). |
