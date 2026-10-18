# 02. Instalação do Sistema

Guia para instalar a Plataforma de Gestão de TI em um servidor, uma VM ou um computador de testes. O passo a passo curto também está no [`README.md`](../README.md).

---

## 1. Requisitos

* **Sistema:** Linux (Ubuntu 22.04+, Debian 12+), Windows 10/11 com Docker Desktop (WSL2) ou macOS.
* **Recursos mínimos:** 2 vCPUs, 4 GB de RAM, 20 GB de disco (SSD recomendado para o PostgreSQL).
* **Software:** Docker Engine 24+ com **Docker Compose v2** (`docker compose`, sem hífen) e Git.
* **Rede:** porta TCP 80 livre (ou outra, via `HTTP_PORT`). Para WhatsApp (Meta) e Slack é preciso um endereço **HTTPS público**; Telegram e e-mail só precisam de saída para a internet.

---

## 2. Instalação guiada (recomendada)

```bash
git clone <URL_DO_REPOSITORIO> plataforma-gestao-ti
cd plataforma-gestao-ti
scripts/install.sh               # Linux, macOS, WSL, Git Bash. Opção: --port 8080
```

No Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1      # Opção: -Port 8080
```

O script:

1. confere se o Docker e o Compose v2 estão instalados **e em execução**;
2. cria o `.env` a partir do `.env.example` com `POSTGRES_PASSWORD`, `SECRET_KEY` e `APP_ENCRYPTION_KEY` **aleatórios** (nunca sobrescreve um `.env` que já exista);
3. executa `docker compose up -d --build` (migrations e dados iniciais rodam sozinhos no backend);
4. espera `/api/v1/health` responder e mostra o endereço.

`--env-only` (`-EnvOnly` no PowerShell) só gera o `.env`.

> **Guarde uma cópia da `APP_ENCRYPTION_KEY` fora do servidor** (cofre de senhas). Ela cifra a senha do SMTP e os tokens dos canais gravados no banco; sem ela, uma restauração de backup não consegue lê-los.

---

## 3. Instalação manual

```bash
cp .env.example .env
# Preencha no .env:
#   POSTGRES_PASSWORD  senha forte
#   SECRET_KEY         openssl rand -hex 32   (o sistema recusa valores curtos ou de exemplo)
#   APP_ENCRYPTION_KEY python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d --build
```

Serviços do Compose: `postgres`, `backend` (API), `worker` (notificações, backup diário, alertas automáticos) e `nginx` (único que publica porta; serve o frontend e encaminha `/api`).

---

## 4. Primeiro acesso: base limpa ou modelo de exemplo

Abra `http://SEU_SERVIDOR` (porta `HTTP_PORT`). Sem nenhum usuário cadastrado, o sistema abre o **assistente de instalação**:

| Opção | O que acontece |
|---|---|
| **Base limpa** (uso real) | Pede o nome da empresa (CNPJ opcional) e cria o administrador. Deixa um **catálogo inicial** editável: setor "Tecnologia da Informação", 6 categorias de chamado e 5 de ativo. Nenhum dado fictício. Modo `PRODUCTION`. |
| **Modelo de exemplo** | Cria o administrador e carrega dados fictícios: 8 colaboradores com contas de exemplo (senha `Demo@2026`), 6 chamados em vários estágios, 5 ativos, 5 insumos de estoque e garantias, para conhecer o sistema e ver os alertas. Modo `DEMO`, com selo no cabeçalho. |

O assistente só funciona enquanto não existe usuário; depois disso responde 409. Para trocar de exemplo para uso real, veja o [guia do ambiente demonstrativo](07-gestao-do-ambiente-demonstrativo.md).

---

## 5. Verificação

```bash
docker compose ps                         # todos "healthy" (o worker leva ~40 s)
curl -s http://localhost/api/v1/health    # "status": "healthy"; components.worker = "healthy"
```

Volumes persistentes (não apague com `down -v`): `postgres_data`, `attachments_data`, `backups_data`.

---

## 6. Reinstalar do zero (descarta tudo)

```bash
docker compose down -v      # apaga banco, anexos e backups do Compose
rm .env                     # ou mantenha, se quiser as mesmas senhas
scripts/install.sh
```

Em produção, faça backup antes (veja [05-backup-e-restauracao.md](05-backup-e-restauracao.md)).
