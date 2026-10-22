# 12. Roteiro de testes em ambiente real

Tudo abaixo foi coberto por testes automatizados com serviços simulados (backend 450+, frontend 230+, mais a suíte em PostgreSQL no CI), **mas nunca rodou junto**: o Docker Desktop do desenvolvimento não subiu, então a pilha completa (Compose, Nginx, WebSocket, migrations em banco povoado) e os provedores reais (Telegram, Meta, Slack) **não foram exercitados**. Este roteiro existe para fechar essa lacuna, em ordem: cada etapa depende da anterior. Pare na primeira que falhar e anote o que apareceu.

Marque `[x]` ao concluir. "Esperado" diz o que deve acontecer; qualquer outra coisa é defeito a relatar (mensagem na tela + `docker compose logs --tail=80 backend worker`).

> Use uma instalação **descartável** nas etapas 1 a 4 (`docker compose down -v` apaga tudo). Só depois configure canais reais.

---

## Etapa 0 — Preparar a máquina

- [ ] Docker Desktop **aberto e com o motor rodando** (`docker info` mostra `Server:`; se só mostra `Client:`, o motor está parado).
- [ ] `git pull` na `main` (o plano diretor das fases 1 a 3 e a recuperação de senha já estão mesclados; SLA ainda não existe).

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

## Etapa 4c — Sessões, senhas e limites (segurança)

Com 2 usuários comuns criados (A e B) e o administrador.

1. Entre como A em **dois navegadores** (ou janela anônima). Em um deles, troque a senha pelo menu do seu usuário (canto superior direito) → **Alterar Senha**. **Esperado:** o outro navegador cai para o login na próxima ação ("Sessão encerrada"); o que trocou segue logado.
2. Como administrador, em **Usuários**, use o botão **Resetar Senha** (ícone de cadeado) do usuário B. **Esperado:** aparece uma senha temporária **aleatória** (16 caracteres) para copiar, uma única vez; B perde a sessão aberta e, ao entrar com a senha temporária, é obrigado a trocá-la.
3. Digite a senha errada 5 vezes seguidas para B. **Esperado:** na 6ª tentativa, "Muitas tentativas inválidas" (conta travada por 15 min); o administrador redefinindo a senha destrava.
4. Com um usuário **sem** o perfil de administrador (A com `identity.users.update`), tente dar o papel de administrador a alguém ou mexer na conta de um administrador. **Esperado:** recusado ("Apenas administradores...").
5. Tente rebaixar/inativar o **último** administrador. **Esperado:** recusado (409).
6. Em um terminal: `for i in $(seq 1 60); do curl -s -o /dev/null -w "%{http_code} " -d "username=x@y.com&password=z" http://localhost/api/v1/identity/login; done`. **Esperado:** depois de algumas respostas `401`, passam a vir `429` (limite do Nginx por IP).

## Etapa 4d — Empresa e Auditoria

1. Organização → **Empresa**: troque o nome e envie uma logomarca PNG/JPEG/WebP de até 2 MB. **Esperado:** o menu lateral muda na hora; ao sair, a tela de **login** mostra a logo e o nome. SVG ou arquivo grande é recusado com mensagem clara.
2. Administração & Sistema → **Auditoria**: **Esperado:** aparecem seus logins, a falha de senha da Etapa 4c, a criação/alteração de usuários, a redefinição de senha, a troca de nome da empresa e da logo (cada um com usuário e data/hora; o IP aparece nos detalhes só nos eventos de login e de recuperação de senha, e as alterações de usuário e de empresa mostram apenas os **nomes dos campos** alterados). Nenhuma linha mostra senha ou token.
3. Filtre por **evento**, por trecho do **e-mail** e por **período**; use "Próxima/Anterior" (50 por página). Uma busca sem resultado mostra "Nenhum registro", e desligar o backend (`docker compose stop backend`) mostra **erro com Tentar novamente** (nunca "vazio").

## Etapa 4b — Importar inventário do GLPI Agent (XML)

Menu **Importar Inventário (GLPI)** (exige `assets.write`). Use XMLs gerados pelo GLPI Agent (`glpi-agent --tasks inventory --local <pasta>`).

1. Envie 2 ou 3 arquivos `.xml` e clique em analisar. **Esperado:** cada máquina aparece como **Novo** (série ainda não cadastrada) ou **Já cadastrado** (série igual à de um ativo).
2. Tente adicionar de novo um arquivo com o **mesmo nome**. **Esperado:** é ignorado, com aviso.
3. Nos **Novos**, preencha Patrimônio, Categoria e Unidade e confirme. **Esperado:** ativos criados em "Em estoque", com CPU, memória, disco, SO e MAC na ficha técnica.
4. Importe de novo o mesmo XML. **Esperado:** aparece como **Já cadastrado**; atualizar só refaz as especificações técnicas, sem gerar movimentação.
5. Dois XMLs com a **mesma série** no mesmo lote: o segundo falha com mensagem clara (a série já pertence a outro ativo), sem derrubar o lote.
6. XML com série de um ativo **inativo**: a análise avisa e não deixa importar.

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

## Etapa 6b — Recuperação de senha por e-mail

Depende da Etapa 6 (SMTP funcionando). **Nasce desativada**: antes de ativar, a tela de login **não** tem "Esqueci minha senha" e `POST /api/v1/identity/password-reset/request` responde 404.

1. Administração → aba de e-mail → cartão **Recuperação de senha por e-mail**. **Esperado:** botão **desabilitado** com a explicação enquanto o SMTP não estiver habilitado com **STARTTLS ou SSL/TLS** e **testado com sucesso** (use o teste de envio da Etapa 6 com a configuração salva).
2. Como **administrador**, clique em **Ativar recuperação de senha** (depois de ativo, o botão vira **Desativar recuperação de senha**). **Esperado:** uma confirmação mostra servidor, remetente e **endereço dos links** — confira que o endereço é o que os usuários acessam (`app_base_url`); confirme. (Quem só gerencia o SMTP, sem ser administrador, é recusado.)
3. Na tela de login, clique em **Esqueci minha senha**, informe o e-mail de um usuário. **Esperado:** mensagem genérica ("Se o e-mail estiver cadastrado...") — a mesma para e-mail inexistente; o e-mail com o link chega em instantes.
4. Abra o link. **Esperado:** a barra de endereço **perde o token** (`/reset-password` sem `?token=`); defina a senha nova (8+ caracteres, confirmação igual) → "Senha redefinida". Entre com a nova senha; **sessões antigas** desse usuário caem.
5. Abra o **mesmo link de novo**. **Esperado:** "Link inválido ou expirado". Peça dois links seguidos: só o **mais recente** funciona. O link vale 30 minutos.
6. Peça 4 links para o mesmo e-mail em menos de 1 hora. **Esperado:** a resposta continua igual, mas só 3 e-mails chegam.
7. Altere **qualquer** campo do SMTP (ex.: remetente) e salve. **Esperado:** a recuperação volta para **Desativada** (e some do login); é preciso testar o envio de novo e reativar.
8. Em **Auditoria**, confira os eventos de recuperação (solicitada, concluída, configurada), sem o token e sem o e-mail.

> O envio de e-mail real **nunca foi exercitado** nos testes automatizados (SMTP simulado): esta etapa é a primeira validação com o servidor da empresa. Se o link chegar com endereço errado, corrija o campo **URL Base da Plataforma (para links nos e-mails)** na configuração do SMTP.

## Etapa 7 — Backup e restauração

1. Administração → **Backups do Banco de Dados** → gerar backup. **Esperado:** arquivo `.sql.gz` com SHA-256 visível na tabela; o botão de **Verificar integridade** da linha confere o arquivo e responde "Arquivo íntegro (SHA-256 confere)". Se a lista não carregar, a tela mostra **erro com Tentar novamente** (nunca "nenhum backup").
   - Pelo terminal: `make backup` (banco + anexos/logo), `make verify-backup` e `make restore` (guia em [05](05-backup-e-restauracao.md)); o restore para o backend e o worker, valida o arquivo e guarda cópia de segurança antes de trocar os dados.
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
3. **Esperado:** migrations aplicam sem erro (inclui `q7a8b9c0d1e2` sessão por usuário, `r8b9c0d1e2f3` ajustes de índices e `s9c0d1e2f3a4` recuperação de senha); a senha SMTP antiga continua funcionando (foi cifrada pela migration `j0e1f2a3b4c5`); login funciona **sem deslogar ninguém** por causa da migration; chamados antigos aparecem.
4. Novas variáveis no `.env` (veja `.env.example`): `ENABLE_QA_SEED` (padrão `false`: o botão de carga de QA responde 403) e `ENABLE_API_DOCS`. A imagem do backend agora usa `PyJWT`: tokens já emitidos continuam válidos.
5. Recuperação de senha por e-mail vem **desativada**; ative só depois da Etapa 6b.

---

## O que relatar quando algo falhar

1. Em qual etapa e passo, e o que você esperava ver.
2. Mensagem exata na tela (ou captura).
3. `docker compose ps` e `docker compose logs --tail=80 backend worker nginx`.
4. Nunca cole tokens, senhas ou o conteúdo do `.env`.
