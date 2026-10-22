# 10. Guia de Solução de Problemas (Troubleshooting)

Este guia prático fornece instruções passo a passo para identificar, diagnosticar e solucionar as principais ocorrências operacionais da **Plataforma de Gestão de TI**.

---

## 1. Problemas com Banco de Dados e Conectividade

### Sintoma: API retornando `HTTP 500` com erro de conexão ao PostgreSQL
* **Causa Provável:** O serviço `postgres` não inicializou a tempo, está reiniciando ou as credenciais do `.env` divergiram do banco já inicializado.
* **Comandos de Diagnóstico:**
  ```bash
  docker compose ps
  docker compose logs postgres --tail 50
  ```
* **Solução:**
  1. Verifique se o container do banco está em estado `healthy`:
     ```bash
     docker compose ps postgres   # a coluna STATUS deve indicar (healthy)
     ```
  2. Teste a conexão manual pelo cliente psql:
     ```bash
     docker compose exec postgres psql -U postgres -d gestao_ti -c "SELECT 1;"
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

## 3. Problemas na Integração com WhatsApp (Meta Cloud API)

O canal usa somente a API oficial da Meta (veja `docs/04-configuracao-de-integracoes.md`, seção 2). Diagnóstico em Notificações > **Entregas e regras** > **Saúde dos canais**.

### Sintoma: canal WhatsApp degradado, entregas `FAILED`
* **Causa 1 (token inválido ou expirado):** use o token permanente de usuário do sistema; ao salvar, o sistema o valida na Graph API e mostra o erro da Meta.
* **Causa 2 (janela de 24 h fechada sem template):** a entrega falha de forma definitiva com a explicação no painel. Configure o template aprovado (seção 2.3 do doc 04).
* **Causa 3 (webhook não chega):** exige HTTPS público com certificado válido. Confira a URL `https://SEU_DOMINIO/api/v1/integrations/whatsapp/webhook`, o token de verificação do card e se o campo `messages` está assinado.
* **Causa 4 (assinatura rejeitada):** o App Secret salvo difere do app da Meta; o webhook é descartado por `X-Hub-Signature-256` inválida.

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
| **Severidade 2 (Alta)** | Falha nos envios de e-mail ou de um canal de notificação (Telegram, WhatsApp, Slack). | Validar credenciais no painel administrativo e a saúde do canal em Entregas e regras; o Service Desk continua operando. |
| **Severidade 3 (Baixa)** | Dúvidas em parametrização de templates ou configuração de setores. | Consultar manual de utilização (Doc 06) ou documentação administrativa (Doc 03). |
