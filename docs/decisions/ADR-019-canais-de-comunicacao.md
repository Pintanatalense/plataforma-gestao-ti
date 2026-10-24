# ADR-019 — Página "Canais de comunicação" e WhatsApp para alertas

**Status:** Proposto (2026-10-23). Nada implementado; as fases abaixo viram PRs depois da aprovação.  
**Data:** 2026-10-23  
**Depende de:** ADR-013 (hub de notificações), ADR-018 (e-mail)

## Contexto

O envio por WhatsApp **já existe no código** (ADR-013, Meta Cloud API oficial), mas nunca foi exercitado com uma conta Meta real e a configuração está espalhada:

| Canal | Onde se configura hoje |
|---|---|
| E-mail (SMTP, recuperação de senha) | Administração → aba de e-mail |
| WhatsApp, Telegram, Slack | Notificações → Entregas e regras → aba "Saúde dos canais" (um card por canal) |
| Vínculo da pessoa com o canal | Notificações → Minhas preferências |
| Respostas rápidas do chamado ("WhatsApp" no chamado) | Administração (templates do sistema) |

O que o WhatsApp já faz (verificado no código): adapter `notifications/channels/whatsapp.py` (texto livre dentro de 24 h, *template* fora da janela), webhook com assinatura HMAC, vínculo por código (`vincular CÓDIGO`), painel de saúde, retentativa e circuito no hub, regras evento → audiência → canais (`notification_rules`), as automações de alerta do worker (`automations.py`: garantia vencendo em 30 e 7 dias, estoque baixo) e o alerta de falha de backup (`jobs.py`, evento `backup.failed`). O ADR-013 §18 já registra como limite conhecido que o canal nunca foi testado contra a Meta real.

## Problemas a resolver

1. **Configuração fragmentada**: o administrador não encontra "onde ligo o WhatsApp"; o e-mail fica numa tela e os outros canais em outra.
2. **Template genérico demais**: fora da janela de 24 h o adapter envia **um único template com uma variável que recebe a mensagem inteira** (`Aviso do TI: {{1}}`). A Meta costuma reprovar corpo de template em que a variável é quase todo o texto, e o texto vira uma linha só (quebras viram ` | `). Para alertas (que são sempre fora da janela) isso é o caminho principal, então precisa ser bem feito.
3. **Sem teste fim a fim**: não há como o administrador mandar uma mensagem de teste para um número, nem ver se o template foi aprovado pela Meta.
4. **O vínculo depende do webhook público**: a pessoa precisa mandar `vincular CÓDIGO` ao número, o que exige URL HTTPS acessível pela Meta. Para só **enviar alertas**, isso é um obstáculo grande no piloto.

## Decisão

### 1. Uma página "Canais de comunicação", uma aba por gateway

Rota `/channels` (menu Administração), com abas **E-mail · WhatsApp · Telegram · Slack**. Cada aba tem a mesma estrutura:

- **Estado** no topo (Ativo / Desativado / Com erro) e botão de **teste**;
- **Configuração** do canal (os formulários de hoje, movidos);
- **Passo a passo** curto do que fazer no provedor;
- link para as **Regras** que usam o canal.

A aba E-mail recebe o SMTP e a recuperação de senha (que depende dele). "Entregas" e "Regras" continuam em *Notificações → Entregas e regras*; o card "Saúde dos canais" dali vira um resumo com link para a nova página. As rotas antigas redirecionam.

**Permissões (como o backend já exige, sem criar nenhuma nova):** a aba E-mail aceita `notifications.manage` **ou** `system.backup.manage` (`email_router.py`); WhatsApp, Telegram e Slack exigem `notifications.manage`. A rota `/channels` precisa de um guard que aceite qualquer das duas e de abas mostradas só para quem pode usá-las. Ligar a recuperação de senha continua restrito a administrador (ADR-018): conferir a permissão do endpoint ao mover o controle.

**Fora do escopo:** as "Respostas rápidas do chamado" (`wa_templates`, Administração) são textos do sistema, **não** os templates da Meta, e ficam onde estão.

### 2. WhatsApp para alertas: template por tipo de alerta

Em vez do template único, cada regra de alerta aponta para um **template aprovado na Meta com variáveis nomeadas por posição**, por exemplo:

> `Alerta de TI: {{1}} ativo(s) com garantia vencendo em {{2}} dias. Detalhes: {{3}}`

A configuração do canal guarda, por código de template do sistema (por exemplo `asset.warranty_expiring`), `{nome na Meta, idioma, parâmetros em ordem}`. O texto genérico atual permanece como **reserva** para eventos sem template próprio. O sistema traz os modelos prontos (texto sugerido para cadastrar na Meta, categoria *Utility*, `pt_BR`) para garantia vencendo, estoque baixo e falha de backup.

**Contrato novo (muda o backend, por isso fica no C2):** hoje o adapter recebe só `Message` (`title`, `body_text`, `link`, `priority`) e não consegue obter "quantidade, prazo, link". `Message` ganha dois campos opcionais, retrocompatíveis: `template_code` e `params: dict[str, str]`, preenchidos pelo `render()` (`templates.py`), gravados na entrega e lidos pelo adapter para montar as variáveis `{{n}}`. Toca `fanout`, `outbox` e `dispatcher`.

**Versões de template:** o corpo aprovado na Meta é fixo e independente do `render()`; só as variáveis mudam. Mudar a estrutura exige uma nova versão (`nome_v2`) e trocar o mapa no canal **sem apagar a v1**, para não deixar alertas sem rota durante a análise; a reserva genérica cobre o intervalo.

### 3. Testar e conferir antes de depender

- Botão **Enviar teste** para um número informado (usa o template escolhido).
- Consulta à Graph API (`message_templates`) para mostrar **Aprovado / Em análise / Rejeitado** de cada template configurado. Exige um campo novo na configuração do canal, o **WhatsApp Business Account ID** (`whatsapp_business_account_id`), hoje inexistente.
- A conta de **teste da Meta** (número de teste, até 5 destinatários, sem custo) é o caminho recomendado para validar antes do número da empresa.

### 4. Vínculo sem webhook público (opcional, fase própria)

Além de "a pessoa envia `vincular CÓDIGO`", permitir o inverso: a pessoa informa o número em *Minhas preferências*, o sistema **envia um código por template** e ela o digita na tela. Assim o piloto recebe alertas sem expor o webhook. O webhook continua necessário para o menu conversacional (abrir/consultar chamado pelo WhatsApp).

Requisitos: um **template de autenticação** (categoria *Authentication*, uma variável com o código, regras próprias da Meta) como primeira mensagem fora da janela; **endpoint novo** que valide o código digitado e grave o número informado (hoje `redeem_link_code` recebe o endereço do webhook); **limite de envios por usuário e por hora** (senão qualquer usuário dispararia mensagens para números arbitrários); e recusar número já vinculado a outra pessoa (reaproveitar `ALREADY_LINKED_ELSEWHERE`).

### 5. Alerta chega a quem optou

Só recebe por WhatsApp quem **vinculou o número** (opt-in explícito, exigência da Meta; é o que o ADR-013 §18 já diz do envio a partir do chamado). A escolha do canal por regra **já existe** (`rules.component.ts` lista os canais, inclusive `preferred`, validados em `admin_router.py`).

**Plano B por e-mail:** as regras de garantia, estoque e backup já incluem `email` junto de `in_app` e `preferred`, então quem não vinculou o WhatsApp recebe por e-mail em paralelo (o `fanout` pula o canal externo sem endereço). Decisão: manter o **e-mail em paralelo como rede de segurança** nas regras de alerta e documentar isso. Criar uma entrega de e-mail só depois de o WhatsApp esgotar as tentativas exigiria encadeamento de entregas e nova chave de idempotência, e fica fora desta etapa.

## Entrega em PRs

| PR | Conteúdo | Depende de |
|---|---|---|
| **C1** | Página `/channels` com as 4 abas e guard por permissão; extrai o SMTP e a recuperação de senha de `admin.component` para um componente próprio e move os cards de WhatsApp/Telegram/Slack; redirecionamentos; sem mudança de backend (a extração do SMTP é a parte maior) | — |
| **C2** | Contrato `Message.template_code`/`params` (fanout, outbox, dispatcher), mapa de templates no canal, modelos prontos, `whatsapp_business_account_id`, **Enviar teste** e status dos templates na Meta | C1 |
| **C3** | Regras de alerta (garantia, estoque, backup) apontando para os templates, com e-mail em paralelo documentado como plano B; ajuste da tela de regras para mostrar qual template cada uma usa | C2 |
| **C4** | Vínculo por código enviado (sem webhook público): template de autenticação, endpoint novo, limite por usuário/hora | C2 |
| **C5** | Homologação com conta Meta real e reescrita do `docs/04` com o passo a passo | conta da empresa |

Cada PR com testes (adapter com transporte falso, como hoje) e revisão independente. Cada PR de frontend e de backend gasta minutos do GitHub Actions (ver `CONTRIBUTING.md`): agrupar o trabalho de cada fase em um commit.

## O que a empresa precisa providenciar (fora do código)

1. Conta **Meta Business** e app com o produto WhatsApp (Cloud API).
2. Um **número** que não esteja em uso no WhatsApp comum (ou o número de teste da Meta para começar).
3. **Token permanente** (usuário do sistema) e **App Secret**.
4. **Templates aprovados** (a aprovação leva de minutos a dias): um por tipo de alerta (garantia, estoque, backup) e, se o vínculo por código enviado for usado, um de autenticação.
5. Para o menu conversacional: **URL HTTPS pública** para o webhook.

Custos e limites (a confirmar na Meta no momento da contratação): mensagens de template são cobradas por mensagem e variam por categoria; contas novas têm limite de destinatários únicos por dia até a verificação do negócio.

## Consequências

- O administrador ganha um só lugar para os quatro canais e consegue testar antes de ligar.
- Alertas por WhatsApp passam a ter texto estruturado, mais chance de aprovação e mensagens mais legíveis.
- Dependemos da aprovação de templates pela Meta: o prazo é externo ao projeto.
- Mudar o texto de um alerta que já tem template aprovado exige nova aprovação.

## Alternativas descartadas

- **Provedores não oficiais (Evolution, Baileys, QR Code):** já recusados no ADR-013 (risco de bloqueio do número e de termos de uso).
- **Gateway de terceiros (Twilio, Z-API):** resolvem o cadastro com a Meta, mas somam custo e outro fornecedor; reavaliar só se a conta Meta direta for inviável para a empresa.
- **Um template único com a mensagem inteira (como hoje):** simples, mas com alta chance de reprovação e texto ruim; fica só como reserva.
