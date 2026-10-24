# ADR-019 — Página "Canais de comunicação" e WhatsApp para alertas

**Status:** Proposto (2026-10-23), **revisado no mesmo dia**: o provedor inicial do WhatsApp passou a ser a **Evolution API** (sem custo), mantendo a Meta Cloud API como segundo provedor. Nada implementado; as fases abaixo viram PRs depois da aprovação.  
**Data:** 2026-10-23  
**Depende de:** ADR-013 (hub de notificações), ADR-018 (e-mail)  
**Altera:** ADR-013 §14.1 (WhatsApp: "Meta Cloud API" passa a "Evolution API primeiro, Meta pronta para entrar")

## Contexto

O envio por WhatsApp **já existe no código** pela Meta Cloud API oficial (ADR-013), mas nunca foi exercitado com conta real e a configuração está espalhada:

| Canal | Onde se configura hoje |
|---|---|
| E-mail (SMTP, recuperação de senha) | Administração → aba de e-mail |
| WhatsApp, Telegram, Slack | Notificações → Entregas e regras → aba "Saúde dos canais" (um card por canal) |
| Vínculo da pessoa com o canal | Notificações → Minhas preferências |
| Respostas rápidas do chamado ("WhatsApp" no chamado) | Administração (templates do sistema) |

O que já existe e será reaproveitado: adapter `notifications/channels/whatsapp.py`, webhook com assinatura, vínculo por código (`vincular CÓDIGO`), painel de saúde, retentativa e circuito no hub, regras evento → audiência → canais (`notification_rules`), os alertas do worker (`automations.py`: garantia vencendo em 30 e 7 dias, estoque baixo; `jobs.py`: `backup.failed`).

## Decisão do dono do produto (2026-10-23)

> O projeto **não pode nascer com custos**. Usar a **Evolution API**; se houver fluxo considerável e julgarmos necessário, migrar para a API oficial. O sistema deve ficar **pronto para receber ambos**.

Isto reverte a recomendação do ADR-013 §14.1 ("Evolution só se o custo for impeditivo e o risco de banimento for aceito explicitamente"). **O risco foi aceito explicitamente** pelo dono do produto; o ADR passa a registrar como mitigá-lo (§3) em vez de evitá-lo.

## Problemas a resolver

1. **Configuração fragmentada**: o administrador não encontra "onde ligo o WhatsApp"; o e-mail fica numa tela e os outros canais em outra.
2. **Provedor único e pago**: o adapter só fala com a Meta (por mensagem de template, com aprovação prévia), o que contraria a decisão acima.
3. **Sem teste fim a fim**: não há como o administrador mandar uma mensagem de teste nem ver se o canal está conectado.
4. **O vínculo depende de URL pública**: pela Meta, o webhook precisa ser acessível da internet. Com a Evolution rodando na mesma rede do Docker, isso deixa de ser obstáculo.

## Decisão

### 1. Uma página "Canais de comunicação", uma aba por gateway

Rota `/channels` (menu Administração), com abas **E-mail · WhatsApp · Telegram · Slack**. Cada aba tem a mesma estrutura:

- **Estado** no topo (Ativo / Desativado / Com erro) e botão de **teste**;
- **Configuração** do canal (os formulários de hoje, movidos);
- **Passo a passo** curto do que fazer no provedor;
- link para as **Regras** que usam o canal.

A aba E-mail recebe o SMTP e a recuperação de senha (que depende dele). "Entregas" e "Regras" continuam em *Notificações → Entregas e regras*; o card "Saúde dos canais" dali vira um resumo com link para a nova página. As rotas antigas redirecionam.

**Permissões (como o backend já exige, sem criar nenhuma nova):** a aba E-mail aceita `notifications.manage` **ou** `system.backup.manage` (`email_router.py`); WhatsApp, Telegram e Slack exigem `notifications.manage`. A rota `/channels` precisa de um guard que aceite qualquer das duas e de abas mostradas só para quem pode usá-las. Ligar a recuperação de senha continua restrito a administrador (ADR-018): conferir a permissão do endpoint ao mover o controle.

**Fora do escopo:** as "Respostas rápidas do chamado" (`wa_templates`, Administração) são textos do sistema, **não** templates da Meta, e ficam onde estão.

### 2. WhatsApp com dois provedores atrás do mesmo canal

O canal continua sendo **um só** (`whatsapp`, uma linha em `channel_configs`), com o campo `provider`: **`evolution`** (padrão) ou **`meta`**. O `WhatsAppAdapter` deixa de falar HTTP diretamente e delega a um *driver* com o mesmo contrato:

| Operação do driver | Evolution | Meta (código atual, movido sem mudar comportamento) |
|---|---|---|
| enviar texto | `POST /message/sendText/{instância}` | texto livre na janela de 24 h |
| fora da janela | não existe (texto livre sempre) | template aprovado |
| estado da conexão | `connectionState` da instância | consulta do Phone Number ID |
| pareamento | QR code na tela do canal | token + Phone Number ID |
| entrada (mensagens recebidas) | webhook da Evolution, na rede interna | webhook com HMAC (já existe) |

Configuração por provedor (segredos continuam cifrados com Fernet):

Os endpoints da Evolution citados aqui (envio de texto, estado da conexão, QR code, webhook com cabeçalho customizado) e a necessidade ou não de Redis **não foram verificados contra uma versão real**; o C2 começa conferindo isso na documentação da versão escolhida.

- **Evolution:** `config = {provider, base_url, instance_name, display_phone, app_base_url}`, `secrets = {api_key, webhook_secret}`.
- **Meta:** como hoje (`phone_number_id`, `graph_version`, `template_name`, `template_language` · `access_token`, `app_secret`, `verify_token`).

Trocar de provedor é editar o canal e (para a Meta) cadastrar os templates; as regras, os vínculos e o histórico não mudam, porque ficam acima do driver. As mensagens são as mesmas: título, corpo e link, formatados para leitura no WhatsApp (negrito com `*…*`, uma informação por linha).

**Classificação de erros (contrato do driver):** cada driver traduz a resposta do provedor para `ok / retryable / permanent`, que é o que o hub usa para retentativa e circuito. Na Evolution: sessão desconectada, instância indisponível, erro de rede ou 5xx = `retryable`; número sem WhatsApp, destinatário inválido ou 4xx de parâmetro = `permanent`; chave inválida = `retryable` com mensagem de configuração (como o token da Meta). A tabela exata de códigos é definida no C2 contra a versão escolhida. A janela de 24 h (`ConversationSession.last_interaction_at`) passa a ser decisão **do driver Meta**, não do adapter.

**Endereço da pessoa:** os vínculos (`UserChannelAddress`) guardam o telefone **normalizado** (só dígitos, DDI 55, regra do nono dígito), igual nos dois drivers; o JID da Evolution é convertido na entrada. Sem isso, trocar de provedor quebraria vínculos e o `ALREADY_LINKED_ELSEWHERE`.

### 3. Evolution API: como rodar sem custo e reduzir o risco

A Evolution **não é oficial**: o número fica pareado por sessão (QR code), pode ser **banido pelo WhatsApp** e a sessão pode cair a cada atualização da plataforma. O custo é zero por mensagem; o único gasto é um **chip dedicado** (pré-pago). Mitigações, todas parte do desenho:

1. **Número dedicado**, nunca o WhatsApp pessoal de alguém nem o de atendimento a clientes.
2. **Só quem optou recebe**: apenas pessoas que **vincularam o número** (opt-in), e a primeira conversa parte da pessoa (`vincular CÓDIGO` para o número da empresa). Sem lista fria, sem disparo em massa.
3. **Volume baixo e ritmo humano**: alertas são poucos por dia; o adapter ganha intervalo mínimo entre envios (com variação aleatória) e limite por hora e por destinatário. A capacidade `rate_per_second` do canal cai de 10 para um valor conservador; hoje é um `ClassVar` fixo e o limite do `dispatcher` é **por canal**, não por destinatário, então "configurável", o limite por hora/destinatário e a variação aleatória são código novo do C3.
4. **Estado visível**: a aba mostra "Conectado / Desconectado / Aguardando QR code" e o último erro. Sessão caída vira alerta ao administrador **por e-mail e in-app** (nunca pelo próprio WhatsApp).
5. **E-mail em paralelo continua nas regras de alerta** (§6): se o WhatsApp cair ou o número for banido, ninguém fica sem aviso. A queda reaproveita o evento **`channel.degraded`** que já existe (regra para administradores por `in_app` e `email`, emitido em `dispatcher.py`); falta definir o gatilho da Evolution, hoje só detectável por `health()`.
6. **Isolamento de rede:** a Evolution roda como serviço **opcional** do Compose (perfil `whatsapp`), com **tag de imagem fixa**, **sem porta publicada no host**: só o backend a alcança, pela rede interna. A `api_key` dela nunca vai ao navegador: o `GET` do canal devolve só máscara/indicador, como os outros segredos. A chave global da Evolution (`AUTHENTICATION_API_KEY`) tem poder sobre todas as instâncias; deve ser forte e vir do `.env` do servidor, e o `base_url` informado pelo administrador é restrito a host interno do Compose (allowlist), para o backend não virar cliente HTTP de qualquer endereço (SSRF).
7. **Dados:** a Evolution usa o PostgreSQL do próprio Compose (banco/schema separado `evolution`, como previsto no ADR-013 §14) e guarda a sessão num volume. **Hoje o volume dela não entra no backup** (`scripts/backup.sh` cobre o dump do banco e os volumes de anexos/logo); incluí-lo, ou aceitar refazer o QR code, é decisão do C2. Perder a sessão exige novo pareamento, não perde dados do sistema. Se o schema `evolution` ficar no mesmo banco, conferir se o `pg_dump --clean` do backup e o restore devem incluí-lo. Versão, variáveis e se o cache dispensa Redis **devem ser conferidos na documentação da versão escolhida no momento da implementação** (o serviço foi removido do Compose na Fase G do ADR-013, e o histórico do Git tem a configuração antiga como ponto de partida).

### 4. Testar e conferir antes de depender

- Botão **Enviar teste** para um número informado, nos dois provedores.
- Evolution: botão **Conectar** (mostra o QR code) e **Desconectar**; atualização do estado enquanto o QR está aberto.
- Meta: consulta do status dos templates configurados (Aprovado / Em análise / Rejeitado), que exige o campo novo `whatsapp_business_account_id`. **Essa parte só é construída se/quando a migração para a Meta for decidida** (§7).

### 5. Vínculo sem URL pública

- **Caminho principal (Evolution):** a pessoa gera o código em *Minhas preferências* e envia `vincular CÓDIGO` ao número da empresa; a Evolution entrega a mensagem ao backend por **webhook interno** (rede do Docker, sem HTTPS público), autenticado por segredo (cabeçalho customizado, `compare_digest`, como o ADR-013 §250 já prevê; nunca em query string). Reaproveita `linking.py` e `ALREADY_LINKED_ELSEWHERE`.

**"Interno" precisa ser imposto, não presumido:** o roteador da API está sob `/api/` e o Nginx encaminha esse prefixo da internet para o backend. A rota do webhook da Evolution usa um caminho próprio **bloqueado no Nginx** (negado fora da rede interna), além do segredo; o backend também valida que a `instance_name` do payload é a configurada e aplica o limite de taxa que já existe (`SenderRateLimiter`). O parser de entrada da Evolution é novo: `extract_messages` e a verificação de assinatura atuais são da Meta.
- **Caminho alternativo (opcional):** a pessoa informa o número e o sistema envia o código; ela o digita na tela. Exige endpoint novo que valide o código e grave o número informado, e **limite de envios por usuário e por hora** (senão qualquer usuário dispararia mensagens para números arbitrários, o que também aumenta o risco de banimento). Na Evolution o código vai como texto comum; na Meta exigiria template de autenticação.

O menu conversacional (abrir/consultar chamado pelo WhatsApp) passa a funcionar também no piloto, porque o webhook interno não depende de domínio público.

### 6. Alerta chega a quem optou

Só recebe por WhatsApp quem **vinculou o número**. A escolha do canal por regra **já existe** (`rules.component.ts` lista os canais, inclusive `preferred`, validados em `admin_router.py`).

**Como o WhatsApp entra numa regra:** pelo canal `preferred`, que o `fanout` expande para todos os canais vinculados da pessoa. Garantia e estoque já têm `preferred` e `email`; **`backup.failed` hoje só tem `in_app` e `email`**, então o C3 precisa acrescentar `preferred` a ela. O seed só cria regras que ainda não existem (por código), então instalações já semeadas exigem **migration de dados ou edição na tela de regras**; o C3 trata isso.

**Plano B por e-mail:** quem não vinculou o WhatsApp (ou quando o número cair) recebe por e-mail em paralelo; o `fanout` pula o canal externo sem endereço. Decisão: manter o **e-mail em paralelo** nas regras de alerta e documentar. Enviar o e-mail só depois de o WhatsApp esgotar as tentativas exigiria encadeamento de entregas e nova chave de idempotência, e fica fora desta etapa.

### 7. Preparado para a Meta (construído só quando a migração for decidida)

Para "ficar pronto para receber ambos" basta o driver (§2), que já mantém o código da Meta funcionando. O que a Meta exige a mais fica **documentado, não construído**:

- **Template por tipo de alerta:** fora da janela de 24 h a Meta só aceita template aprovado, e o atual (uma variável com a mensagem inteira) tende a ser reprovado. A migração incluiria um template por alerta (garantia, estoque, backup) e o contrato novo `Message.template_code` + `params: dict[str, str]` (toca `render()`, `fanout`, `outbox` e `dispatcher`), mais versões `nome_v2` sem apagar a anterior.
- **Status dos templates** na Graph API e o campo `whatsapp_business_account_id`.
- **Template de autenticação** para o vínculo por código enviado.
- **Conta Meta Business**, número fora do WhatsApp comum, token permanente, App Secret e URL HTTPS pública para o webhook; custo por mensagem de template (a confirmar na Meta na contratação).

**Gatilhos para migrar** (sugestão, a decidir pelo dono): número banido mais de uma vez; mais de uma queda de sessão por mês; volume de alertas que torne o ritmo conservador inviável; exigência de cliente/empresa por canal oficial.

## Registro de implementação — C2 (2026-10-24)

Conferido no código da Evolution **v2.3.7** (imagem `evoapicloud/evolution-api:v2.3.7`; a tag `2.3.7` sem `v` não existe no Docker Hub):

- Autenticação por cabeçalho `apikey` (chave global `AUTHENTICATION_API_KEY` ou token da instância). Rotas: `POST /instance/create`, `GET /instance/connect/{i}`, `GET /instance/connectionState/{i}`, `DELETE /instance/logout/{i}`, `GET /instance/fetchInstances`, `POST /message/sendText/{i}` (`number`, `text`, `linkPreview`, `delay`), `POST /webhook/set/{i}` (`webhook.{url, headers, events, enabled}`; o corpo enviado inclui `apikey`).
- **Redis é opcional:** `CACHE_REDIS_ENABLED=false` com `CACHE_LOCAL_ENABLED=true` (o `.env.example` deles liga o Redis; usamos cache local para não somar um serviço).
- **Chave padrão pública no código:** sem `AUTHENTICATION_API_KEY` a Evolution usa uma chave fixa (`BQYHJGJHJ`). Por isso o serviço do Compose **recusa subir** sem chave própria de ao menos 24 caracteres.
- **Mensagens recebidas podem vir com `@lid`** em vez do telefone (há `remoteJidAlt`): o C4 precisa normalizar para o número antes de vincular.

Decisões que mudam o texto acima:

- **Endereço e chave ficam no servidor** (`EVOLUTION_BASE_URL`, `EVOLUTION_API_KEY` no ambiente do backend e do worker), não no cadastro do canal. É mais seguro que a allowlist prevista no §3 (o administrador não escolhe para onde o backend faz requisições, o que elimina o SSRF) e não deixa a chave global no banco nem na tela.
- **O provedor é escolhido no cadastro do canal** (`provider`); uma configuração sem o campo é Meta, então nada muda para quem já usa a Meta. Os segredos da Meta são mantidos ao trocar de provedor.
- **Dois pontos ficaram para os próximos PRs:** o intervalo/limite anti-banimento e o **Enviar teste** (C3), e o webhook de entrada (C4). Não há cartão de erro da Evolution homologado: a classificação de erros em `ok/retryable/permanent` foi escrita a partir do código e **precisa ser confirmada com um chip real (C5)**.
- Neste PR **o container da Evolution não foi executado** (o Docker Desktop estava parado nesta máquina): o Compose foi validado só por `docker compose config`.

### C3 (2026-10-24)

- **Entrega adiada (`DeliveryResult.deferred`)**: o ritmo e o teto por hora não dormem dentro do envio (o ciclo do worker é sequencial e um sono longo atrasaria o batimento e os outros canais) nem gastam tentativas: a entrega volta a `PENDING` com `next_attempt_at` futuro e não conta para o circuito.
- Ritmo: `Pacer` por adapter (intervalo sorteado entre 1× e 1,75× o configurado, padrão 4 s) e teto de 10 mensagens enviadas por hora por número (consulta `deliveries`), ambos em `config` e ajustáveis (0 desliga).
- **Enviar teste** é direto (fora da fila) com limite de 5 por hora por administrador e auditoria só com os 4 últimos dígitos.
- **Sessão caída**: job `whatsapp.health_check` (a cada 5 min) reaproveita o evento `channel.degraded` (que também é emitido pelo circuito do dispatcher após falhas seguidas); debounce de uma checagem e um aviso por queda, rearmado ao reconectar (`automation_marks`).
- **`backup.failed` ganhou `preferred`**; a migration `u1e2f3a4b5c6d` só altera a regra semeada intacta. A regra `channel.degraded` continua sem canais externos de propósito.
- Ainda **não homologado com chip real** (C5).

### C4 (2026-10-24)

- **Entrada**: `POST /api/v1/integrations/whatsapp/evolution/webhook`, registrada na Evolution (`POST /webhook/set/{instância}`, evento `MESSAGES_UPSERT`, cabeçalho `X-Webhook-Secret`) ao clicar em *Conectar número*, apontando para `EVOLUTION_WEBHOOK_URL` (padrão `http://backend:8000/...`, rede do Compose).
- **"Interno" imposto**: `location /api/v1/integrations/whatsapp/evolution/ { return 404; }` no Nginx (compartilhado pelos modos HTTP e HTTPS) e segredo próprio por instalação (`webhook_secret`, Fernet, comparado com `compare_digest`; a `apikey` que a Evolution coloca no corpo **não** autentica). Limite por remetente e deduplicação por id da mensagem, como na Meta.
- **`@lid`**: a v2.3.7 já troca o `remoteJid` por `remoteJidAlt` quando existe; sem telefone (`@lid` puro), grupos, mídia, `fromMe` (inclusive o eco das nossas mensagens) e outras instâncias são ignorados. Só vale `^\d{10,15}@s.whatsapp.net$`; o endereço guardado é só dígitos, como na Meta.
- **Não feito**: o vínculo "o sistema envia o código para o número informado" (opcional no §5) — o vínculo por `vincular CÓDIGO` basta para o piloto e evita enviar mensagens a números digitados.
- O segredo do webhook fica em texto claro no banco da Evolution (tabela de webhook, visível a quem tem a chave global) — inerente ao desenho. Se o registro falhar no *Conectar*, o segredo novo já está salvo e o próximo clique o reenvia.
- Ainda **não homologado com chip real** (C5): o formato exato do corpo do webhook foi lido do código da v2.3.7. O bloqueio do Nginx só foi coberto por teste do texto do arquivo: **conferir com `curl` de fora da rede no C5**.

## Entrega em PRs

| PR | Conteúdo | Depende de |
|---|---|---|
| **C1** | Página `/channels` com as 4 abas e guard por permissão; extrai o SMTP e a recuperação de senha de `admin.component` para um componente próprio e move os cards de WhatsApp/Telegram/Slack; redirecionamentos; sem mudança de backend (a extração do SMTP é a parte maior) | — |
| **C2** | Driver de WhatsApp (contrato + **driver Evolution** + driver Meta com o código atual movido sem mudar comportamento); campo `provider`; serviço `evolution` opcional no Compose (perfil `whatsapp`, tag fixa, sem porta publicada); estado da conexão e QR code; normalização do telefone; decisão sobre backup do volume e do schema | C1 |
| **C3** | **Enviar teste**; ritmo anti-banimento (intervalo, limite por hora/destinatário); texto formatado dos alertas; alerta de sessão caída ao administrador por e-mail/in-app; regras de garantia, estoque e backup com WhatsApp + e-mail documentado como plano B (inclui `preferred` em `backup.failed` e a migração das regras já semeadas); gatilho de `channel.degraded` para a Evolution | C2 |
| **C4** | Vínculo: webhook interno da Evolution (`vincular CÓDIGO`) com rota bloqueada no Nginx, parser próprio e segredo; opcionalmente, código enviado com limite por usuário/hora | C2 |
| **C5** | Homologação com um chip dedicado real e reescrita do `docs/04` com o passo a passo (instalar, parear, vincular, testar, o que fazer se cair/banir) | chip e Compose no piloto |
| *Futuro* | Itens do §7 (templates, status, autenticação), se a migração para a Meta for decidida | decisão do dono |

Cada PR com testes (driver com transporte falso, como hoje) e revisão independente. Cada PR de frontend e de backend gasta minutos do GitHub Actions (ver `CONTRIBUTING.md`): agrupar o trabalho de cada fase em um commit.

## O que a empresa precisa providenciar (fora do código)

1. Um **chip dedicado** com WhatsApp (pessoal ou Business), que não seja usado por ninguém no dia a dia, e um celular para o pareamento inicial por QR code.
2. O servidor do piloto com o Compose atualizado (o perfil `whatsapp` sobe a Evolution).
3. Aceitar que o WhatsApp pode desconectar ou banir o número, mantendo o e-mail como rede de segurança.

## Consequências

- Nenhum custo recorrente: sem cobrança por mensagem nem aprovação prévia de texto; o alerta pode mudar de texto a qualquer momento.
- O administrador ganha um só lugar para os quatro canais e consegue testar e ver a conexão.
- O vínculo e o menu conversacional passam a funcionar sem expor o sistema à internet.
- **Risco aceito:** banimento do número e quedas de sessão; a Evolution é um projeto de terceiros sem SLA, e o WhatsApp pode quebrá-la a cada atualização. As mitigações do §3 reduzem, não eliminam.
- Há um serviço a mais para operar (Evolution) e um volume a mais no backup.
- O código da Meta continua testado e disponível; migrar é trocar `provider` e cumprir o §7.

## Alternativas descartadas

- **Só a Meta Cloud API (proposta inicial deste ADR):** mais robusta e oficial, mas cobra por mensagem de template e exige conta, aprovação de templates e URL pública; contraria a decisão de não ter custos na partida.
- **Outros provedores não oficiais (Baileys direto, wppconnect):** mesmo risco de banimento sem ganho; a Evolution já foi avaliada no ADR-013 e tem API HTTP estável.
- **Gateway de terceiros pago (Twilio, Z-API):** somam custo e outro fornecedor.
- **Um template único com a mensagem inteira (Meta):** simples, mas com alta chance de reprovação; só serviria como reserva numa futura migração.
