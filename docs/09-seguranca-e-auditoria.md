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

* **Controle Granular por Permissões (RBAC):** Cada endpoint da API exige uma permissão explícita (ex: `system.backup.manage`, `sd.ticket.write`, `integrations.whatsapp.manage`).
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
  * Canais de notificação: `notifications.channel_unlinked` e degradação de canal;
  * Ambiente demonstrativo: `system.demo.seeded` e `system.demo.cleaned`.
* **O que NÃO é auditado hoje (limitações conhecidas):** login, logout e falhas de login; troca ou reset de senha; criação e alteração de usuários, perfis e permissões; alteração de empresa/logo; configuração de SMTP; restauração de backup (feita por script, fora da API); importação e exportação de dados. Previsto no plano diretor (`docs/plans/plano-diretor.md`, item P3-6).
* **Estrutura dos registros (`audit_logs`):** `id`, `event_type`, `entity_type`, `entity_id`, `data` (JSON do evento), `user_id` (nome e e-mail são derivados do usuário na consulta) e `created_at` (UTC). **Não há** campo de endereço IP nem snapshot antes/depois.
* **Consulta:** `GET /api/v1/audit` e `GET /api/v1/audit/{entity_type}/{entity_id}` (permissão `audit.read`). Ainda não existe tela.

---

## 5. Recomendações Operacionais para Produção

1. **Alterar o `SECRET_KEY`:** Nunca utilizar valores padrão em servidores de produção.
2. **Habilitar HTTPS:** Configurar certificado SSL/TLS (ex: via Let's Encrypt ou Certbot) na camada do proxy Nginx.
3. **Restringir Portas no Firewall:** Manter apenas as portas 80 e 443 expostas publicamente. A porta 5432 (PostgreSQL) deve permanecer fechada para redes externas.
4. **Política de Senhas Fortes:** Exigir senhas com no mínimo 8 caracteres contendo números, letras e símbolos.
