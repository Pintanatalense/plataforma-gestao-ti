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

.PARAMETER Check
  Só verifica os requisitos (não instala nem altera nada).

.PARAMETER Yes
  Instala sem perguntar o que faltar (Docker Desktop, via winget).

.PARAMETER DryRun
  Mostra o que seria instalado, sem executar.

.NOTES
  Plataforma de Gestão de TI — instalador Windows.
  Developed by Hedú • InfraNuvem  (HeduInfo)  https://infranuvem.com.br

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Port 8080
#>
param(
  [switch]$EnvOnly,
  [switch]$Check,
  [switch]$Yes,
  [switch]$DryRun,
  [int]$Port = 0,
  [switch]$Https,
  [string]$Hosts = '',
  [int]$HttpsPort = 0
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # acentos e o selo da marca no console
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


# --- Identidade e requisitos mínimos ----------------------------------------------------------------
$MinRamMb = 4096     # Docker Desktop (WSL2) pede 4 GB; 8 GB é o recomendado
$RecRamMb = 8192
$MinDiskGb = 10      # imagens, volumes do banco e anexos

function Show-Banner {
  Write-Host ''
  Write-Host '  Plataforma de Gestão de TI — Instalador'
  Write-Host "  Developed by Hedú • InfraNuvem • $((Get-Date).Year)  (HeduInfo)"
  Write-Host '  https://infranuvem.com.br'
  Write-Host ''
}
function Write-Ok([string]$m)      { Write-Host "  [ok]    $m" -ForegroundColor Green }
function Write-Missing([string]$m) { Write-Host "  [FALTA] $m" -ForegroundColor Red }
function Write-Note([string]$m)    { Write-Host "  [aviso] $m" -ForegroundColor Yellow }

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-PortBusy([int]$port) {
  return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Test-DockerRunning {
  docker info *> $null
  return ($LASTEXITCODE -eq 0)
}

function Confirm-Install([string]$question) {
  if ($Yes) { return $true }
  if (-not [Environment]::UserInteractive) { return $false }
  $answer = Read-Host "$question [s/N]"
  return ($answer -match '^(s|sim|y|yes)$')
}

function Start-DockerDesktop {
  $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (-not (Test-Path $exe)) { return $false }
  Say 'Abrindo o Docker Desktop e aguardando o motor iniciar (até 3 minutos)...'
  Start-Process $exe
  for ($i = 0; $i -lt 36; $i++) {
    Start-Sleep -Seconds 5
    if (Test-DockerRunning) { return $true }
  }
  return $false
}

# Verifica (e, se permitido, instala) os requisitos. Termina o script se algo essencial faltar.
function Test-Requirements {
  $blocking = $false
  Say 'Verificando os requisitos mínimos...'

  if ($PSVersionTable.PSVersion -ge [Version]'5.1') { Write-Ok "PowerShell $($PSVersionTable.PSVersion)" }
  else { Write-Missing "PowerShell $($PSVersionTable.PSVersion) (mínimo 5.1)"; $blocking = $true }

  $build = [Environment]::OSVersion.Version.Build
  if (-not [Environment]::Is64BitOperatingSystem) { Write-Missing 'Windows de 32 bits não é suportado.'; $blocking = $true }
  elseif ($build -ge 19041) { Write-Ok "Windows (build $build)" }
  else { Write-Missing "Windows build $build (mínimo 19041, o Windows 10 versão 2004, exigido pelo WSL2 do Docker Desktop)"; $blocking = $true }

  $ramMb = [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
  if ($ramMb -ge $RecRamMb) { Write-Ok "Memória: $ramMb MB" }
  elseif ($ramMb -ge $MinRamMb) { Write-Note "Memória: $ramMb MB (funciona; o recomendado é $RecRamMb MB)" }
  else { Write-Missing "Memória: $ramMb MB (mínimo $MinRamMb MB)"; $blocking = $true }

  $drive = (Get-Location).Drive.Name
  $freeGb = [int]((Get-PSDrive -Name $drive).Free / 1GB)
  if ($freeGb -ge $MinDiskGb) { Write-Ok "Disco livre em ${drive}: $freeGb GB" }
  else { Write-Missing "Disco livre em ${drive}: $freeGb GB (mínimo $MinDiskGb GB)"; $blocking = $true }

  $cs = Get-CimInstance Win32_ComputerSystem
  $virtOn = $cs.HypervisorPresent -or ((Get-CimInstance Win32_Processor | Where-Object { $_.VirtualizationFirmwareEnabled }) -ne $null)
  if ($virtOn) { Write-Ok 'Virtualização habilitada' }
  else { Write-Note 'Virtualização parece desativada na BIOS/UEFI; o Docker Desktop precisa dela (ative "Intel VT-x/AMD-V").' }

  $httpPort = if ($Port -gt 0) { $Port } elseif ((Test-Path .env) -and (Get-EnvValue 'HTTP_PORT') -ne '') { [int](Get-EnvValue 'HTTP_PORT') } else { 80 }
  $ports = @($httpPort)
  if ($Https) { $ports += $(if ($HttpsPort -gt 0) { $HttpsPort } else { 443 }) }
  $running = $false
  if (Get-Command docker -ErrorAction SilentlyContinue) { $running = [bool](docker compose ps --status running -q 2>$null) }
  foreach ($p in $ports) {
    if ((Test-PortBusy $p) -and -not $running) { Write-Missing "Porta $p já está em uso por outro programa (escolha outra com -Port ou libere a porta)."; $blocking = $true }
    else { Write-Ok "Porta $p livre" }
  }

  if (Get-Command curl.exe -ErrorAction SilentlyContinue) { Write-Ok 'curl.exe' }
  else { Write-Missing 'curl.exe (vem com o Windows 10 1803 ou superior)'; $blocking = $true }

  $hasDocker = [bool](Get-Command docker -ErrorAction SilentlyContinue)
  $dockerReady = $false
  if ($hasDocker) {
    Write-Ok 'docker instalado'
    docker compose version *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'docker compose v2' } else { Write-Missing 'docker compose v2' }
    if (Test-DockerRunning) { Write-Ok 'docker em execução'; $dockerReady = $true } else { Write-Missing 'docker instalado, mas não está em execução' }
  } else { Write-Missing 'Docker Desktop' }

  if ($Check) {
    Write-Host ''
    if (-not $blocking -and $dockerReady) { Say 'Tudo certo: o computador atende aos requisitos.'; exit 0 }
    Fail 'Há requisitos faltando (veja [FALTA] acima). Rode sem -Check para instalar o que for possível.'
  }
  if ($blocking) { Fail 'Requisitos de hardware, sistema ou porta não atendidos (acima). Corrija e rode de novo.' }
  if ($dockerReady) { return }

  # Instalação / inicialização do Docker Desktop
  if ($hasDocker) {
    if ($DryRun) { Say 'Simulação: o Docker Desktop seria aberto e eu esperaria o motor iniciar.'; exit 0 }
    if (Start-DockerDesktop) { Say 'Docker em execução.'; return }
    Fail 'O Docker Desktop não ficou pronto. Abra-o manualmente, aceite os termos na primeira vez, espere aparecer "Engine running" e rode o instalador de novo.'
  }

  Write-Host ''
  Write-Host 'Vou instalar o Docker Desktop (Docker Inc., pelo winget). Ele habilita o WSL2 e pode pedir para reiniciar o computador.'
  $wingetCmd = 'winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements'
  if ($DryRun) { Write-Host "  (dry-run) $wingetCmd"; Say 'Simulação concluída: nada foi instalado.'; exit 0 }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail 'winget não encontrado. Instale o Docker Desktop manualmente: https://docs.docker.com/desktop/setup/install/windows-install/ e rode este instalador de novo.'
  }
  if (-not (Test-Admin)) { Fail 'Para instalar o Docker Desktop, abra o PowerShell como Administrador e rode o instalador de novo.' }
  if (-not (Confirm-Install 'Posso continuar?')) { Fail 'Instalação cancelada. Instale o Docker Desktop e rode de novo (ou use -Yes).' }
  winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) { Fail 'A instalação do Docker Desktop falhou. Veja a mensagem acima.' }
  Write-Host ''
  Say 'Docker Desktop instalado.'
  Write-Host '    Próximos passos: reinicie o computador se o instalador pedir, abra o Docker Desktop,'
  Write-Host '    aceite os termos de uso (só na primeira vez), espere aparecer "Engine running"'
  Write-Host '    e rode este instalador de novo.'
  exit 0
}

# --- 1. Pré-requisitos ----------------------------------------------------------------------------
Show-Banner
if (-not $EnvOnly) {
  Test-Requirements
  docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 não encontrado ('docker compose version' falhou)." }
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
