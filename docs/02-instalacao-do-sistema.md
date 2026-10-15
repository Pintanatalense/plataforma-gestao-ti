# 02. Instalação e Implantação do Sistema

Este guia orienta o administrador de sistemas e engenheiro DevOps na implantação repetível, previsível e segura da **Plataforma de Gestão de TI** em servidores físicos, máquinas virtuais ou instâncias em nuvem.

---

## 1. Pré-Requisitos de Infraestrutura

Antes de iniciar a instalação, certifique-se de que o host atende aos seguintes requisitos:

* **Sistema Operacional:** Linux (Ubuntu 22.04 LTS+, Debian 12+, RHEL 9+) ou Windows Server com WSL2/Docker Desktop.
* **Recursos Mínimos:**
  * 2 vCPUs
  * 4 GB de memória RAM (6 GB se utilizar a Evolution API em conjunto)
  * 20 GB de espaço em disco livre (SSD recomendado para o PostgreSQL)
* **Softwares Obrigatórios:**
  * Docker Engine (v24.0 ou superior)
  * Docker Compose (v2.20 ou superior)
  * Git
  * Porta TCP **80** (HTTP) e/ou **443** (HTTPS) liberada no firewall de entrada.

---

## 2. Preparação do Ambiente e Variáveis

1. Clone o repositório oficial no diretório de serviços do servidor:
   ```bash
   git clone <URL_DO_REPOSITORIO> /opt/plataforma-gestao-ti
   cd /opt/plataforma-gestao-ti
   ```

2. Crie o arquivo de ambiente `.env` a partir do modelo base:
   ```bash
   cp .env.example .env
   ```

3. Configure as variáveis críticas de produção no `.env`:
   ```env
   # Banco de Dados
   POSTGRES_DB=gestao_ti
   POSTGRES_USER=gestao_admin
   POSTGRES_PASSWORD=GereUmaSenhaForteExemplo!2026#Db
   DB_PORT=5432

   # Segurança e Tokens
   SECRET_KEY=ChaveSecretaDePeloMenos32CaracteresAleatoriosSegurosParaProducao!
   DEBUG=false
   API_PORT=8000
   HTTP_PORT=80

   # Armazenamento de Anexos e Backups
   ATTACHMENT_STORAGE_PATH=/data/attachments

   # Opcional: Evolution API v2
   EVOLUTION_PORT=8084
   EVOLUTION_API_KEY=ChaveSecretaExclusivaDaEvolutionAPI_2026!
   EVOLUTION_SERVER_URL=http://localhost:8084
   ```

---

## 3. Inicialização dos Serviços via Docker Compose

### Cenário Padrão (Produção Empresarial)
Inicia o banco de dados PostgreSQL, a API FastAPI e o proxy reverso Nginx com o frontend Angular:

```bash
docker compose up -d --build
```

### Cenário com Integração WhatsApp (Evolution API)
Caso a empresa deseje utilizar o gateway de WhatsApp localmente no mesmo servidor:

```bash
docker compose --profile evolution up -d --build
```

---

## 4. Aplicação de Migrações do Banco de Dados

O banco de dados é inicializado automaticamente na primeira subida. Para aplicar todas as migrações estruturais do Alembic:

```bash
docker compose exec backend alembic upgrade head
```

---

## 5. Primeiro Acesso: Base Limpa vs. Demonstração

Ao acessar o sistema pela primeira vez no navegador (`http://SEU_IP_OU_DOMINIO/`):

1. O sistema detectará automaticamente que não existem contas cadastradas e redirecionará para a rota `/setup`.
2. O assistente de configuração permite escolher o modo de implantação:
   * **Opção A: Implantação Empresarial Limpa (CLEAN)**
     * Cria a conta do primeiro superadministrador com credencial própria.
     * Registra a Razão Social e o CNPJ da empresa contratante.
     * Inicia a base em modo `PRODUCTION` com 0 chamados fictícios, 0 ativos simulados e 0 colaboradores falsos.
   * **Opção B: Ambiente Demonstrativo (DEMO)**
     * Cria o administrador e carrega o conjunto padrão de dados modelo para treinamento e demonstrações comerciais.

---

## 6. Verificação e Testes de Validação

Para confirmar que todos os serviços estão em execução e operando com integridade:

1. **Checagem de Saúde da API:**
   ```bash
   curl -i http://localhost/api/v1/health
   ```
   *Resposta esperada:* `HTTP/1.1 200 OK` com `{"status": "healthy", "components": {"database": "healthy"}}`.

2. **Verificação dos Volumes Persistentes:**
   ```bash
   docker volume ls | grep gestao-ti
   ```
   Devem estar listados os volumes:
   * `postgres_data`
   * `attachments_data`
   * `backups_data`
