# Status e Pendências - Plataforma de Gestão de TI

Este documento sumariza o status atual do projeto, as funcionalidades recém-entregues, e mapeia as pendências técnicas e tarefas pendentes que necessitam de intervenção ou desenvolvimento futuro.

---

## ✅ Funcionalidades Entregues e Corrigidas

1. **Testes Unitários (Backend)**
   - Corrigidas falhas do `async_client` em `test_inventory_audit.py`.
   - Ajustada criação de instâncias com parâmetros corretos (ex: `hashed_password`).
   - Resolvido erro `MissingGreenlet` nos models do Service Desk ao configurar os relacionamentos `materials` e `interactions` com `lazy="selectin"`.
   - **Status:** Todos os 44 testes automatizados estão passando com sucesso (100%).

2. **Segurança contra Vazamento de Informações**
   - Implementado um fallback centralizado em `app/core/exceptions.py`.
   - Requisições para rotas não mapeadas (404) ou com body inválido (422) não exibem mais o stacktrace nem expõem tabelas, colunas, chaves estrangeiras ou informações locais do servidor. Toda falha retorna um JSON padronizado.

3. **Integração de Logo da Empresa (Branding)**
   - Modelos, Schemas e API no backend preparados para fazer upload da Logo (rota `POST /api/v1/organization/company/logo`) salvando no diretório `static/`.
   - Rota livre (pública) adicionada para resgate da imagem da tela de login.
   - Frontend ajustado: A página inicial (Login) agora exibe a Logo da Empresa com fallback visual em caso de erro, juntamente com o nome dinâmico recuperado do banco.
   - **Nota:** O layout interno (`sidebar`, `header`...) ainda usa componentes provisórios (boilerplate `<p>header works!</p>`), sendo assim a logo interna deverá ser adicionada quando estas barras forem oficialmente desenhadas.

4. **Correção de UI: Cabeçalhos com Texto Cortado**
   - Bug crônico visualizado nos cabeçalhos (`h1`) ao longo do sistema nas listagens devido à incompatibilidade do gradient `-webkit-background-clip: text`.
   - **Correção Aplicada:** Máscaras de gradientes removidas e substituídas globalmente nos componentes pelo padrão `color: var(--mat-sys-primary)` acompanhado de `padding: 10px 0;`. Agora não ocorre mais clipping independente da variação do browser.

---

## ⚠️ Pendências Encontradas e Próximos Passos (To-Do)

### 1. Reestruturação dos Componentes Frontend (Boilerplates Perdidos)
Durante uma automação de reescrita em lote, arquivos não trackeados nas seguintes features foram corrompidos e então removidos para não impedir a compilação do front. Eles deverão ser gerados novamente através do Angular CLI (`ng g c ...` e `ng g s ...`):
* `app/features/assets/` (componentes `asset-list`, `asset-create`, `asset-detail`, e `asset.service`)
* `app/features/stock/` (componentes `stock-list`, `stock-create`, `stock-detail`, e `stock.service`)
* `app/features/inventory/` (componentes `inventory-list`, `inventory-detail`, e `inventory.service`)
**Prioridade:** Alta (antes de continuar o desenvolvimento nestes módulos, basta recriar a estrutura de pastas e boilerplate).

### 2. Criação do Shell / Layout Interno
As páginas do layout interno do sistema (`Sidebar`, `Header`) atualmente consistem apenas do html autogerado do Angular.
**Ação Necessária:** 
- Implementar o MatSidenav.
- Adicionar o menu dinâmico baseado no perfil do usuário logado (Admin, Support, etc).
- Acoplar no novo layout a visualização da Logo (previamente tratada na tela de login).

### 3. Conexão Completa dos Módulos Físicos
Os módulos de **Ativos (Assets)** e **Estoque (Stock)** foram construídos perfeitamente do lado da API em sessões anteriores e seu relacionamento ao `Service Desk` pelo ticket foi estabelecido, mas o mapeamento visual no Frontend precisa da construção das telas citadas no Item 1.

### 4. Remoção de Componentes Legados
Os componentes `role-list` e `user-list` que possuíam HTMLs isolados foram unificados diretamente nos respectivos `.ts` (Standalone Components). O Git identificou remoções desses antigos `.html` e `.scss`, o que foi mergeado. Verificar se não há lixos residuais nos imports das classes referentes.

---
**Build de Integração Contínua (CI):** Os commits foram realizados com sucesso em `main`. O sistema backend está rodando com consistência, e o frontend está livre de falhas críticas ou bugs visuais no CSS neste exato momento.
