# Plano de Evolução — Central de Operações, Infraestrutura e Conhecimento

> **Status:** aprovado como referência oficial em 2026-10-25. A implementação é autorizada **por fase**, após avaliação; cada PR é aprovado individualmente. Substitui o [plano-diretor.md](plano-diretor.md) (fases 1–4 concluídas em #11–#63).
> Base: código e testes (3 levantamentos + verificações diretas, marcadas ✔). Documentação histórica não foi usada como prova.
> Cuidados mantidos na aprovação: validação segura da PoC no Proxmox (recursos dedicados), integridade da auditoria e preservação das regras atuais de permissões e visibilidade.
> **Antes da Fase 0:** sequência de CI #64 → B (`ci-local`) → C (backend/PG real) → E (Docker + smoke) → F (fluxo dos agentes).

## Context

A plataforma (FastAPI + SQLAlchemy async + Alembic + PG16 · Angular 22 · Nginx · Compose · worker com outbox) cobre chamados, patrimônio, estoque, notificações e auditoria. O objetivo é torná-la a **fonte de verdade operacional** (equipamentos, virtualização, rede, serviços, chamados, monitoramento, conhecimento), consultável por humanos e agentes, local e sem custo obrigatório. A arquitetura será **validada por uma PoC pequena** antes de expandir; as fases seguintes confirmam ou corrigem as decisões com o que a PoC mostrar.

Legenda: **[APROVADO]** decisão sua · **[RECOMENDADO]** proposta minha, a confirmar na fase · **[OBRIGATÓRIO]** requisito de segurança que nenhuma fase pode dispensar · **[FUTURO]** visão mantida, sem data.

---

## 1. Decisões aprovadas

| # | Decisão |
|---|---|
| A1 | Principal único em `user_accounts` com `kind` (`human` / `service`), autenticação e restrições próprias por tipo |
| A2 | Permissões críticas (aprovação, execução, administração) exigem concessão explícita, **inclusive para administradores**, com mecanismo seguro de concessão inicial e recuperação |
| A3 | PoC com Proxmox e Zabbix do laboratório, em **recursos dedicados aos testes**; nada existente é alterado sem autorização específica |
| A4 | IPAM básico integrado, com porta aberta para integração futura com NetBox |
| A5 | Ordem: PoC → SLA concluído → CMDB completa |
| — | Direção arquitetural da Revisão 2 aprovada como referência (CMDB separada do patrimônio, identidades externas, integrações como módulo, execução fora do núcleo) |

---

## 2. Requisitos obrigatórios de segurança [OBRIGATÓRIO]

| # | Requisito | Origem (✔ = confirmado no código) |
|---|---|---|
| S1 | **Escopo aplicado nas consultas**, não só guardado no token: toda listagem/detalhe filtra por setor, ambiente e recurso permitidos ao principal (seção 3.1) | ✔ hoje o escopo vem de um `dict` montado só no router de chamados (`service_desk/router.py:36-70`) a partir do colaborador |
| S2 | **IP real confiável**: Nginx envia `X-Forwarded-For $remote_addr` em todos os blocos (ou `real_ip` com proxies declarados); backend aceita o cabeçalho só de proxies confiáveis; teste de IP forjado | ✔ bloco `/api/` usa `$proxy_add_x_forwarded_for` e o backend pega o 1º IP → IP forjável na auditoria |
| S3 | **Papéis de banco separados**: aplicação deixa de usar o superusuário; Evolution recebe um papel restrito ao schema `evolution_api` | ✔ backend, worker **e Evolution** usam o mesmo `POSTGRES_USER` (superusuário) |
| S4 | **Auditoria à prova de alteração** (seção 3.8): sem UPDATE/DELETE pela aplicação, encadeamento por hash, retenção por categoria, reset de demo não apaga trilha de segurança | ✔ `demo_service` apaga `AuditLog`; não há retenção nem proteção |
| S5 | **Permissões críticas nunca concedidas automaticamente** (nem pelo seed ao "Administrador"); concessão só por quem tem a permissão de conceder críticas, auditada e notificada a todos os administradores | ✔ `seed.py` ressincroniza o "Administrador" com todas as permissões |
| S6 | **Tokens de serviço**: opacos, só hash no banco, validados a cada requisição, revogação imediata, validade obrigatória, nunca `is_admin`, nunca login por senha, nunca JWT | — |
| S7 | **Integrações**: segredo por conexão cifrado (Fernet) e mascarado; `compare_digest`; 404 desligado / 401 sem corpo; lista de IPs no Nginx para entradas; URLs de saída em lista permitida (anti-SSRF); limite de requisições; payload só com campos permitidos | ✔ padrão já existe na Evolution |
| S8 | **Leitura sem efeito colateral**: token de leitura não escreve; integrações de leitura usam credenciais só de leitura (Proxmox `PVEAuditor`); campos sensíveis descartados antes de gravar | — |
| S9 | **Execução fora do núcleo**: nenhuma ação na infraestrutura roda no backend; só catálogo fechado, com aprovação e evidência | — |
| S10 | **Backup completo e chave guardada à parte** (seção 3.7); restauração testada | ✔ backup do app = só banco; chave e `.env` fora; volume da Evolution fora |
| S11 | **Rotas ocultas e Nginx testados de verdade**: contrato de autenticação cobre rotas `include_in_schema=False`; teste sobe o Nginx e prova bloqueios | ✔ hoje só se lê o texto do `.conf` |
| S12 | **Migrations com volta declarada**: expandir → migrar → contrair; transformação de dados exige backup verificado antes; módulos novos atrás de liga/desliga | — |
| S13 | **Conteúdo para agentes é dado, não instrução**: documentos, chamados e alertas entregues marcados como dado; ferramentas de agente só por catálogo | — |

---

## 3. Desenho técnico [RECOMENDADO, validado pela PoC]

### 3.1 Contexto de acesso único (S1)
Um objeto `AccessContext` montado **uma vez por requisição** em `get_token_payload` (`core/dependencies.py:27`), para humanos e serviços: principal, tipo, permissões, `employee_id` (humanos), setores visíveis, ambientes permitidos, recursos permitidos (lista ou "todos do setor").
- Humano: setores = setor do colaborador (técnico) ou todos (`read_all`), como hoje.
- Serviço: setores/ambientes/recursos vêm do token, **nunca** "todos" por omissão.
- Substitui o `dict` ad hoc de `service_desk/router.py:36` e as checagens por `employee_id` em `assets/router.py:153-290`, `organization/router.py:207` e `attachments/access.py`.
- Filtro aplicado no **repositório/serviço** (não no router), para que toda rota nova herde.
- Rotas pessoais ("meus chamados", "meus ativos", preferências, troca de senha, WebSocket) recusam principal de serviço com 403 explícito.
- Teste por rota: serviço com setor X não lê nada do setor Y (lista, detalhe, anexos, histórico, contexto).

### 3.2 Principal de serviço e tokens (A1, S6)
- `user_accounts.kind`; `email`/`hashed_password` aceitam nulo **só** para serviço (CHECK); CHECK impede `is_admin` em serviço; login por senha só para humano. ✔ ~20 FKs para `user_accounts` continuam válidas.
- `service_tokens`: principal, prefixo, hash SHA-256, escopos (⊂ permissões dos perfis), setores, ambientes, recursos, `expires_at` obrigatório, último uso/IP, `revoked_at`. Formato `gti_svc_<prefixo>_<segredo>`, mostrado uma vez.
- Auditoria grava `actor_kind` e o token usado (prefixo).

### 3.3 Chamados automáticos
- `origin` (`web`, `chat`, `monitoramento`, `integracao`, `agente`) + `reported_by_user_id`.
- `requester_id` opcional só para `monitoramento`/`integracao` (CHECK). Agente em nome de pessoa informa colaborador real e precisa de `service_desk.tickets.create_on_behalf`.
- Unidade de origem = unidade do IC afetado ou padrão da conexão; setor de origem/responsável = configurados na integração.
- Autor de interações automáticas = principal de serviço.
- Notificações: audiência `requester` vazia é válida; `sector_attendants` mantida.
- SLA: só interação pública **humana** conta como primeira resposta.
- Telas e schemas aceitam "Aberto por: Zabbix".

### 3.4 Permissões (A2, S5)
- Catálogo único em código: código, módulo, rótulo pt-BR, descrição, risco (`leitura`, `alteração`, `aprovação`, `execução`, `administração`).
- Desmembramento de permissões amplas concede as novas **só** a perfis que já faziam aquilo (teste compara acesso antes/depois).
- Críticas: `is_admin` **não** dispensa. Nova permissão `identity.critical.grant` (ela própria crítica).
- **Concessão inicial:** o assistente de instalação/primeiro administrador recebe as críticas explicitamente, registrado na auditoria.
- **Recuperação:** comando no servidor (`python -m app.cli grant-critical --email ...`), que exige acesso ao host, grava auditoria e notifica todos os administradores. Sem caminho pela interface para conceder a si mesmo.
- Tela de perfis agrupada por módulo, em pt-BR, com risco e "acesso efetivo" calculado pelo backend.

### 3.5 Worker sem bloqueio e sem duplicidade
- `--role=all|delivery|jobs`; padrão um contêiner (`all`), integrações pesadas em contêiner `jobs` separado.
- **Isolamento real:** timeout de `asyncio` não interrompe código bloqueante. Por isso, jobs de integração e qualquer job com chamada externa ou trabalho pesado rodam em **subprocesso por execução**, encerrado à força no tempo máximo. Jobs leves continuam em tarefa assíncrona com `wait_for`. Chamadas síncronas restantes vão para `asyncio.to_thread`.
- **Sem execução duplicada:** `job_runs` com índice único parcial "uma execução `running` por job"; concessão com prazo (`lease_until`) renovada por batimento.
- **Recuperação após queda:** execução com prazo vencido vira `interrompida` e entra na fila de nova tentativa (espera crescente, limite de tentativas).
- **Idempotência:** jobs gravam por upsert na identidade externa; repetir uma execução não muda o resultado.
- **Histórico:** início, fim, duração, status, erro, contadores (criados/atualizados/propostas) por execução.
- Entregas nunca esperam jobs (laços separados). Teste: job que dorme 10 min não atrasa uma notificação.
- Revisar chamadas bloqueantes atuais no laço de entregas (ex.: envio SMTP) e no `backup.daily`.

### 3.6 CMDB: estados, identidade e relações
**Três estados, armazenados separadamente:**
| Estado | Onde | Quem escreve | Uso |
|---|---|---|---|
| Administrativo validado | `config_items.attributes` + `validated_by/at` por campo | pessoa com `cmdb.items.write`, ou aceite de proposta | verdade oficial do cadastro |
| Observado | `ci_observations` (IC, fonte, campo, valor, `observed_at`) | integrações | o que as ferramentas viram |
| Desejado | `ci_baselines` (versão, atributos esperados, aprovado por/em) | `cmdb.baselines.approve` | padrão a cumprir; conformidade |

Comparações distintas: observado × administrativo → **proposta de atualização** (qualidade do cadastro); observado × desejado → **desvio de conformidade** (não altera cadastro). Nunca se misturam.

**Identidade de VM/CT** (`external_identities`; ambíguo ⇒ proposta, nunca vínculo):
| Situação detectada | Ação |
|---|---|
| Mesmo cluster+`vmid`, mesmo UUID SMBIOS e mesma data de criação (`meta ctime`) | mesmo IC; se mudou de nó, encerra `hospedado_em` antigo e abre o novo |
| Mesmo `vmid`, UUID ou data de criação diferentes | **reuso de VMID**: IC antigo vai para "não encontrado"; novo IC; proposta "é o mesmo recurso?" |
| `vmid` novo, UUID igual a um IC existente que **ainda existe** | **clone com UUID duplicado**: novo IC + alerta "identificador duplicado" |
| `vmid` novo, UUID igual a um IC que **sumiu** | provável **restauração**: proposta de associação, sem vínculo automático |
| CT (sem UUID SMBIOS) | cluster+`vmid`+data de criação; divergência ⇒ proposta |
| Mais de um candidato | proposta listando os candidatos |
Quais campos o Proxmox regenera em clone e restauração (UUID SMBIOS, `vmgenid`, `ctime`) será **confirmado na homologação** com a versão do laboratório.

**Relações:** catálogo `ci_relationship_types` (rótulos direto/inverso, tipos permitidos, cardinalidade, acíclica) + `ci_relationships` com `valid_from/valid_to` e origem. Sem auto-relação; único (origem, tipo, destino) ativo; índice parcial único para tipos 1:1 (`hospedado_em`, `membro_de`); ciclo verificado por consulta recursiva nos tipos acíclicos; relação é encerrada, nunca apagada.
**Desaparecido:** só conta em sincronização completa bem-sucedida; 3 ausências seguidas ⇒ "não encontrado" + proposta de desativação. **Desatualizado:** validade por fonte, "visto há X" na tela. **Integração fora do ar:** nenhuma alteração; conexão "degradada"; aviso único aos administradores.

### 3.7 Backup e recuperação (S10)
| Item | Hoje | Proposta |
|---|---|---|
| Banco (inclui schema da Evolution) | ✔ app e script | manter + verificação |
| Anexos e logo | só no script | também no backup do app |
| Volume `evolution_instances` | fora | incluído (ou documentado como recriável por novo pareamento) |
| `.env` (senhas, `SECRET_KEY`, chaves) | fora | **cópia separada e cifrada**, nunca junto do dump |
| `APP_ENCRYPTION_KEY` | fora | guarda offline (cofre/impresso); sem ela os segredos cifrados são irrecuperáveis |
| Cópia externa | não | arquivo cifrado (senha própria) para destino externo configurável |
| Restauração | script manual | roteiro em ambiente limpo: `.env` → banco → volumes → conferir revisão do Alembic → subir → smoke (`/api/v1/health` com banco e worker saudáveis) |
| Teste | não | restauração automática semanal em banco descartável + simulado manual trimestral |
| Rotação de chave | não | procedimento com `MultiFernet` (recifrar e trocar) |

### 3.8 Auditoria (S4)
- Categorias: **segurança** (login, permissões, tokens, integrações, aprovações, execuções, concessões críticas) e **operacional**.
- Retenção: segurança — mínimo 5 anos, configurável só para mais; operacional — padrão 2 anos. Antes de expirar, exportação assinada (hash) para arquivo.
- Proteção: papel de banco da aplicação com só INSERT/SELECT em `audit_logs` (exige S3); gatilho que bloqueia UPDATE/DELETE fora da função de retenção; encadeamento por hash (cada linha guarda o hash da anterior) com verificação periódica.
- Reset de demo: apaga só dados de demonstração, nunca a trilha de segurança.
- Campos: `actor_kind`, IP confiável (S2), token/prefixo, categoria.

### 3.9 Zabbix
- Chave do evento: (conexão, id do **problema**); `{EVENT.ID}` na recuperação continua sendo o do problema; `{EVENT.RECOVERY.ID}`, `{EVENT.VALUE}`, `{EVENT.UPDATE.STATUS}`, `{TRIGGER.ID}`, `{HOST.ID}`.
- Reenvio ⇒ `ON CONFLICT`; recuperação antes do problema ⇒ evento nasce normalizado e não abre chamado; simultâneos ⇒ chamado criado na mesma transação com `SELECT … FOR UPDATE`; severidade só sobe (configurável); oscilação (< N min, chamado aberto) ⇒ interação no existente.
- Correlação nunca esconde: chamado filho sempre criado e visível, com `probable_cause_ticket_id` como "possível causa" desfazível (`parent_ticket_id` é dos chamados vinculados, ADR-026); só agrupa notificação de filhos com severidade ≤ à do principal; High e Disaster notificam sempre.
- Padrões: Warning+ abre chamado; Information ignorado (configurável); Warning→baixa, Average→média, High→alta, Disaster→crítica; host sem IC ⇒ chamado "recurso não identificado" + proposta de vínculo; normalização não fecha o chamado.

### 3.10 Proxmox (somente leitura)
Usuário dedicado + token com separação de privilégios e papel `PVEAuditor`.
| Dado | Endpoint | Privilégio |
|---|---|---|
| Nós, VMs, CTs, storages | `/cluster/resources`, `/cluster/status` | `Sys.Audit`, `VM.Audit`, `Datastore.Audit` |
| Configuração (CPU, memória, discos, placas/VLAN/MAC, tags, UUID SMBIOS, `meta`) | `/nodes/{n}/qemu|lxc/{id}/config` | `VM.Audit` |
| Snapshots | `/…/{id}/snapshot` | `VM.Audit` |
| Backups existentes | `/nodes/{n}/storage/{s}/content?content=backup` | `Datastore.Audit` (confirmar na homologação) |
| Redes do nó | `/nodes/{n}/network` | `Sys.Audit` |
| IP dentro da VM | agente convidado | fora do `PVEAuditor` ⇒ opcional, desligado |
Descartados antes de gravar: `cipassword`, `sshkeys`, `args`, `hookscript`.

### 3.11 IPAM básico (A4)
Tabelas próprias (não ICs): `vlans`, `ip_prefixes` (`cidr`, GiST), `ip_addresses` (`inet`, estado usado/reservado/livre/conflito), `network_interfaces` (IC do equipamento, nome, `macaddr`). Conflito = mesmo IP ativo em duas interfaces ou fora do prefixo. Campos e identificadores compatíveis com o modelo do NetBox para integração futura.

---

## 4. Prova de conceito (pequena e objetiva)

**Pré-requisito:** Fase 0 itens 0.1–0.4 (proxy confiável, papéis de banco, contexto de acesso, catálogo de permissões).
**Escopo:** tipos fixos (servidor físico, nó Proxmox, VM, serviço) · `config_items`, `ci_relationships` (`hospedado_em`, `executa_em`, `depende_de`), `external_identities`, `ci_observations` · principal + token de serviço **só leitura** · `origin` no chamado · sincronização Proxmox de um cluster de teste (job em subprocesso) · webhook Zabbix mínimo (problema/recuperação, dedupe) · `GET /api/v1/cmdb/items/{id}/context` · script de agente só leitura.
**Fora:** telas completas (só uma página de consulta), reconciliação, IPAM, correlação, baselines.
**Ambiente:** VMs/hosts **dedicados** no laboratório; Zabbix com host de teste; nenhum recurso existente alterado.

**Critérios de aceite:**
1. Sincronização cria nó, VMs e relações; repetir não duplica.
2. VM de teste migrada entre nós ⇒ mesmo IC; relação antiga encerrada, nova aberta.
3. VMID reutilizado e clone de teste ⇒ **propostas**, nenhum vínculo automático.
4. Alerta do Zabbix na VM ⇒ um chamado ligado ao IC; reenvio não duplica; recuperação vira interação.
5. Contexto devolve hospedeiro, serviço dependente, chamado e origem/idade de cada dado.
6. **Isolamento por setor:** token com setor A consultando um IC do setor A cujo hospedeiro, serviço ou chamado pertence ao setor B recebe só a indicação "relação restrita" (sem nome, IP, título ou contagem detalhada). Teste dedicado para cada caminho (hospedeiro, dependente, chamado, anexo).
7. Token de leitura: `POST` ⇒ 403; revogado ⇒ 401 na requisição seguinte.
8. Job de sync preso não atrasa notificação; queda do worker no meio ⇒ execução retomada sem duplicar.
9. Tudo desligado ⇒ suíte completa verde e comportamento atual idêntico.

**Saída:** relatório da PoC + ADR-020 (CMDB) e ADR-021 (identidades de serviço) "Aceitos" com as correções aprendidas.
**Esforço:** 3–4 semanas (+ pré-requisitos).

---

## 5. Roadmap

Semanas de trabalho efetivo com folga de homologação. ⚠ = alto risco de subestimação.

| Ordem | Etapa | Esforço | Depende de |
|---|---|---|---|
| — | Sequência de CI: #64 → B → C → E → F | em andamento | — |
| **Fase 0** | 0.1 proxy confiável (S2) · 0.2 papéis de banco (S3) · 0.3 contexto de acesso único (S1) · 0.4 catálogo de permissões + seed seguro + concessão inicial/recuperação (S5/A2) · 0.5 desmembrar permissões amplas · 0.6 tela de perfis pt-BR + acesso efetivo · 0.7 auditoria protegida e retenção (S4) · 0.8 worker com papéis, subprocesso, `job_runs` · 0.9 backup completo e restauração testada (S10) · 0.10 correção de docs (ADR-017/019, ADR-013 §7.2), `ENABLE_API_DOCS=false`, worker monta anexos · 0.11 pendências do WhatsApp e chamado do bot "que não aparece" | 5–7 sem ⚠ | CI |
| **Fase 1** | PoC (seção 4) | 3–4 sem ⚠ | 0.1–0.4, 0.8 |
| **Fase 2** | SLA ligado aos chamados (ciclos, pausa, violações, `sla.check`, indicadores, regra "só humano conta") | 2–3 sem ⚠ | PoC (`origin`) |
| **Fase 3** | Identidades de serviço completas (escopos, tela, rotação) · módulo de integrações · CMDB completa (tipos editáveis, relações, propostas, baselines, desaparecidos, tela do IC) | 6–8 sem ⚠ | SLA, ADRs aceitos |
| **Fase 4** | Zabbix completo (tela, lista de IPs, oscilação, correlação) · Proxmox completo · busca global · linha do tempo | 4–5 sem | Fase 3 |
| **Fase 5** | KB · catálogo de serviços + impacto · mudanças como tipo de chamado · IPAM básico · backup/certificados/domínios · QR Code · API de agentes + MCP de leitura | por item | Fase 4 |
| **Fase 6** | Executor de diagnósticos + runbooks de leitura · escrita por agentes com aprovação | 3+ sem ⚠ | Fase 5 |

Pendências antigas sem fase fixa: assinatura dos instaladores, proteção da `main`, HSTS/CSP, 12 `error: () => {}`, `*ngIf` → `@if`, validação do C5 do WhatsApp com número real.

**Regra de todo PR:** `make ci-local` verde; testes do comportamento novo, de escopo por setor e de não regressão de permissões; migration com estratégia de volta declarada (S12); ADR antes do primeiro código de módulo novo; merge só com sua autorização.

---

## 5.1 Fase 0 detalhada (ordem aprovada em 2026-10-25)

Esforço: S ≤ ½ dia · M 1–2 dias · L 3–5 dias. ⚠ = maior risco de estouro. Pré-requisitos da PoC: PRs 2, 5, 7, 10 e 12.

| # | PR | Escopo | Esforço | Depende de |
|---|---|---|---|---|
| 1 | `docs` | Status de ADR-017/019 e §7.2 do ADR-013 alinhados ao código; este plano versionado | S | — |
| 2 | `fix(security)` IP real | Nginx com `X-Forwarded-For $remote_addr` em todos os blocos; backend confia só no proxy (S2) | S–M | — |
| 3 | `fix(config)` | `ENABLE_API_DOCS` padrão `false`; worker monta anexos e logo | S | — |
| 4 | `test` acesso atual | Testes que congelam quem vê/faz o quê por perfil e setor (sem mudar código) | M | — |
| 5 | `feat(identity)` catálogo | Catálogo único (módulo, rótulo pt-BR, risco) + migration de sincronização; seed não concede críticas; `identity.critical.grant`, concessão inicial e comando de recuperação (S5/A2) | M | 4 |
| 6 | `feat(identity)` desmembrar | `assets.write`, `tickets.manage`, `system.backup.manage` desmembradas; novas só para quem já fazia; `tickets.create/read` e `assets.read_own` checadas | M | 4, 5 |
| 7 | `refactor(auth)` contexto único | `AccessContext` montado na autenticação e aplicado nos serviços/repositórios (S1); mesmo comportamento | L ⚠ | 4 |
| 8 | `feat(frontend)` perfis pt-BR | Permissões agrupadas, descrição, risco e acesso efetivo | M | 5, 6 |
| 9 | `feat(audit)` | Tipo de ator, IP confiável, categoria, retenção, demo não apaga trilha de segurança | M | 2 |
| 10 | ADR-022 + `feat(db)` papéis | Dono (migrations), aplicação (dados) e Evolution (schema próprio); roteiro de atualização; rollback para o superusuário (S3) | L ⚠ | 1 |
| 11 | `feat(audit)` imutável | Sem UPDATE/DELETE para a aplicação, gatilho de bloqueio, encadeamento por hash (S4) | M | 9, 10 |
| 12 | `feat(worker)` | Papéis, `job_runs` com concessão, subprocesso com tempo máximo, nova tentativa | L ⚠ | — |
| 13 | `feat(backup)` | Anexos/logo no backup do app, volume da Evolution, `.env`/chave à parte, restauração testada (S10) | M–L | 10 |
| 14 | `fix(whatsapp)` | Índice em `deliveries`, 500 no inbound, status sem escrita, chamado do bot que "não aparece" | S–M | — |

**Concluída quando:** IP da auditoria não é forjável; nenhuma permissão crítica é concedida automaticamente; acesso de todos os perfis atuais idêntico ao de hoje (comprovado por teste); aplicação sem superusuário do banco; auditoria imutável para a aplicação; job preso não atrasa notificações; restauração completa testada em ambiente limpo.

## 6. Implementação futura [FUTURO] — visão mantida

| Funcionalidade | Posição atual | Pré-requisito |
|---|---|---|
| Topologia física de rede | adiada; começar por árvore/dependências | descoberta, relações |
| Descoberta SNMP/LLDP | adiada; avaliar Netdisco ou descoberta do Zabbix antes | executor, IPAM |
| Versão de configurações (estilo Oxidized) | integrar o Oxidized, trazer diffs para o IC | CMDB |
| Mapa visual completo (biblioteca de grafo) | após árvore/dependências | relações estáveis |
| Saúde por recurso com critérios explícitos | após dados de monitoramento/backup confiáveis | Zabbix, backup |
| Correlação avançada de incidentes | após regras simples rodarem com dados reais | Zabbix |
| Capacidade e tendências | ler do Zabbix/Proxmox | integrações |
| Gestão de acessos (sem senhas) | adiada | CMDB |
| Reconciliação automática ampla | após propostas manuais provarem qualidade | CMDB |
| Descoberta de ativos não cadastrados | derivada das integrações | integrações |
| Indicadores operacionais (disponibilidade, recorrência, qualidade do inventário) | após dados | SLA, integrações |
| Ações administrativas no Proxmox (ligar, migrar…) | só com aprovação e executor | executor, A2 |
| Correção automatizada por runbooks | só após diagnósticos de leitura estáveis | executor |
| Busca semântica/RAG local | após KB | KB |
| Assistente técnico local (sem GPU) | adiado; Hermes consome API/MCP | MCP, busca |
| Integração NetBox | quando o IPAM básico não bastar | IPAM |

## 7. O que eu contesto

- **Mudanças** como módulo separado ⇒ tipo de chamado com aprovação e reversão (reaproveita filas, SLA, notificações).
- **MCP próprio** só se o Hermes precisar; a API com token já atende.
- **Assistente local** sem GPU: lento e pouco confiável em chamada de ferramentas; o valor vem antes da IA (busca, contexto, KB).
- **Indicador de saúde** antes de dados confiáveis vira número enganoso.
- **CMDB extensa sem integração** fica vazia: só expandir depois que Proxmox/Zabbix alimentarem automaticamente.

## Verificação

- Backend: `make ci-local` + testes de escopo por setor (incluindo relações), token revogado, IP forjado, concessão crítica, auditoria imutável.
- Migrations: upgrade → downgrade → upgrade com dados; transformações com backup verificado e restauração testada.
- Worker: teste de job preso e de queda no meio da execução.
- Integrações: transporte falso (padrão `http_client()`) + homologação no laboratório em recursos dedicados, documentada.
- Nginx: teste com contêiner real (404, lista de IPs, cabeçalho de IP).
- Backup: restauração completa em ambiente limpo (semanal automática, trimestral manual).
- CI: consumo medido com `scripts/ci_usage.py`.
