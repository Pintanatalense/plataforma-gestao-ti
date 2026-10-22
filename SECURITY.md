# Política de segurança

## Como relatar uma vulnerabilidade

**Não abra uma issue pública** com detalhes de uma falha de segurança.

Use o relato privado do GitHub: na página do repositório, **Security → Report a vulnerability**
(requer "Private vulnerability reporting" habilitado em *Settings → Code security*). Se não estiver
disponível, avise o responsável do projeto por um canal privado e inclua:

- o que foi encontrado e o impacto;
- passos para reproduzir (versão/commit, endpoint, usuário e permissões usados);
- sugestão de correção, se houver.

**Nunca inclua** senhas, tokens, a `APP_ENCRYPTION_KEY`, dumps de banco nem dados reais de usuários no relato.

## O que o projeto já faz

- Senhas com bcrypt; sessões JWT com revogação (ADR-016: troca de senha, desativação e mudança de perfil encerram as sessões).
- Credenciais de integrações cifradas no banco (Fernet).
- Autorização por permissão em toda rota autenticada; teste automatizado impede rota nova sem autenticação.
- CI com testes em PostgreSQL, `alembic check`, lint, `shellcheck`, build das imagens e auditoria de dependências (`pip-audit`, `npm audit`).

Limites e riscos conhecidos estão em `docs/09-seguranca-e-auditoria.md` e em `docs/plans/plano-diretor.md`.

## Versões suportadas

O projeto ainda não tem releases versionadas: apenas a `main` recebe correções.
