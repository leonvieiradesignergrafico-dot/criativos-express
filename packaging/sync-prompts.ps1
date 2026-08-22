# Sincroniza app\prompts\ (a fonte) pras copias empacotadas dos prompts, sem rebuild completo.
# Rode depois de editar qualquer arquivo em app\prompts\ (copywriter.md, roteirista_*.md, etc.)
# se voce usa o app pelo atalho instalado (nao so por `python server.py`/`python desktop.py`).
#
# Uso (a partir da RAIZ do projeto "Criativos Express"):
#     powershell -ExecutionPolicy Bypass -File packaging\sync-prompts.ps1
#
# So copia .md (dado, nao muda nenhum .exe/.dll). Reversivel: os prompts.json e outputs
# gerados por produto nao sao tocados.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "app\prompts"

if (-not (Test-Path $src)) {
    throw "Fonte nao encontrada: $src (rode este script a partir de packaging\ dentro do projeto Criativos Express)."
}

# Alvos conhecidos: a copia empacotada dentro da propria pasta do projeto (build local, clicavel)
# e a instalacao real via Setup em %LOCALAPPDATA%. Ambos sao opcionais -- so sincroniza o que existir.
$targets = @(
    (Join-Path $root "Ads Express (app)\_internal\app\prompts"),
    (Join-Path $env:LOCALAPPDATA "Programs\Ads Express\_internal\app\prompts")
)

$synced = 0
foreach ($target in $targets) {
    if (-not (Test-Path $target)) {
        Write-Host "-- Alvo nao existe, pulando: $target" -ForegroundColor DarkGray
        continue
    }
    Write-Host "==> Sincronizando prompts em: $target" -ForegroundColor Cyan
    Copy-Item -Path (Join-Path $src "*.md") -Destination $target -Force
    $srcVideo = Join-Path $src "video_formatos"
    $targetVideo = Join-Path $target "video_formatos"
    if (-not (Test-Path $targetVideo)) { New-Item -ItemType Directory -Path $targetVideo -Force | Out-Null }
    Copy-Item -Path (Join-Path $srcVideo "*.md") -Destination $targetVideo -Force
    $synced++
}

if ($synced -eq 0) {
    Write-Host "Nenhum alvo empacotado encontrado nesta maquina -- nada a sincronizar (voce provavelmente so roda do codigo-fonte)." -ForegroundColor Yellow
} else {
    Write-Host "==> Pronto. $synced copia(s) sincronizada(s)." -ForegroundColor Green
}
