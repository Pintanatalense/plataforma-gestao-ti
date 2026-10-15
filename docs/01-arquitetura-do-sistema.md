# 01. Arquitetura do Sistema

## 1. Visão Geral da Solução

A **Plataforma de Gestão de TI** é estruturada como um **Monólito Modular Assíncrono**, projetado para prover governança abrangente sobre operações de tecnologia, inventário de ativos, controle de acessos, service desk, almoxarifado de insumos e mensageria corporativa.

O sistema foi arquitetado para suportar tanto **instalações empresariais limpas (Produção)** quanto **ambientes demonstrativos (Demo)** controlados, com separação explícita entre dados operacionais, configurações fundamentais e dados fictícios.

---

## 2. Diagrama da Arquitetura

```mermaid
graph TD
    Client["Navegador Web / Usuário"] -->|HTTP / HTTPS (Porta 80/443)| Proxy["Nginx Reverse Proxy\n(gestao-ti-proxy)"]
    WhatsAppUser["Colaborador via WhatsApp"] -->|Webhook HTTP POST| Proxy

    subgraph "Ambiente de Aplicação (Docker Network)"
        Proxy -->|Static Files| FrontendDist["SPA Angular 17\n(/usr/share/nginx/html)"]
        Proxy -->|Proxy /api/v1/ e /ws| BackendAPI["FastAPI Backend\n(gestao-ti-api :8000)"]

        subgraph "Backend - Módulos Principais"
            Identity["Identidade & RBAC (MOD-02)"]
            ServiceDesk["Service Desk (MOD-04)"]
            AssetsStock["Ativos & Estoque (MOD-03/06)"]
            DemoManager["Gestão de Ambientes (MOD-01)"]
            BackupService["Backup & Recovery (MOD-14)"]
            EmailNotifier["Notificador SMTP (MOD-11)"]
            WhatsAppBot["WhatsApp & Anti-Ban (MOD-15)"]
        end

        BackendAPI --- Identity
        BackendAPI --- ServiceDesk
        BackendAPI --- AssetsStock
        BackendAPI --- DemoManager
        BackendAPI --- BackupService
        BackendAPI --- EmailNotifier
        BackendAPI --- WhatsAppBot

        BackupService -->|pg_dump / psql CLI| Database
        BackupService -->|Armazenamento| BackupVolume["Volume /data/backups"]
        BackendAPI -->|Anexos locais| AttachVolume["Volume /data/attachments"]

        Database[("PostgreSQL 16\n(gestao-ti-db :5432)\nSchema: public")]
        BackendAPI -->|SQLAlchemy 2.0 Async / asyncpg| Database
    end

    subgraph "Serviços Integrados Externos / Opcionais"
        EmailNotifier -->|SMTP / STARTTLS :587 / :465| SmtpServer["Servidor de E-mail (Gmail / O365 / Postfix)"]
        WhatsAppBot -->|REST API :8084| EvolutionAPI["Evolution API v2 Container\n(Perfil: evolution)"]
        EvolutionAPI -->|Conexão Baileys/Socket| WhatsAppNet["Rede WhatsApp / Meta"]
    end
```

---

## 3. Componentes e Tecnologias

| Camada | Tecnologia | Versão / Detalhes | Papel no Sistema |
| :--- | :--- | :--- | :--- |
| **Frontend** | Angular + Angular Material | v17+ Standalone Components | Interface rica em SPA para atendentes, gestores e administradores. |
| **Reverse Proxy** | Nginx | Alpine Linux | Roteamento unificado de tráfego HTTP, terminação de conexões e entrega de assets compilados. |
| **Backend API** | Python / FastAPI | Python 3.12, FastAPI 0.111+ | API assíncrona orientada a serviços com injeção de dependências e regras de domínio. |
| **Banco de Dados** | PostgreSQL | PostgreSQL 16 (Alpine) | Persistência relacional robusta com chaves estrangeiras, integridade ACID e migrações via Alembic. |
| **Driver BD** | asyncpg + SQLAlchemy | SQLAlchemy 2.0 Async ORM | Pool de conexões assíncrono para alto throughput sem bloqueio da event loop. |
| **Backup Engine** | `postgresql-client` nativo | `pg_dump` e `psql` com Gzip | Geração atômica de dumps estruturados e restauração validada com hash SHA-256. |
| **Notificações** | Python standard (`smtplib`, `ssl`, `asyncio.to_thread`) | MIME multipart (HTML + Texto) | Envio transacional de notificações de chamados respeitando a regra DEC-012. |
| **Integração WhatsApp** | Evolution API v2 / Meta Cloud API | Adapter Pattern modular | Bot de autoatendimento, verificação de chamados e notificações com escudo Anti-Ban. |

---

## 4. Fluxo de Comunicação e Segurança

1. **Camada de Borda**: Toda a comunicação externa atinge o container `gestao-ti-proxy` na porta 80 (ou 443 em SSL). Nenhuma porta de banco de dados ou backend fica diretamente exposta à internet em produção.
2. **Autenticação e Sessão**: Utiliza tokens JWT assimétricos/assinados via `pyjwt` com tempo de expiração configurável. Requisições subsequentes transmitem o cabeçalho `Authorization: Bearer <token>`.
3. **Controle de Acesso Baseado em Perfis (RBAC)**: O endpoint avalia as permissões granulares (`require_permission`) associadas aos papéis do usuário (`ADMIN_TOTAL`, `GESTAO_TI`, `TECNICO_N2`, `SOLICITANTE_PADRAO`).
4. **Isolamento de Dados Demonstrativos**: As entidades operacionais possuem o discriminador booleano `is_demo`. O serviço `DemoManagementService` assegura a distinção lógica e física entre artefatos de teste e dados reais da empresa.
