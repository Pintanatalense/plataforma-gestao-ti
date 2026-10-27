# 13 — Inventário de páginas (frontend)

Estado real de cada tela do frontend, com a evidência no código. Substitui o "% de conclusão" informal das revisões anteriores: aqui cada coluna é um fato que se confere abrindo o arquivo indicado.

Gerado em 2026-10-22 a partir de `frontend/src/app/app.routes.ts` e dos componentes (33 rotas). Se o código mudou depois, refaça a leitura: esta tabela não se atualiza sozinha.

## Critérios

| Coluna | O que significa | Como foi verificado |
|---|---|---|
| Acesso | permissão exigida pela rota (`permissionGuard`) ou quem pode abrir | `app.routes.ts` |
| Falha de carga | a tela mostra o erro do servidor (com "Tentar novamente") em vez de parecer vazia | uso de `<app-load-state>` no componente/template, ou tratamento próprio de erro; para formulários, o erro no envio |
| Testes | specs que referenciam o componente | busca do nome da classe em `*.spec.ts` |

"Tratamento próprio" = a tela trata o erro sem o componente padrão (Dashboard, Caixa de entrada, Preferências, Importação GLPI). Presença de um spec **não** garante que todos os fluxos da tela estão cobertos: é o ponto de partida para o roteiro `docs/12-roteiro-de-testes.md`, que continua sendo executado por uma pessoa.

## Tabela

| Rota | Acesso | Componente | Falha de carga | Testes |
|---|---|---|---|---|
| `/setup` | só antes da configuração inicial | [`features/setup/setup.component.ts`](../frontend/src/app/features/setup/setup.component.ts) | ✔ formulário (erro no envio exibido) | `features/setup/setup.component.spec.ts` |
| `/login` | visitante (sem login) | [`features/auth/login/login.component.ts`](../frontend/src/app/features/auth/login/login.component.ts) | ✔ formulário (erro no envio exibido) | `features/auth/login/login-branding.spec.ts`<br>`features/auth/login/login.component.spec.ts`<br>`features/auth/password-reset-screens.spec.ts` |
| `/forgot-password` | visitante (sem login) | [`features/auth/forgot-password/forgot-password.component.ts`](../frontend/src/app/features/auth/forgot-password/forgot-password.component.ts) | ✔ formulário (erro no envio exibido) | `features/auth/password-reset-screens.spec.ts` |
| `/reset-password` | público (link do e-mail) | [`features/auth/reset-password/reset-password.component.ts`](../frontend/src/app/features/auth/reset-password/reset-password.component.ts) | ✔ formulário (erro no envio exibido) | `features/auth/password-reset-screens.spec.ts` |
| `/change-password` | qualquer usuário logado | [`features/auth/change-password/change-password.component.ts`](../frontend/src/app/features/auth/change-password/change-password.component.ts) | ✔ formulário (erro no envio exibido) | `features/auth/change-password/change-password.component.spec.ts`<br>`features/auth/server-messages.spec.ts` |
| `/dashboard` | qualquer usuário logado | [`features/dashboard/dashboard.component.ts`](../frontend/src/app/features/dashboard/dashboard.component.ts) | ✔ tratamento próprio | `features/dashboard/dashboard.component.spec.ts` |
| `/organization` | `organization.units.read` | [`features/organization/unit-list/unit-list.component.ts`](../frontend/src/app/features/organization/unit-list/unit-list.component.ts) | ✔ componente de estados | `features/organization/org-identity-lists.spec.ts`<br>`features/organization/unit-list/unit-list.component.spec.ts` |
| `/organization/company` | `organization.company.read` | [`features/organization/company/company.component.ts`](../frontend/src/app/features/organization/company/company.component.ts) | ✔ componente de estados | `features/organization/company/company.component.spec.ts` |
| `/organization/sectors` | `organization.sectors.read` | [`features/organization/sector-list/sector-list.component.ts`](../frontend/src/app/features/organization/sector-list/sector-list.component.ts) | ✔ componente de estados | `features/organization/org-identity-lists.spec.ts`<br>`features/organization/sector-list/sector-list.component.spec.ts` |
| `/organization/employees` | `organization.employees.read` | [`features/organization/employee-list/employee-list.component.ts`](../frontend/src/app/features/organization/employee-list/employee-list.component.ts) | ✔ componente de estados | `features/organization/org-identity-lists.spec.ts` |
| `/identity/users` | `identity.users.read` | [`features/identity/user-list/user-list.component.ts`](../frontend/src/app/features/identity/user-list/user-list.component.ts) | ✔ componente de estados | `features/identity/user-list/user-list.component.spec.ts`<br>`features/organization/org-identity-lists.spec.ts` |
| `/identity/roles` | `identity.roles.read` | [`features/identity/role-list/role-list.component.ts`](../frontend/src/app/features/identity/role-list/role-list.component.ts) | ✔ componente de estados | `features/identity/role-list/role-list.component.spec.ts`<br>`features/organization/org-identity-lists.spec.ts` |
| `/audit` | `audit.read` | [`features/audit/audit.component.ts`](../frontend/src/app/features/audit/audit.component.ts) | ✔ componente de estados | `features/audit/audit.component.spec.ts` |
| `/admin` | `identity.roles.read` | [`features/admin/admin.component.ts`](../frontend/src/app/features/admin/admin.component.ts) | ✔ componente de estados | `features/admin/admin-reset-all.spec.ts`<br>`features/admin/admin-states.spec.ts`<br>`features/admin/admin.component.spec.ts` |
| `/notifications` | qualquer usuário logado | [`features/notifications/inbox/inbox.component.ts`](../frontend/src/app/features/notifications/inbox/inbox.component.ts) | ✔ tratamento próprio | `features/notifications/inbox/inbox.component.spec.ts` |
| `/notifications/preferences` | qualquer usuário logado | [`features/notifications/preferences/preferences.component.ts`](../frontend/src/app/features/notifications/preferences/preferences.component.ts) | ✔ tratamento próprio | `features/notifications/preferences/preferences.component.spec.ts` |
| `/channels` | `notifications.manage` **ou** `system.backup.manage` (a aba E-mail aceita as duas; WhatsApp, Telegram e Slack só a primeira) | [`features/channels/channels-page.component.ts`](../frontend/src/app/features/channels/channels-page.component.ts) | abas por canal (ADR-019); E-mail extraído do Painel Administrativo | `features/channels/channels-page.component.spec.ts`, `features/channels/email-config.component.spec.ts` |
| `/notifications/admin` | `notifications.manage` | [`features/notifications/admin/notifications-admin.component.ts`](../frontend/src/app/features/notifications/admin/notifications-admin.component.ts) | contêiner de abas (cada painel tem teste em admin-panels.spec.ts) | `features/notifications/admin/admin-panels.spec.ts` (só os painéis Entregas, Regras e Canais) |
| `/service-desk` | qualquer usuário logado | [`features/service-desk/ticket-list/ticket-list.component.ts`](../frontend/src/app/features/service-desk/ticket-list/ticket-list.component.ts) | ✔ componente de estados | `features/list-screens.spec.ts`<br>`features/service-desk/ticket-list/ticket-list.component.spec.ts` |
| `/service-desk/categories` | `service_desk.categories.manage` | [`features/service-desk/category-list/category-list.component.ts`](../frontend/src/app/features/service-desk/category-list/category-list.component.ts) | ✔ componente de estados | `features/category-lists-states.spec.ts` |
| `/service-desk/reports` | `service_desk.reports.read` | [`features/service-desk/ticket-report/ticket-report.component.ts`](../frontend/src/app/features/service-desk/ticket-report/ticket-report.component.ts) | ✔ componente de estados; período e indicadores de SLA (ADR-017) | `features/service-desk/ticket-report/ticket-report.component.spec.ts` |
| `/service-desk/sla` | `service_desk.sla.manage` | [`features/service-desk/sla-admin/sla-admin.component.ts`](../frontend/src/app/features/service-desk/sla-admin/sla-admin.component.ts) | ✔ componente de estados; abas Políticas e Calendários (ADR-017) | `features/service-desk/sla-admin/sla-admin.component.spec.ts`<br>`features/service-desk/category-list/category-list-sla.spec.ts` |
| `/service-desk/new` | qualquer usuário logado | [`features/service-desk/ticket-create/ticket-create.component.ts`](../frontend/src/app/features/service-desk/ticket-create/ticket-create.component.ts) | ✔ formulário (erro no envio exibido) | `features/service-desk/ticket-create/ticket-create-attachments.spec.ts`<br>`features/service-desk/ticket-create/ticket-create.component.spec.ts` |
| `/service-desk/:id` | qualquer usuário logado | [`features/service-desk/ticket-detail/ticket-detail.component.ts`](../frontend/src/app/features/service-desk/ticket-detail/ticket-detail.component.ts) | ✔ componente de estados | `features/detail-screens.spec.ts`<br>`features/service-desk/ticket-detail/ticket-detail.component.spec.ts` |
| `/assets` | `assets.read` | [`features/assets/asset-list/asset-list.component.ts`](../frontend/src/app/features/assets/asset-list/asset-list.component.ts) | ✔ componente de estados | `features/assets/asset-list/asset-list.component.spec.ts`<br>`features/list-screens.spec.ts` |
| `/assets/categories` | `assets.read` | [`features/assets/category-list/category-list.component.ts`](../frontend/src/app/features/assets/category-list/category-list.component.ts) | ✔ componente de estados | `features/assets/category-list/category-list.component.spec.ts`<br>`features/category-lists-states.spec.ts` |
| `/assets/new` | `assets.write` | [`features/assets/asset-create/asset-create.component.ts`](../frontend/src/app/features/assets/asset-create/asset-create.component.ts) | ✔ componente de estados | `features/asset-stock-support-states.spec.ts` |
| `/assets/import-glpi` | `assets.import` | [`features/assets/asset-glpi-import/asset-glpi-import.component.ts`](../frontend/src/app/features/assets/asset-glpi-import/asset-glpi-import.component.ts) | ✔ tratamento próprio | `features/assets/asset-glpi-import/asset-glpi-import.component.spec.ts` |
| `/assets/:id` | `assets.read` | [`features/assets/asset-detail/asset-detail.component.ts`](../frontend/src/app/features/assets/asset-detail/asset-detail.component.ts) | ✔ componente de estados | `features/assets/asset-detail/asset-detail.component.spec.ts` |
| `/stock` | `stock.read` | [`features/stock/stock-list/stock-list.component.ts`](../frontend/src/app/features/stock/stock-list/stock-list.component.ts) | ✔ componente de estados | `features/list-screens.spec.ts` |
| `/stock/categories` | `stock.read` | [`features/stock/category-list/category-list.component.ts`](../frontend/src/app/features/stock/category-list/category-list.component.ts) | ✔ componente de estados | `features/category-lists-states.spec.ts` |
| `/stock/new` | `stock.write` | [`features/stock/stock-create/stock-create.component.ts`](../frontend/src/app/features/stock/stock-create/stock-create.component.ts) | ✔ componente de estados | `features/asset-stock-support-states.spec.ts`<br>`features/auth/server-messages.spec.ts` |
| `/stock/:id` | `stock.read` | [`features/stock/stock-detail/stock-detail.component.ts`](../frontend/src/app/features/stock/stock-detail/stock-detail.component.ts) | ✔ componente de estados | `features/asset-stock-support-states.spec.ts`<br>`features/detail-screens.spec.ts`<br>`features/reload-failure.spec.ts` |
| `/inventory` | `inventory.read` | [`features/inventory/inventory-list/inventory-list.component.ts`](../frontend/src/app/features/inventory/inventory-list/inventory-list.component.ts) | ✔ componente de estados | `features/list-screens.spec.ts` |
| `/inventory/:id` | `inventory.read` | [`features/inventory/inventory-detail/inventory-detail.component.ts`](../frontend/src/app/features/inventory/inventory-detail/inventory-detail.component.ts) | ✔ componente de estados | `features/detail-screens.spec.ts` |

## Resumo

- 33 rotas; as 22 que exigem permissão específica estão na coluna Acesso, as demais exigem apenas login (ou são públicas, como o fluxo de senha).
- Toda rota tem tratamento visível de falha na carga principal; as falhas de chamadas auxiliares estão listadas abaixo.
- Toda rota tem ao menos um spec que a referencie, exceto `/notifications/admin` (contêiner de abas; ver abaixo).

## O que este inventário não prova

- Não foi aberto navegador para cada tela: a evidência é de código e de testes automatizados (jsdom), não de uso real. A validação em uso real é o `docs/12-roteiro-de-testes.md`.
- Acessibilidade: o ESLint registra avisos (clique sem teclado, rótulo sem controle) ainda não corrigidos; ver `frontend/eslint.config.js`.
- Dívida de estilo: centenas de `*ngIf/*ngFor` aguardam migração para `@if/@for`; dezenas de usos de `any`.
- Pendências conhecidas (falha de chamada auxiliar que não aparece para o usuário): `features/assets/asset-detail/asset-detail.component.ts:257,265` (unidades e colaboradores), `features/service-desk/category-list/category-list.component.ts:999`, `features/service-desk/ticket-create/ticket-create.component.ts:94,104`, `features/service-desk/ticket-detail/ticket-detail.component.ts:161,206,305,423` (categorias, anexos, itens de estoque, colaboradores), `features/assets/asset-glpi-import/asset-glpi-import.component.ts:93,100` (categorias e unidades só vão para o console) e a contagem de não lidas da caixa de entrada (`features/notifications/inbox/inbox.component.ts:200`, só o contador do menu). Duas são intencionais e comentadas no código: `features/audit/audit.component.ts:137` e `features/auth/login/login.component.ts:70`.
- `/assets/import-glpi` tem "tratamento próprio" para a análise e a importação (erros mostrados), mas não para as listas de apoio acima.
- `/notifications/admin` é só um contêiner de abas: nenhum spec referencia o componente em si; os painéis Entregas, Regras e Canais têm teste em `admin-panels.spec.ts`, e os painéis Telegram, WhatsApp e Slack não têm spec.
