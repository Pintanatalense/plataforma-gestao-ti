# 11. Guia da Base de Testes e Homologação (QA & Staging)

Este guia documenta a arquitetura, a infraestrutura e os procedimentos operacionais para execução de testes automatizados e gestão de bases de homologação/QA na **Plataforma de Gestão de TI**.

---

## 1. Princípio de Isolamento de Ambientes

O sistema adota uma separação tripartite estrita para garantir que dados de teste, dados de demonstração comercial e dados reais de produção nunca entrem em conflito:

| Ambiente | Host / Porta | Banco de Dados | Finalidade |
| :--- | :--- | :--- | :--- |
| **Desenvolvimento Local** | `localhost:5432` | `gestao_ti` | Trabalho diário de desenvolvimento de novos recursos. |
| **Demonstração (Demo)** | `localhost:5432` | `gestao_ti` (`is_demo=True`) | Apresentações comerciais com possibilidade de limpeza segura pela UI. |
| **Testes & QA (Descartável)** | `localhost:55432` | `gti_test` | Homologação de releases, testes E2E e execução de testes no PostgreSQL real. |

> [!IMPORTANT]
> A guarda de segurança [backend/tests/_guard.py](file:///c:/Projetos/plataforma-gestao-ti/backend/tests/_guard.py) impede sumariamente que qualquer rotina de teste conecte a bancos de dados cujo nome não termine com o sufixo `_test` ou cujo host não seja local (`localhost`, `127.0.0.1`).

---

## 2. Infraestrutura Docker de Testes (`docker-compose.test.yml`)

O repositório dispõe de uma infraestrutura leve e otimizada exclusivamente para testes automatizados e homologação em [docker-compose.test.yml](file:///c:/Projetos/plataforma-gestao-ti/docker-compose.test.yml).

### 2.1. Otimizações de Desempenho
Para acelerar a criação de tabelas, inserção de fixtures e execução de testes de integração, o container de banco de testes opera com sincronização síncrona desativada:
* `fsync=off`
* `synchronous_commit=off`
* `full_page_writes=off`

### 2.2. Comandos Operacionais (Makefile)

```bash
# Iniciar o PostgreSQL de testes em segundo plano (porta 55432)
make test-db-up

# Parar e descartar completamente os volumes e dados de teste
make test-db-down

# Reiniciar e recriar o banco de testes do zero (estado limpo)
make test-db-reset
```

---

## 3. Estratégia de Execução de Testes Automatizados

O ecossistema de testes do backend oferece duas modalidades complementares:

### 3.1. Testes Rápidos In-Memory (SQLite Assíncrono)
Utilizado para ciclos rápidos de TDD (Test-Driven Development) e no pipeline de CI padrão:
```bash
make test
# ou: cd backend && python -m pytest -v --tb=short
```
* **Velocidade:** Executa centenas de testes unitários em poucos segundos.
* **Isolamento:** Tabelas criadas e destruídas dinamicamente em memória a cada suite.

### 3.2. Testes de Integração com PostgreSQL Real (`USE_PG_TEST`)
Utilizado para validar migrações do Alembic, integridade de tipos nativos (ex.: `JSONB`, `UUID`), triggers e relacionamentos complexos:
```bash
# 1. Garanta que o container de teste está rodando
make test-db-up

# 2. Execute a suíte apontando para o PostgreSQL na porta 55432
make test-pg
```

---

## 4. Massa de Dados de Homologação (`seed_test.py`)

Para testes de usabilidade, homologação manual pelo cliente ou testes ponta a ponta (E2E), execute a carga especializada:

```bash
# Carga de teste (idempotente)
make seed-test
# ou direto no backend:
python -m app.seed_test

# Carga com reset prévio (limpa dados anteriores e reconstrói)
make seed-test-reset
# ou direto no backend:
python -m app.seed_test --reset
```

### 4.1. Matriz de Credenciais de Homologação

Todas as contas de teste são criadas com a senha padrão unificada: **`Teste@2026`** (com `must_change_password=False` para facilitar o fluxo automatizado):

| Perfil / Papel | E-mail de Acesso | Colaborador Vinculado | Setor | Permissões Principais |
| :--- | :--- | :--- | :--- | :--- |
| **Superadministrador** | `admin@teste.local` | Administrador de Testes | TI | Acesso global irrestrito, backups e configurações. |
| **Técnico Nível 1** | `tecnico.n1@teste.local` | Carlos Suporte N1 | Suporte N1 | Atendimento de chamados, notas internas, consulta de estoque. |
| **Especialista Nível 2** | `tecnico.n2@teste.local` | Juliana Especialista N2 | TI | Gestão de ativos, estoque e atendimento avançado. |
| **Almoxarife / Estoque** | `almoxarife@teste.local` | Roberto Almoxarife | Almoxarifado | Entrada/saída de insumos, saldo mínimo e patrimônio. |
| **Gestão / Gerente** | `gestor@teste.local` | Mariana Gestora | Operações | Visualização de todos os chamados, relatórios de SLA e auditoria. |
| **Solicitante Comercial** | `solicitante@teste.local` | Lucas Solicitante | Comercial | Abertura de chamados, visualização de próprios equipamentos alocados. |
| **Solicitante RH** | `solicitante.rh@teste.local` | Fernanda Recursos Humanos | RH | Abertura de chamados de suporte e solicitação de sistemas. |

---

## 5. Cenários de Borda Inclusos na Base de Teste

A base de homologação inclui intencionalmente dados representativos de cenários de estresse do dia a dia da TI:

1. **Chamado com Ativo Vinculado:** Chamado *"Notebook reiniciando sozinho em tela azul"* com o equipamento `NOTE-TEST-001` vinculado e histórico de interações públicas e privadas.
2. **Chamado com SLA Estourado:** Chamado crítico aberto há 5 dias pendente de resolução, permitindo validar sinalizadores visuais de atraso e relatórios gerenciais.
3. **Chamado Resolvido com Baixa de Material:** Chamado com item de estoque (`Mouse USB Óptico`) baixado diretamente no atendimento.
4. **Ativos em Múltiplos Ciclos de Vida:**
   * `NOTE-TEST-001`: **Em Uso** (alocado com termo assinado para Lucas Solicitante).
   * `NOTE-TEST-002`: **Disponível** (no estoque técnico).
   * `NOTE-TEST-003`: **Em Manutenção** (assistência técnica).
   * `NOTE-TEST-004`: **Baixado / Decommissioned** (obsoleto).
5. **Insumos de Estoque com Alertas de Reposição:**
   * `Mouse USB` e `Teclado ABNT2`: **Estoque Normal**.
   * `Cabo HDMI 2m`: **Estoque Baixo** (2 unidades em estoque para mínimo de 10).
   * `Toner HP Neverstop`: **Estoque Crítico / Esgotado** (0 unidades para mínimo de 3).

---

## 6. Testes Ponta a Ponta (E2E) com `TARGET_URL`

Os scripts na pasta `tests/` suportam direcionamento dinâmico via variável de ambiente:

```bash
# Executando contra a base local padrão
python tests/test_flow.py

# Executando contra um ambiente de homologação remoto ou containerizado
TARGET_URL=http://staging.empresa.local:8000 python tests/test_flow.py
```
