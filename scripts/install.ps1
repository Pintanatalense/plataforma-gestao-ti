<#
.SYNOPSIS
  Instalação guiada da Plataforma de Gestão de TI no Windows (PowerShell + Docker Desktop).

.DESCRIPTION
  Gera o .env (se não existir) com senhas aleatórias, sobe o sistema e espera ficar pronto.
  Seguro para rodar de novo: nunca sobrescreve um .env existente.

.PARAMETER EnvOnly
  Só gera o .env, sem subir nada.

.PARAMETER Port
  Porta HTTP publicada (padrão 80).

.PARAMETER Https
  Ativa HTTPS com certificado autoassinado (gerado em .\certs).

.PARAMETER Hosts
  Nomes ou IPs extras do certificado, separados por vírgula (ex.: "ti.local,192.168.0.10").

.PARAMETER HttpsPort
  Porta HTTPS publicada (padrão 443).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Port 8080
#>
param(
  [switch]$EnvOnly,
  [int]$Port = 0,
  [switch]$Https,
  [string]$Hosts = '',
  [int]$HttpsPort = 0
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Say($msg)  { Write-Host "==> $msg" }
function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

function New-RandomBytes([int]$count) {
  $bytes = New-Object byte[] $count
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  return ,$bytes
}
function New-Hex([int]$count)      { -join ((New-RandomBytes $count) | ForEach-Object { $_.ToString('x2') }) }
# Chave Fernet = 32 bytes aleatórios em base64 "url-safe" (44 caracteres com padding).
function New-FernetKey()           { [Convert]::ToBase64String((New-RandomBytes 32)).Replace('+', '-').Replace('/', '_') }

function Get-EnvValue([string]$key) {
  $line = Get-Content .env -Encoding UTF8 | Where-Object { $_ -match "^$key=" } | Select-Object -First 1
  if ($line) { return $line.Substring($key.Length + 1) } else { return '' }
}

function Set-EnvValue([string]$key, [string]$value, [bool]$onlyIfEmpty) {
  $lines = Get-Content .env -Encoding UTF8
  $found = $false
  $out = foreach ($line in $lines) {
    if ($line -match "^$key=(.*)$") {
      $found = $true
      if ($onlyIfEmpty -and $Matches[1] -ne '') { $line } else { "$key=$value" }
    } else { $line }
  }
  if (-not $found) { $out = @($out) + "$key=$value" }
  # UTF-8 sem BOM: o Compose lê o .env e um BOM estragaria a primeira variável.
  [System.IO.File]::WriteAllLines((Join-Path (Get-Location) '.env'), [string[]]@($out), (New-Object System.Text.UTF8Encoding($false)))
}

function New-LocalCert([string]$hostList) {
  $san = 'DNS:localhost,IP:127.0.0.1,IP:::1'
  $first = 'localhost'
  foreach ($h in ($hostList -split ',')) {
    $h = $h.Trim()
    if ($h -eq '') { continue }
    if ($h -match '^[0-9.]+$' -or $h.Contains(':')) { $san += ",IP:$h" } else { $san += ",DNS:$h" }
    $first = $h
  }
  New-Item -ItemType Directory -Force certs | Out-Null
  $certDir = (Resolve-Path certs).Path
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'  # o docker escreve o progresso do download em stderr; no PS 5.1 isso viraria erro fatal
  docker run --rm -v "${certDir}:/certs" alpine/openssl req -x509 -newkey rsa:2048 -nodes -days 730 `
    -keyout /certs/server.key -out /certs/server.crt -subj "/CN=$first" `
    -addext "subjectAltName=$san" -addext 'basicConstraints=critical,CA:TRUE' `
    -addext 'keyUsage=digitalSignature,keyEncipherment,keyCertSign' -addext 'extendedKeyUsage=serverAuth' *> $null
  $ErrorActionPreference = $previous
  if ($LASTEXITCODE -ne 0) { Fail 'Não consegui gerar o certificado (o Docker precisa conseguir baixar a imagem alpine/openssl).' }
  Say "Certificado autoassinado criado em certs\ (válido por 2 anos; vale para: $san)."
}

# --- 1. Pré-requisitos ----------------------------------------------------------------------------
if (-not $EnvOnly) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'Docker não encontrado. Instale o Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/' }
  docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 não encontrado ('docker compose version' falhou)." }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) { Fail 'O Docker está instalado, mas não está em execução. Abra o Docker Desktop e aguarde ele iniciar.' }
}

# --- 2. Arquivo .env ------------------------------------------------------------------------------
$generated = $false
if (Test-Path .env) {
  Say 'Arquivo .env já existe: mantido como está.'
} else {
  if (-not (Test-Path .env.example)) { Fail '.env.example não encontrado; rode o script na raiz do repositório.' }
  Say 'Gerando .env com senhas aleatórias...'
  Copy-Item .env.example .env
  Set-EnvValue 'POSTGRES_PASSWORD' (New-Hex 16) $true
  Set-EnvValue 'SECRET_KEY' (New-Hex 32) $true
  Set-EnvValue 'APP_ENCRYPTION_KEY' (New-FernetKey) $true
  $generated = $true
}

if ($Port -gt 0) { Set-EnvValue 'HTTP_PORT' "$Port" $false }

if ($Https) {
  if ($EnvOnly) { Fail '-Https precisa do Docker para gerar o certificado; não combine com -EnvOnly.' }
  if ((Test-Path certs\server.crt) -and (Test-Path certs\server.key)) { Say 'Certificado em certs\ já existe: mantido (apague a pasta para gerar outro).' }
  else { New-LocalCert $Hosts }
  if ($HttpsPort -gt 0) { Set-EnvValue 'HTTPS_PORT' "$HttpsPort" $false }
  elseif ((Get-EnvValue 'HTTPS_PORT') -eq '') { Set-EnvValue 'HTTPS_PORT' '443' $false }
  Set-EnvValue 'COMPOSE_PATH_SEPARATOR' ':' $false
  Set-EnvValue 'COMPOSE_FILE' 'docker-compose.yml:docker-compose.https.yml' $false
}

foreach ($required in 'POSTGRES_PASSWORD', 'SECRET_KEY', 'APP_ENCRYPTION_KEY') {
  if ((Get-EnvValue $required) -eq '') { Fail "$required está vazio no .env. Preencha (veja os comentários do arquivo) e rode de novo." }
}

if ($generated) {
  Say 'Senhas geradas em .env.'
  Write-Host ''
  Write-Host '    IMPORTANTE: faça agora uma cópia da APP_ENCRYPTION_KEY FORA deste servidor'
  Write-Host '    (cofre de senhas). Sem ela, senhas e tokens de canais gravados no banco não'
  Write-Host '    podem ser lidos depois de uma restauração. Ela está no arquivo .env.'
  Write-Host ''
}

if ($EnvOnly) { Say 'Pronto: .env gerado. Suba com: docker compose up -d --build'; exit 0 }

# --- 3. Subir e esperar ---------------------------------------------------------------------------
Say 'Construindo e iniciando os serviços (a primeira vez demora alguns minutos)...'
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail 'docker compose falhou. Veja a mensagem acima.' }

$httpPort = Get-EnvValue 'HTTP_PORT'
if ($httpPort -eq '') { $httpPort = '80' }
$url = "http://localhost:$httpPort"
$curlOpts = @('-fsS')
if ((Get-EnvValue 'COMPOSE_FILE') -like '*https*') { $url = "https://localhost:$(Get-EnvValue 'HTTPS_PORT')"; $curlOpts = @('-fsSk') }
Say "Aguardando o sistema responder em $url ..."
for ($i = 0; $i -lt 90; $i++) {
  curl.exe @curlOpts --max-time 5 -o NUL "$url/api/v1/health" 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Say 'Sistema no ar!'
    Write-Host "    Abra $url e siga o assistente: ele cria o administrador e deixa você escolher"
    Write-Host '    entre uma BASE LIMPA ou um MODELO DE EXEMPLO com dados fictícios.'
    if ($curlOpts[0] -eq '-fsSk') {
      Write-Host '    HTTPS autoassinado: o navegador avisa que o certificado não é confiável. Para o pop-up do navegador'
      Write-Host '    funcionar, importe certs\server.crt como autoridade raiz confiável (veja docs\02, seção 7).'
    }
    Write-Host '    Para acompanhar:  docker compose ps   |   docker compose logs -f backend'
    exit 0
  }
  Start-Sleep -Seconds 2
}
Fail 'O sistema não respondeu em 3 minutos. Veja: docker compose ps; docker compose logs --tail=80 backend'
