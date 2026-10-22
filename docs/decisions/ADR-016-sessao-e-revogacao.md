# ADR-016 — Sessão, revogação de tokens e limite de login

**Status:** Aceito e implementado (2026-10-22)  
**Data:** 2026-10-22  
**Complementa:** ADR-002 (autenticação própria)

## Contexto

O ADR-002 definiu JWT HS256 de 8 h, stateless. Na auditoria de 2026-10-21 ficou confirmado que:

- trocar ou redefinir a senha, desativar o usuário ou mudar seus perfis **não encerrava** as sessões já abertas: o token continuava válido até 8 h (`tests/identity/test_auth_hardening.py` chegava a fixar esse comportamento);
- as permissões vivem dentro do token, então uma mudança de perfil só valia no próximo login;
- a troca de senha não zerava o bloqueio por tentativas;
- não havia limite de tentativas de login por endereço (o bloqueio é por conta).

Isso importa agora porque a recuperação de senha por e-mail (ADR-018, futura) só é segura se a redefinição derrubar sessões abertas por quem tinha a senha antiga.

## Decisão

**Versão de sessão no banco, comparada a cada requisição.**

- `user_accounts.token_version` (inteiro, padrão 0, migration `q7a8b9c0d1e2`).
- Todo token emitido leva o claim `tv` com a versão vigente (`IdentityService._issue_token`).
- `get_token_payload` já consultava o usuário no banco a cada requisição; passa a também comparar `tv` com `token_version` e responde **401** ("Sessão encerrada. Entre novamente.") se diferirem. **Custo extra: zero consultas.**
- Token **sem** `tv` (emitido antes desta mudança) vale como versão 0, que é a de todo usuário existente: **aplicar a migration não desloga ninguém**.

**A versão é incrementada quando:**

| Evento | Quem cai |
|---|---|
| Troca da própria senha | todas as outras sessões; a atual recebe token novo na resposta de `POST /identity/me/password` |
| Redefinição de senha por administrador | todas as sessões do usuário |
| Desativação, reativação ou exclusão do usuário | todas as sessões do usuário |
| Mudança de `is_admin` ou do conjunto de perfis do usuário | todas as sessões do usuário (as permissões do token ficam corretas no próximo login) |
| Alteração das permissões de um perfil ou exclusão do perfil | só as sessões de quem tem aquele perfil |

Edições que não mudam nada (mesmo `is_admin`, mesmos perfis) **não** derrubam a sessão.

**Além disso:** troca e redefinição de senha zeram `failed_login_count` e `locked_until`.

**Limite de tentativas de login por IP no Nginx:** `limit_req_zone` de 30 requisições/minuto por IP, `burst=10`, resposta **429**, só em `POST /api/v1/identity/login` (`nginx/app-locations.conf`; zona declarada em `nginx.conf` e `https.conf.template`). Complementa o bloqueio por conta (5 senhas erradas → 15 min). Validado com `nginx -t` nos dois modos e com teste de carga (60 tentativas rápidas: 12 passam, 48 recebem 429; demais rotas não são afetadas).

## Alternativas consideradas

- **Lista de tokens revogados (`jti` em tabela/Redis):** cresce com o tempo, exige limpeza e, para "encerrar todas as sessões", ainda precisaria de um marcador por usuário — que é exatamente a versão. Descartada.
- **Tokens curtos + refresh token:** reduziria a janela, mas adiciona fluxo, armazenamento e telas; só vale se a duração de 8 h virar problema. Não adotado agora.
- **Ler as permissões do banco a cada requisição** (em vez do token): eliminaria o atraso de permissões, mas custa joins em toda chamada. Com a versão de sessão, o atraso fica restrito a quem não teve perfil alterado; reavaliar se necessário.

## Consequências

- Quem troca a própria senha segue logado (token novo), mas celular, outro computador etc. caem.
- O frontend (`AuthService.changeOwnPassword`) substitui o token pelo devolvido; o token não entra no objeto do usuário em memória nem no cache local.
- Uma alteração em massa de perfil derruba os usuários afetados: aviso operacional.
- O token (e portanto a permissão) continua dentro do JWT; token em `localStorage` e sem CSP no SPA seguem como risco de XSS (tratado na Fase 5 do plano diretor).
- Rollback: reverter o PR; a coluna pode permanecer sem efeito (ou ser removida pelo downgrade da migration).
