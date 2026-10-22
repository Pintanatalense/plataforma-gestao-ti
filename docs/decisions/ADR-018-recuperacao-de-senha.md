# ADR-018 — Recuperação de senha por e-mail

**Status:** Aceito e implementado no backend (2026-10-22); telas em PR seguinte  
**Data:** 2026-10-22  
**Depende de:** ADR-016 (versão de sessão)

## Contexto

Hoje só um administrador redefine a senha de alguém. Um usuário que esquece a senha depende dele. O sistema já tem SMTP configurável (cifrado) e a revogação de sessões do ADR-016, que é o que torna a redefinição segura (quem tinha a senha antiga perde a sessão).

## Decisão

Recuperação por link de uso único enviado por e-mail, **desligada por padrão**.

**Liga/desliga.** `system_settings.password_reset` (`true`/`false`, padrão `false`). Só pode ser ligada por quem administra o SMTP e apenas se o SMTP está habilitado **e homologado**: "homologado" = um teste de envio bem-sucedido para o **mesmo** host, porta e usuário da configuração atual (alterar qualquer um deles invalida a homologação). Desligada, ou com SMTP indisponível/sem TLS, os endpoints respondem 404 e a tela não mostra o link (`GET /identity/password-reset/status`).

**Fluxo.**

1. `POST /identity/password-reset/request {email}` → **sempre 202** com a mesma mensagem (a conta existir ou não, estar ativa ou não, ter passado do limite ou não). O envio ocorre depois da resposta (background).
2. Token: `secrets.token_urlsafe(32)`; **só o SHA-256 é guardado** (`password_reset_requests`). Validade de **30 minutos**, uso único. Um novo pedido invalida os anteriores ainda abertos.
3. `POST /identity/password-reset/confirm {token, new_password}` → valida hash/validade/uso, aplica a senha (mínimo 8), **zera o bloqueio por tentativas, remove "trocar senha no próximo login" e incrementa `token_version`** (encerra todas as sessões). Link inválido, expirado ou já usado → mesma mensagem genérica.
4. **Abuso:** por e-mail, 3 pedidos/hora; por IP, 10 pedidos/hora (contados na própria tabela, inclusive pedidos de e-mails inexistentes). Acima do limite a resposta continua 202, sem criar token nem enviar. O IP vem de `X-Forwarded-For` (definido pelo Nginx); o limite por IP é uma camada a mais, não a única: o Nginx também limita `/password-reset/request` por IP.
5. **SMTP:** o envio exige TLS (`STARTTLS` ou `SSL_TLS`); `NONE` não é aceito para recuperação de senha. Falha de envio vai para a auditoria (`identity.password_reset_send_failed`), sem retentativa em rajada; o token expira sozinho.
6. **Sigilo:** token e senha nunca vão para log nem para auditoria; o e-mail do pedido é guardado só como hash.

**Auditoria:** `identity.password_reset_requested`, `identity.password_reset_completed`, `identity.password_reset_send_failed`, `identity.password_reset_configured`.

## Alternativas descartadas

- **Passar pelo outbox do hub de notificações:** ganha retentativas, mas guarda o link no banco por mais tempo e exige adaptar o canal. Reavaliar se o SMTP corporativo for instável.
- **Perguntas secretas / SMS:** mais fracas ou dependem de integração que o sistema não tem.

## Consequências

- Nova tabela `password_reset_requests` (migration `s9c0d1e2f3a4`).
- Equalização de tempo é aproximada: o trabalho de e-mail acontece após a resposta; consultas de banco do caminho "conta existe" e "não existe" são equivalentes em número.
- O link usa `app_base_url` do SMTP; se estiver errado, o link chega quebrado (verificar na homologação).
