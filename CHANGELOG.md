# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/). Cada item aponta o PR em `Pintanatalense/plataforma-gestao-ti`.

## [0.1.1] — 2026-10-23

### Funcionalidades

- **Modelo editável do Termo de Responsabilidade**: o texto do termo pode ser adaptado ao padrão da empresa (botão *Modelo do termo* em Patrimônio e Ativos, exige `organization.company.update`), com prévia e volta ao modelo padrão; os dados do colaborador e do ativo continuam preenchidos automaticamente. Sem modelo próprio, o termo é o mesmo de antes. O modelo é texto simples (sem HTML) e cada alteração fica na auditoria.

### Correções

- Gerar o termo de responsabilidade (lista, detalhe e visão rápida do ativo) falhava sem avisar quando a API respondia erro ou o navegador bloqueava a nova aba; agora mostra a mensagem.

### Processo

- O CI gasta bem menos minutos do GitHub Actions: não roda na `main` após o merge, roda só as áreas alteradas por PR, e a suíte completa (inclusive SQLite) roda toda segunda-feira. Dependabot passou a ser mensal e sem rebase automático.

## [0.1.0] — 2026-10-23 (versão para o piloto)

Primeira versão marcada. Reúne a estabilização, a qualidade funcional e as capacidades novas feitas a partir do plano diretor (`docs/plans/plano-diretor.md`).

### Segurança

- Sessões passam a ser revogadas ao trocar ou redefinir a senha e ao desativar a conta (versão de sessão no token, ADR-016); `python-jose` trocado por `PyJWT`.
- Anti-escalada de privilégio: só administrador concede `is_admin`; ninguém concede permissão que não tem; o último administrador é protegido.
- A carga de QA (`/system/demo/seed-test`, cria administrador com senha conhecida) vem **desligada** (`ENABLE_QA_SEED=false`). A documentação interativa da API (`/api/v1/docs`) continua **ligada por padrão**; para um servidor exposto, defina `ENABLE_API_DOCS=false` no `.env`.
- Teste de SMTP não reaproveita a senha salva para outro servidor; alterar o SMTP gera auditoria.
- Limite de tentativas de login no Nginx; o IP do cliente deixou de poder ser forjado por `X-Forwarded-For`.
- Recuperação de senha por e-mail (ADR-018), **desligada por padrão**: só administrador liga, exige SMTP homologado com TLS, link de uso único com validade de 30 minutos, limites por e-mail e por IP.

### Funcionalidades

- Tela **Empresa** (nome, CNPJ e logo) com a logo no menu e no login.
- Tela **Auditoria** com filtros e paginação; a trilha passou a registrar login, falha de login, usuários, perfis, senhas e empresa.
- **Zerar toda a base** pelo painel (só administrador, com backup novo e frase de confirmação), mantendo usuários, perfis, categorias e configurações; a tela de limpeza de demonstração estava lendo campos inexistentes e foi corrigida.
- Importação de inventário GLPI endurecida (série duplicada, JSON inválido, nomes repetidos); categorias de estoque; série única de ativo.
- Base do SLA (ADR-017): tabelas, migration e cálculo de horas úteis. **Sem efeito nos chamados** até a integração (a política "Padrão" nasce inativa).

### Confiabilidade

- Falha de carga deixou de parecer "lista vazia" em todas as telas (componente padrão de estados com "Tentar novamente"); mensagens reais do servidor em vez do texto genérico; chamado deixava de salvar o anexo e dizia "sucesso".
- Banco: migrations alinhadas aos modelos (`alembic check` limpo); `get_company` determinístico.
- Backup/restauração: scripts de verificação e de restauração testados; volumes de anexos e logo incluídos.
- Logs com `X-Request-ID` (devolvido na resposta e presente em cada linha de log) e nível configurável por `LOG_LEVEL`.

### Qualidade e processo

- CI com 6 verificações (testes em SQLite e em PostgreSQL, build das imagens, shellcheck, auditoria de dependências, testes do frontend); ESLint bloqueando erros; `strict` e `strictTemplates` ligados.
- Instaladores para Windows e Linux verificam requisitos e instalam o que faltar (`scripts/install.ps1`, `scripts/install.sh`).
- Documentação reescrita contra o código (`docs/`), inventário de páginas com evidência (`docs/13`), roteiro de testes (`docs/12`).

### Limitações conhecidas

- E-mail real da recuperação de senha não foi exercitado com o SMTP da empresa (etapa 6b do `docs/12`).
- SLA ainda não está integrado aos chamados (P4-S2 em diante).
- 12 chamadas auxiliares ainda falham em silêncio (lista em `docs/13`); acessibilidade e migração `*ngIf` → `@if` pendentes (avisos do ESLint).
- Instalação real do Docker Desktop pelo `winget` e em Windows limpo não foi testada.
- Sem assinatura digital dos instaladores (exige certificado ou chave do titular).
