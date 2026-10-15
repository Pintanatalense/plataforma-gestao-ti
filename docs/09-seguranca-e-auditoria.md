# 09. Segurança da Informação, Conformidade e Auditoria

Este documento consolida os controles de segurança técnica, mecanismos de proteção de dados e práticas de auditoria implementadas na **Plataforma de Gestão de TI**.

---

## 1. Controles de Autenticação e Criptografia

* **Hashing de Credenciais:** As senhas dos usuários nunca são armazenadas em texto plano. É utilizado o algoritmo criptográfico **bcrypt** com salting automático e fator de custo adaptativo.
* **Tokens de Acesso (JWT):** A sessão utiliza JSON Web Tokens assinados com algoritmo HMAC-SHA256 utilizando o `SECRET_KEY` configurado nas variáveis de ambiente.
* **Proteção de Segredos e Chaves de Integração:**
  * As credenciais do servidor SMTP e a chave de API da Evolution API ficam salvas no banco de dados com a senha mascarada (`********`).
  * Nenhuma senha ou token de serviço é registrado em logs de aplicação ou exposto em respostas de erro da API.

---

## 2. Princípio do Menor Privilégio e Segregação de Funções

* **Controle Granular por Permissões (RBAC):** Cada endpoint da API exige uma permissão explícita (ex: `system.backup.manage`, `sd.ticket.write`, `integrations.whatsapp.manage`).
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

* **Eventos Auditados:**
  * Autenticação e bloqueios de acesso (`user.login`, `user.logout`, `user.password_changed`);
  * Mudanças de permissões e perfis de usuários;
  * Ciclo de vida completo dos chamados (`ticket.created`, `ticket.status_changed`, `ticket.interaction_added`, `ticket.closed`);
  * Movimentações de patrimônio e consumo de estoque;
  * Geração e restauração de backups (`backup.created`, `backup.restored`);
  * Execução de limpeza do ambiente demonstrativo (`system.demo.cleaned`).
* **Estrutura dos Registros de Auditoria:**
  * `id`: UUID único do evento;
  * `event_type`: Identificador padronizado da ação;
  * `entity_type` e `entity_id`: Recurso impactado;
  * `user_id`, `user_name` e `user_email`: Responsável pela ação;
  * `ip_address`: Endereço IP de origem da requisição;
  * `data`: Snapshot em JSON com dados antes e depois da modificação;
  * `created_at`: Carimbo de data/hora em UTC.

---

## 5. Recomendações Operacionais para Produção

1. **Alterar o `SECRET_KEY`:** Nunca utilizar valores padrão em servidores de produção.
2. **Habilitar HTTPS:** Configurar certificado SSL/TLS (ex: via Let's Encrypt ou Certbot) na camada do proxy Nginx.
3. **Restringir Portas no Firewall:** Manter apenas as portas 80 e 443 expostas publicamente. A porta 5432 (PostgreSQL) deve permanecer fechada para redes externas.
4. **Política de Senhas Fortes:** Exigir senhas com no mínimo 8 caracteres contendo números, letras e símbolos.
