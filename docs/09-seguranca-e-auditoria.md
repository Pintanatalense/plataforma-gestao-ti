# 09. Segurança da Informação, Conformidade e Auditoria

Este documento consolida os controles de segurança técnica, mecanismos de proteção de dados e práticas de auditoria implementadas na **Plataforma de Gestão de TI**.

---

## 1. Controles de Autenticação e Criptografia

* **Hashing de Credenciais:** As senhas dos usuários nunca são armazenadas em texto plano. É utilizado o algoritmo criptográfico **bcrypt** com salting automático e fator de custo adaptativo.
* **Tokens de Acesso (JWT):** A sessão utiliza JSON Web Tokens assinados com algoritmo HMAC-SHA256 utilizando o `SECRET_KEY` configurado nas variáveis de ambiente.
  * **Revogação (ADR-016):** cada token leva a versão de sessão do usuário (`tv`); trocar ou redefinir a senha, desativar o usuário ou mudar seus perfis incrementa a versão e derruba as sessões abertas (401). A troca da própria senha devolve um token novo para a sessão atual. O login tem limite de 30 tentativas/minuto por IP no Nginx (429), além do bloqueio de 15 min após 5 senhas erradas na conta.
* **Proteção de Segredos e Chaves de Integração:**
  * As credenciais das integrações (SMTP, Telegram, WhatsApp/Meta, Slack, chaves VAPID) ficam cifradas com Fernet (`APP_ENCRYPTION_KEY`) na tabela `channel_configs`; a interface mostra a senha mascarada (`********`) e nunca devolve o segredo. **Guarde `APP_ENCRYPTION_KEY` fora do servidor: sem ela, um backup restaurado não consegue decifrar essas credenciais.**
  * Nenhuma senha ou token de serviço é registrado em logs de aplicação ou exposto em respostas de erro da API.

---

## 2. Princípio do Menor Privilégio e Segregação de Funções

* **Controle Granular por Permissões (RBAC):** Cada endpoint da API exige uma permissão explícita (ex: `system.backup.manage`, `service_desk.tickets.manage`, `integrations.whatsapp.manage`). O catálogo único (código, módulo, rótulo, descrição e risco) fica em `backend/app/identity/permission_catalog.py`; o mapa de qual permissão protege cada rota é testado em `backend/tests/access_control/`.
* **Permissões críticas** (`system.backup.manage`, `system.backup.download`, `system.data.import` e `identity.critical.grant`): valem **só por concessão individual**, nunca por perfil e nunca pelo simples "administrador". Perfis não aceitam críticas (o sistema recusa e tira as que encontrar).
  * **Concessão inicial:** quem conclui o assistente de instalação recebe todas.
  * **Pela API:** `POST/DELETE /api/v1/identity/users/{id}/critical-permissions`, só para quem tem `identity.critical.grant`, com motivo obrigatório; ninguém concede a si mesmo; não se revoga a última concessão de `identity.critical.grant`. Revogar encerra as sessões da pessoa. Tudo vai para a auditoria e avisa os administradores (regra *Permissão crítica concedida ou revogada*).
  * **Recuperação (acesso ao servidor):** `docker compose exec backend python -m app.cli grant-critical --email <conta> --reason "<motivo>"` concede todas à conta ativa; `python -m app.cli list-critical` lista quem tem. A pessoa precisa entrar de novo.
  * **Atualização de uma instalação existente:** quem já tinha uma crítica (administrador ou perfil) recebe a concessão equivalente, registrada na auditoria; nada muda no acesso.
* **Anti-escalada de privilégio (gestão de usuários e perfis):** só administradores concedem ou retiram o papel de administrador; quem não é administrador só atribui perfis (e só cria perfis) com permissões que ele mesmo possui, não altera contas de administrador nem de quem tem mais permissões do que ele (incluindo redefinir a senha), e ninguém consegue desativar, excluir ou rebaixar o **último administrador ativo** (erro 409).
* **Isolamento de Escopo Setorial:**
  * Solicitantes só visualizam e interagem com os chamados abertos por eles próprios.
  * Técnicos atendem chamados atribuídos a si ou ao seu setor responsável.
  * Apenas administradores e coordenadores possuem acesso irrestrito a configurações globais.

---

## 3. Confidencialidade e Privacidade de Dados (DEC-012)

* **Proteção de Notas Internas de Atendimento:** O sistema diferencia categoricamente comunicações públicas de notas internas. Comentários técnicos com diagnósticos confidenciais, menções a senhas de rede ou informações sigilosas da infraestrutura **JAMAIS** são disparados para o solicitante por e-mail ou webhook de WhatsApp.
* **Validação de Entradas (Input Sanitization):** Todos os dados recebidos via REST e Webhooks passam por validação estrita de tipos, regex e tamanho com **Pydantic v2**, neutralizando ataques de injeção de payload ou Cross-Site Scripting (XSS).

---

## 4. Trilha de Auditoria Contínua

A plataforma possui um sistema de auditoria centralizado através da tabela `audit_logs`:

* **Como funciona:** o barramento interno de eventos grava na tabela `audit_logs` todo evento publicado pelos módulos (`backend/app/audit/listener.py`).
* **Eventos que existem hoje:**
  * Chamados: `ticket.created`, `ticket.status_changed`, `ticket.interaction_added`, `ticket.assigned`, `ticket.priority_changed`, `ticket.closed`, `ticket.material_added` e os eventos de vínculo, reserva, entrega, devolução e inspeção de ativos (`ticket.asset_*`);
  * Colaborador criado (`employee.created`);
  * Backups: `backup.completed` e `backup.failed`;
  * Identidade: `identity.login_success`, `identity.login_failed`, `identity.login_blocked`, `identity.user_created`, `identity.user_updated` (só os nomes dos campos alterados), `identity.user_deactivated`, `identity.password_reset_by_admin`, `identity.password_changed`, `identity.role_created`, `identity.role_updated`, `identity.role_deleted`;
  * Recuperação de senha por e-mail (ADR-018): `identity.password_reset_requested`, `identity.password_reset_completed`, `identity.password_reset_send_failed`, `identity.password_reset_configured`;
  * Empresa e e-mail: `organization.company_updated` (só os nomes dos campos), `organization.company_logo_updated`, `notifications.email_configured`;
  * Canais de notificação: `notifications.channel_unlinked` e degradação de canal;
  * Ambiente demonstrativo: `system.demo.seeded` e `system.demo.cleaned`.
* **O que NÃO é auditado hoje (limitações conhecidas):** logout (o JWT é sem estado: não há evento de saída); restauração de backup (feita por script, fora da API); importação e exportação de dados; leituras. Nenhum registro leva senha, token ou o texto digitado no campo de e-mail do login; tentativas com e-mail inexistente ficam sem usuário e só com o IP. **Risco aceito:** login com e-mail inexistente ou em conta travada grava uma linha por tentativa sem autenticação; o único freio é o `limit_req` do Nginx (30/min por IP) — não há retenção/purga da tabela.
* **Estrutura dos registros (`audit_logs`):** `id`, `event_type`, `entity_type`, `entity_id`, `data` (JSON do evento), `user_id` (nome e e-mail são derivados do usuário na consulta) e `created_at` (UTC). **Não há** coluna própria de endereço IP nem snapshot antes/depois: o IP, quando existe, vai dentro de `data` (`ip`), e as alterações guardam só os nomes dos campos mudados.
* **Consulta:** `GET /api/v1/audit` (filtros `event_type`, `entity_type`, `user` por trecho do e-mail, `date_from`, `date_to`; `limit` de 1 a 200; total no cabeçalho `X-Total-Count`), `GET /api/v1/audit/event-types` e `GET /api/v1/audit/{entity_type}/{entity_id}` (permissão `audit.read`). Tela: **Administração → Auditoria** (`/audit`).

---

## 5. Recomendações Operacionais para Produção

1. **Alterar o `SECRET_KEY`:** Nunca utilizar valores padrão em servidores de produção.
2. **Habilitar HTTPS:** Configurar certificado SSL/TLS (ex: via Let's Encrypt ou Certbot) na camada do proxy Nginx.
3. **Restringir Portas no Firewall:** Manter apenas as portas 80 e 443 expostas publicamente. A porta 5432 (PostgreSQL) deve permanecer fechada para redes externas.
4. **Política de Senhas Fortes:** Exigir senhas com no mínimo 8 caracteres contendo números, letras e símbolos.
