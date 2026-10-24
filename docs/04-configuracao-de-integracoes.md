# 04. Configuração de Integrações (WhatsApp & E-mail SMTP)

Este documento detalha o funcionamento, parametrização segura e testes de conectividade das duas principais integrações da plataforma: **WhatsApp (Meta Cloud API)**, **Telegram** e **Notificações por E-mail (SMTP)**.

---

## 1. Servidor de E-mail (SMTP) — Notificações Transacionais

O módulo de e-mail é responsável por alertar os usuários sobre o ciclo de vida dos chamados no Service Desk.

### 1.1. Configuração dos Parâmetros SMTP
1. Acesse **Administração > Canais de comunicação > E-mail** (quem tem `notifications.manage` ou `system.backup.manage`).
2. Ative a chave **Notificações por E-mail**.
3. Preencha os dados do provedor da empresa:
   * **Servidor (Host):** Ex: `smtp.gmail.com`, `smtp.office365.com` ou servidor interno Postfix.
   * **Porta:** `587` (STARTTLS) ou `465` (SSL/TLS).
   * **Segurança da Conexão:** Selecione `STARTTLS` ou `SSL_TLS`.
   * **Usuário / E-mail de Autenticação:** Conta de envio (Ex: `suporte@empresa.com.br`).
   * **Senha / App Password:** Digite a senha de aplicativo gerada no provedor.
   * **E-mail do Remetente (From):** Endereço que constará no cabeçalho.
   * **Nome de Exibição:** Ex: `Service Desk - Gestão de TI`.
   * **URL Base da Plataforma:** URL pública da instalação (Ex: `https://chamados.empresa.com.br`) usada para gerar links diretos nos e-mails.
4. Clique em **Salvar Parâmetros SMTP**.
   > *Nota de Segurança:* As credenciais são armazenadas criptografadas na tabela `system_settings` e a senha é mascarada (`********`) no retorno de APIs e interfaces.

### 1.2. Teste de Envio de Validação
Antes de ativar as notificações em ambiente de produção:
1. No card **Validação de Conectividade**, informe seu e-mail no campo **E-mail de Destino para Teste**.
2. Clique no botão **Enviar E-mail de Teste**.
3. O sistema executará o handshake TLS, autenticação SMTP e o envio de uma mensagem de validação contendo carimbo de data e hora.

### 1.3. Regra de Privacidade e Sigilo DEC-012
A plataforma implementa a política de privacidade **DEC-012**:
* Quando um técnico adiciona uma **Nota Interna (`is_internal = True`)**, essa mensagem é estritamente sigilosa. O sistema **JAMAIS** envia notificação por e-mail para o solicitante.
* Apenas **respostas públicas** (`is_internal = False`) disparam alertas para o cliente solicitante.
* Quando o solicitante responde no chamado, o técnico responsável atribuído é notificado por e-mail com link de acesso rápido.

---

## 2. WhatsApp

O canal tem **dois provedores** (escolha na aba **Administração > Canais de comunicação > WhatsApp**; veja o [ADR-019](decisions/ADR-019-canais-de-comunicacao.md)):

* **Evolution API** (sem custo por mensagem): seção 2.0 abaixo.
* **Meta Cloud API** (oficial, cobra por mensagem de template): seções 2.1 a 2.6.

### 2.0. Evolution API (opcional, não oficial)

**Riscos que você aceita ao usar este provedor:** a Evolution controla o WhatsApp Web por trás dos panos. O WhatsApp pode **desconectar a sessão** a qualquer momento e pode **banir o número**. Por isso: use um **chip dedicado** (nunca o WhatsApp pessoal de alguém), mantenha o **e-mail** ligado nas regras de alerta e peça o vínculo só a quem quer receber.

1. No `.env`, defina `EVOLUTION_API_KEY` (os instaladores já geram uma; em instalações antigas use `openssl rand -hex 24`). O serviço **recusa subir** sem uma chave de pelo menos 24 caracteres.
2. Suba o serviço opcional: `docker compose --profile whatsapp up -d`. Ele não publica porta no host; só o backend e o worker o alcançam.
3. Na aba **WhatsApp**, escolha **Evolution API**, mantenha o nome da instância, marque *Canal habilitado* e **Salvar**.
4. Clique em **Conectar número** e, no celular do chip dedicado, abra *WhatsApp > Aparelhos conectados > Conectar um aparelho* e leia o QR code (ele troca sozinho). O estado muda para *Conectado*.
5. **Teste:** com o canal habilitado e salvo, informe seu número (DDI + DDD) em **Enviar teste**. A mensagem vai na hora e o resultado aparece na tela (até 5 testes por hora; só os 4 últimos dígitos ficam na auditoria).
6. **Vínculo das pessoas (sem endereço público):** cada pessoa abre **Notificações > Minhas preferências**, gera o código do WhatsApp e envia `vincular CÓDIGO` ao número da empresa (o botão abre o WhatsApp já com a mensagem). A Evolution entrega a mensagem ao sistema pela rede interna do Docker; nenhuma URL pública é necessária. Só depois do vínculo a pessoa recebe alertas e usa o menu (abrir e consultar chamado). O endereço de entrada é registrado na Evolution cada vez que você clica em **Conectar número**.
7. **Ritmo contra banimento:** o sistema espera de 1× a 1,75× o **intervalo entre mensagens** (padrão 4 s) entre um envio e outro e manda no máximo **10 mensagens por hora para a mesma pessoa**. Mensagens que esperam a vez ficam pendentes e saem sozinhas, sem gastar tentativas. Ajuste ou zere (0 desliga) na aba, se precisar.
8. **Se cair:** o estado volta para *Desconectado*. O sistema tenta reenviar por um tempo; o que esgotar as tentativas aparece como falha em *Notificações > Entregas e regras*. Leia o QR code de novo para reconectar. Mesmo sem mensagens na fila, o sistema confere a sessão a cada 5 minutos e **avisa os administradores por caixa de entrada e e-mail** (um aviso por queda, na segunda checagem seguida; nunca pelo próprio WhatsApp).

> Os alertas de **garantia vencendo**, **estoque baixo** e **falha de backup** chegam por WhatsApp a quem vinculou o número, além de caixa de entrada e e-mail. Em instalações que já existiam, a regra de falha de backup é atualizada sozinha na migração, a menos que o administrador a tenha editado.

> **Segurança da entrada de mensagens:** o caminho `/api/v1/integrations/whatsapp/evolution/` é bloqueado no Nginx (404 pela internet) e, mesmo alcançado, só vale com o segredo no cabeçalho `X-Webhook-Secret` (gerado pelo sistema, guardado cifrado). Mensagens de grupos, suas próprias e de remetentes que a Evolution só identifica por `@lid` (sem telefone) são ignoradas.

> Neste provedor não há janela de 24 h nem template: o texto vai livre. A sessão do número fica no PostgreSQL (schema `evolution_api`) e no volume `evolution_instances`. **Homologação pendente:** os formatos exatos de erro da Evolution e o comportamento de reinício ainda precisam ser confirmados com um chip real (ADR-019, fase C5).

**Meta Cloud API (oficial)** — seções 2.1 a 2.6, abaixo.

O canal WhatsApp faz parte do hub de notificações (ADR-013). Com a **Meta**, não há QR Code nem fila própria: a Meta limita a taxa e o hub faz retentativa, circuito e painel de entregas.

### 2.1. O que você precisa na Meta
1. Uma conta **Meta Business** e um app com o produto **WhatsApp** (Cloud API).
2. Um número de telefone cadastrado no app (o *Phone Number ID* aparece em WhatsApp > Configuração da API).
3. Um **token de acesso permanente** (usuário do sistema), o **App Secret** (Configurações do app > Básico) e, para falar com a equipe fora da janela de 24 h, um **template aprovado** (ver 2.3).

### 2.2. Configuração no sistema
Notificações > **Entregas e regras** > aba **Saúde dos canais** > card **WhatsApp**:

| Campo | Para quê |
|---|---|
| Token de acesso | envia mensagens (cifrado; nunca é exibido de volta) |
| App Secret | valida a assinatura `X-Hub-Signature-256` dos webhooks (cifrado) |
| Phone Number ID | identifica o número remetente |
| Versão da Graph API | padrão `v21.0` |
| Template / idioma | mensagem aprovada usada **fora** da janela de 24 h |
| Endereço do sistema | prefixo dos links enviados nas mensagens |

Ao salvar, o sistema valida o token na Graph API e descobre o número exibido. O campo **Token de verificação** é gerado pelo sistema.

### 2.3. Janela de 24 h e templates
A Meta só permite texto livre até 24 h depois da última mensagem **da pessoa**. O sistema decide sozinho:
* janela aberta → texto livre;
* janela fechada → o **template** configurado, com **uma variável** (`{{1}}`) que recebe o texto da notificação (quebras de linha viram ` | `, exigência da Meta);
* janela fechada e sem template → a entrega falha de forma definitiva com a explicação, visível no painel.

Sugestão de corpo do template (categoria *Utility*, idioma `pt_BR`): `Aviso do TI: {{1}}`.

### 2.4. Webhook (exige HTTPS público)
Em WhatsApp > Configuração > Webhook:
* **URL de callback:** `https://SEU_DOMINIO/api/v1/integrations/whatsapp/webhook`
* **Token de verificação:** o exibido no card do WhatsApp
* **Campo assinado:** `messages`

O endpoint só aceita corpo com assinatura HMAC válida (`401` caso contrário). Diferente do Telegram, que usa long polling, o WhatsApp **precisa** de um endereço HTTPS acessível pela Meta.

### 2.5. Vínculo das pessoas
Cada pessoa vai em Notificações > Minhas preferências, gera o código do WhatsApp e envia `vincular CÓDIGO` ao número da empresa (ou usa o link `wa.me`). Só então recebe avisos e usa o menu (abrir, consultar e responder chamados). Telefone digitado no cadastro do colaborador **não** vincula nada.

### 2.6. Envio a partir do chamado
O botão "WhatsApp" do chamado (respostas rápidas com templates do sistema) cria uma entrega no hub para o solicitante, **se ele tiver vinculado o WhatsApp**; senão o sistema explica o que falta. O envio fica registrado no histórico do chamado.

---

## 3. Slack

### 3.1. O que você precisa no Slack
Um app em api.slack.com/apps, instalado no workspace, com:
1. **Escopos do bot** (OAuth & Permissions): `chat:write` e `im:history`. Copie o *Bot User OAuth Token* (`xoxb-…`).
2. **App Home → Messages Tab** ligada e "Allow users to send Slash commands and messages from the messages tab" marcada (sem isso as pessoas não conseguem conversar com o app).
3. **Event Subscriptions** ligado, com o evento de bot `message.im`. O *Signing Secret* está em Basic Information.

### 3.2. Configuração no sistema
Notificações > Entregas e regras > Saúde dos canais > Slack: cole o token e o Signing Secret, informe o endereço público do sistema e salve. O sistema valida o token em `auth.test` antes de gravar. Segredos ficam cifrados e nunca voltam pela API.

### 3.3. Request URL (exige HTTPS público)
No Slack, em Event Subscriptions, informe `https://SEU-DOMINIO/api/v1/integrations/slack/events`. O Slack envia um `url_verification`; o sistema só responde se a assinatura for válida (por isso salve e **habilite** o canal antes). Requisições sem assinatura válida ou com mais de 5 minutos recebem 401.

### 3.4. Vínculo das pessoas
Cada pessoa gera o código em Notificações > Minhas preferências e envia `vincular CÓDIGO` em **conversa direta com o app** no Slack. O endereço guardado é o id do usuário Slack (`U…`). Mensagens de canais, de bots e edições são ignoradas.
