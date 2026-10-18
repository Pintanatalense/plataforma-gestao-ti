# 12. Roteiro de testes em ambiente real

Tudo abaixo foi coberto por testes automatizados com serviços simulados (backend 300+, frontend 90+), **mas nunca rodou junto**: o Docker Desktop do desenvolvimento não subiu, então a pilha completa (Compose, Nginx, WebSocket, migrations em banco povoado) e os provedores reais (Telegram, Meta, Slack) **não foram exercitados**. Este roteiro existe para fechar essa lacuna, em ordem: cada etapa depende da anterior. Pare na primeira que falhar e anote o que apareceu.

Marque `[x]` ao concluir. "Esperado" diz o que deve acontecer; qualquer outra coisa é defeito a relatar (mensagem na tela + `docker compose logs --tail=80 backend worker`).

> Use uma instalação **descartável** nas etapas 1 a 4 (`docker compose down -v` apaga tudo). Só depois configure canais reais.

---

## Etapa 0 — Preparar a máquina

- [ ] Docker Desktop **aberto e com o motor rodando** (`docker info` mostra `Server:`; se só mostra `Client:`, o motor está parado).
- [ ] `git pull` na `main` (todas as fases já estão mescladas: 0, A a F, instalação).

## Etapa 1 — Instalação guiada

1. `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` (use `-Port 8080` se a 80 estiver ocupada).
2. **Esperado:** cria `.env`, constrói as imagens (alguns minutos), termina com "Sistema no ar!".
3. `docker compose ps` → `postgres`, `backend`, `worker`, `nginx` com **healthy** (o worker pode levar ~40 s).
4. `curl http://localhost/api/v1/health` → `"status": "healthy"` e `components.worker: "healthy"`.
5. Rode o script **de novo**. **Esperado:** "Arquivo .env já existe: mantido" e nada é sobrescrito.
6. Copie a `APP_ENCRYPTION_KEY` do `.env` para o seu cofre de senhas.

> Se o build falhar, envie o trecho final da saída. Já houve falha antes com a imagem do backend (dependências); está corrigida, mas nunca foi construída aqui depois das fases B a F.

## Etapa 2 — Primeiro acesso: **modelo de exemplo**

1. Abra `http://localhost`. **Esperado:** o assistente "Bem-vindo! Vamos instalar".
2. Escolha **Modelo de exemplo**; e-mail e senha de 8+ caracteres; instalar.
3. **Esperado:** entra logado no painel, com indicação de ambiente demonstrativo.
4. Confira: Chamados (6), Ativos (5), Estoque (5 itens; 3 destacados como "Estoque Baixo"), Organização (setores e colaboradores).
5. Saia e entre com `gabriel.ti@empresa.com.br` / `Demo@2026` (atendente de exemplo). **Esperado:** vê os chamados do setor de TI.
6. Tente abrir `http://localhost` de novo estando sem usuário novo: o assistente **não** deve reaparecer.

## Etapa 3 — Reinstalar e testar a **base limpa**

1. `docker compose down -v` e `scripts\install.ps1` (o `.env` é mantido).
2. No assistente, escolha **Base limpa**, informe o nome da empresa e o administrador.
3. **Esperado:** painel vazio, sem selo de demonstração.
4. Confira o catálogo inicial: Organização → setor "Tecnologia da Informação"; ao abrir chamado, 6 categorias disponíveis; Ativos → 5 categorias; Estoque → 4 categorias.
5. Abra um chamado de teste (qualquer categoria). **Esperado:** é criado e fica atribuído ao setor de TI.

## Etapa 4 — Fluxo central (sino, e-mail desligado)

Com a base limpa, crie 2 usuários pela tela de Usuários: um com perfil **Solicitante** e um com **Atendente** (o Atendente precisa de colaborador do setor de TI).

1. Como Solicitante, abra um chamado. **Esperado:** o sino do Atendente ganha uma notificação **sem recarregar a página** (WebSocket via Nginx).
2. Como Atendente, assuma o chamado e mude o status. **Esperado:** o Solicitante recebe no sino.
3. Como Atendente, escreva uma **nota interna**. **Esperado:** o Solicitante **não** recebe nada (regra DEC-012).
4. Escreva uma resposta normal. **Esperado:** o Solicitante recebe.
5. Em Notificações → Preferências: ative o horário de silêncio e desligue uma categoria; repita um evento e confira que o sino continua funcionando sempre.
6. Como administrador, abra Notificações → Entregas e regras: as entregas aparecem como `SENT`; em Regras, use o **simulador** com um evento de chamado.
7. Em "Saúde dos canais", confira que o worker aparece ativo e que os jobs `backup.daily`, `retention.cleanup`, `stock.low_check` e `assets.warranty_check` estão listados.

## Etapa 5 — Alertas automáticos (estoque e garantia)

Faça na instalação com o **modelo de exemplo** (Etapa 2) ou cadastre itens na base limpa (item com quantidade ≤ mínimo; ativo com garantia em até 30 dias).

1. Saúde dos canais → job `stock.low_check` → **Executar agora**.
2. **Esperado:** o administrador recebe **uma** notificação "3 itens com estoque baixo" (resumo). Execute de novo: **nenhuma** nova.
3. Repor um item acima do mínimo, esvaziar de novo e executar: o aviso volta (rearmou).
4. Job `assets.warranty_check` → **Executar agora**. **Esperado:** "2 garantias perto de vencer"; repetir não duplica.

## Etapa 6 — E-mail (SMTP)

1. Administração → aba **Servidor de E-mail (SMTP)**: servidor, porta, usuário, senha; salve e use o **teste de envio**.
2. **Esperado:** e-mail de teste chega. A senha não aparece de volta na tela (campo mascarado).
3. Gere um chamado novo: o e-mail deve chegar **fora** do horário de silêncio (20h–07h, fuso Fortaleza); dentro dele fica agendado para as 07h (o sino não atrasa).
4. Reinicie tudo (`docker compose restart`) e repita o teste de envio: confirma que a senha cifrada continua legível (mesma `APP_ENCRYPTION_KEY`).

## Etapa 7 — Backup e restauração

1. Administração → **Backups do Banco de Dados** → gerar backup. **Esperado:** arquivo `.sql.gz` com SHA-256.
2. Num ambiente **descartável**, siga [05-backup-e-restauracao.md](05-backup-e-restauracao.md) (`scripts/restore-backup.sh`). **Esperado:** dados voltam; a configuração de e-mail continua utilizável com a mesma chave.
3. No demonstrativo: Administração → **Ambientes & Dados** → **Limpar dados de demonstração** (digite a frase pedida). **Esperado:** sai só o exemplo; catálogo inicial e Matriz permanecem; você continua logado.

## Etapa 8 — Telegram (gratuito, sem HTTPS)

1. No Telegram, `@BotFather` → crie um bot e copie o token.
2. Saúde dos canais → Telegram: cole o token, habilite, salve. **Esperado:** mostra `@seu_bot`.
3. Como usuário, Notificações → Minhas preferências → **Meus canais** → Telegram → gerar código; envie `/vincular CÓDIGO` ao bot. **Esperado:** o bot confirma o vínculo.
4. No bot: `menu`; abra um chamado por ele; consulte e responda um chamado.
5. Abra um chamado pelo sistema atribuído a esse usuário. **Esperado:** chega no Telegram (e no sino).
6. Código errado 5 vezes bloqueia o remetente por 15 min.

## Etapa 9 — Slack

Exige URL HTTPS pública (túnel como Cloudflare Tunnel/ngrok serve para teste).

1. Siga a seção 3 de [04-configuracao-de-integracoes.md](04-configuracao-de-integracoes.md) (app, escopos `chat:write` e `im:history`, evento `message.im`, Messages Tab).
2. Saúde dos canais → Slack: token `xoxb-`, Signing Secret; salve (valida em `auth.test`). Habilite.
3. No Slack, em Event Subscriptions, cole a Request URL exibida. **Esperado:** "Verified".
4. Gere o código em Meus canais → Slack e envie `vincular CÓDIGO` na conversa direta com o app. **Esperado:** confirma o vínculo.
5. Atribua um chamado a esse usuário. **Esperado:** mensagem direta no Slack, com link "Abrir no sistema".

## Etapa 10 — WhatsApp (Meta Cloud API)

Exige conta Meta for Developers, número de teste, URL HTTPS pública e, para fora da janela de 24 h, um template aprovado. Roteiro em [04-configuracao-de-integracoes.md](04-configuracao-de-integracoes.md), seção 2.

1. Saúde dos canais → WhatsApp: token, App Secret, Phone Number ID, template (se tiver); salve. **Esperado:** mostra o número validado.
2. Na Meta, configure o webhook com a URL e o token de verificação exibidos. **Esperado:** handshake aceito.
3. Do seu celular, envie `vincular CÓDIGO` ao número. **Esperado:** confirmação.
4. Mande `menu`; abra e consulte chamados.
5. Aguarde passar 24 h sem escrever e atribua um chamado: deve ir pelo **template**; sem template configurado, a entrega falha com explicação clara no painel.

## Etapa 10b — Pop-up do navegador (Web Push)

Funciona em `http://localhost` (contexto seguro) ou em HTTPS com certificado confiável (docs/02, seção 7).

1. Em Minhas preferências, cartão **Pop-up no navegador** → **Ativar neste navegador** → permita as notificações.
2. **Enviar teste**. **Esperado:** em alguns segundos aparece o pop-up do sistema operacional (com a aba em primeiro plano ele **não** aparece, de propósito: o sino já avisa; troque de aba ou minimize).
3. **Feche a aba do sistema** (deixe o navegador aberto). Em outro navegador/janela anônima, como outro usuário, responda um chamado do primeiro. **Esperado:** pop-up no seu desktop; clicar abre o sistema no chamado.
4. Responda várias vezes no mesmo chamado: os avisos se fundem em um só.
5. Em Preferências, desligue o canal "Pop-up no navegador" e repita: nada chega; o sino continua.
6. **Desativar** no cartão e conferir que o teste passa a ser recusado.
7. Com certificado autoassinado (`-Https`): sem importar `certs/server.crt` o cartão deve avisar/falhar; depois de importar e reiniciar o navegador, funciona em `https://nome-do-certificado`.

## Etapa 11 — Atualização de uma instalação antiga (só se houver uma)

Se existir instalação anterior com dados reais:

1. **Backup antes** (Etapa 7). A migration da Fase D apaga `wa_outbox`, `wa_sessions` e `wa_configs` de forma **irreversível**.
2. Defina `APP_ENCRYPTION_KEY` no `.env`, `git pull`, `docker compose up -d --build`, `docker compose logs -f backend`.
3. **Esperado:** migrations aplicam sem erro; a senha SMTP antiga continua funcionando (foi cifrada pela migration `j0e1f2a3b4c5`); login funciona; chamados antigos aparecem.

---

## O que relatar quando algo falhar

1. Em qual etapa e passo, e o que você esperava ver.
2. Mensagem exata na tela (ou captura).
3. `docker compose ps` e `docker compose logs --tail=80 backend worker nginx`.
4. Nunca cole tokens, senhas ou o conteúdo do `.env`.
