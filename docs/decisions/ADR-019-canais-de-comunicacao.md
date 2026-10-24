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

O que o WhatsApp já faz (verificado no código): adapter `notifications/channels/whatsapp.py` (texto livre dentro de 24 h, *template* fora da janela), webhook com assinatura HMAC, vínculo por código (`vincular CÓDIGO`), painel de saúde, retentativa e circuito no hub, regras evento → audiência → canais (`notification_rules`), e as automações de alerta do worker (garantia vencendo, estoque baixo, backup).

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

A aba E-mail recebe o SMTP e a recuperação de senha (que depende dele). "Entregas" e "Regras" continuam em *Notificações → Entregas e regras*; o card "Saúde dos canais" dali vira um resumo com link para a nova página. As rotas antigas redirecionam. Cada aba só aparece para quem tem a permissão do que ela altera (hoje: SMTP exige `system.backup.manage`; os demais canais, `notifications.manage`). Não se criam permissões novas nesta etapa.

### 2. WhatsApp para alertas: template por tipo de alerta

Em vez do template único, cada regra de alerta aponta para um **template aprovado na Meta com variáveis nomeadas por posição**, por exemplo:

> `Alerta de TI: {{1}} ativo(s) com garantia vencendo em {{2}} dias. Detalhes: {{3}}`

A configuração do canal guarda, por código de template do sistema, `{nome na Meta, idioma, parâmetros em ordem}` (os parâmetros vêm do evento: quantidade, prazo, link). O texto genérico atual permanece como **reserva** para eventos sem template próprio. O sistema traz os modelos prontos (texto sugerido para cadastrar na Meta, categoria *Utility*, `pt_BR`) para garantia vencendo, estoque baixo e falha de backup.

### 3. Testar e conferir antes de depender

- Botão **Enviar teste** para um número informado (usa o template escolhido).
- Consulta à Graph API (`message_templates`) para mostrar **Aprovado / Em análise / Rejeitado** de cada template configurado (exige o *WhatsApp Business Account ID* no cadastro).
- A conta de **teste da Meta** (número de teste, até 5 destinatários, sem custo) é o caminho recomendado para validar antes do número da empresa.

### 4. Vínculo sem webhook público (opcional, fase própria)

Além de "a pessoa envia `vincular CÓDIGO`", permitir o inverso: a pessoa informa o número em *Minhas preferências*, o sistema **envia um código por template** e ela o digita na tela. Assim o piloto recebe alertas sem expor o webhook. O webhook continua necessário para o menu conversacional (abrir/consultar chamado pelo WhatsApp).

### 5. Alerta chega a quem optou

Só recebe por WhatsApp quem **vinculou o número** (opt-in explícito, exigência da Meta). A regra pode escolher `whatsapp` fixo ou `preferred`, e fica definido um **plano B por e-mail** quando a pessoa não vinculou ou a entrega falha de forma definitiva.

## Entrega em PRs

| PR | Conteúdo | Depende de |
|---|---|---|
| **C1** | Página `/channels` com as 4 abas; move os formulários existentes e o SMTP; redirecionamentos; sem mudança de backend | — |
| **C2** | Templates por alerta (mapa no canal, parâmetros do evento), modelos prontos, **Enviar teste**, status dos templates na Meta | C1 |
| **C3** | Regras: escolher canal por regra e plano B por e-mail; seed dos alertas de garantia, estoque e backup apontando para os templates | C2 |
| **C4** | Vínculo por código enviado (sem webhook público) | C2 |
| **C5** | Homologação com conta Meta real e reescrita do `docs/04` com o passo a passo | conta da empresa |

Cada PR com testes (adapter com transporte falso, como hoje) e revisão independente.

## O que a empresa precisa providenciar (fora do código)

1. Conta **Meta Business** e app com o produto WhatsApp (Cloud API).
2. Um **número** que não esteja em uso no WhatsApp comum (ou o número de teste da Meta para começar).
3. **Token permanente** (usuário do sistema) e **App Secret**.
4. **Templates aprovados** (a aprovação leva de minutos a dias).
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
