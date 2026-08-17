# Build completo do Ads Express (app + assistente de Setup).
# Uso (a partir da RAIZ do projeto):
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Requer: Python 3.13 com pyinstaller instalado (pip install pyinstaller).
# Saída:  dist\Ads Express\           (o app, sem console)
#         dist\Setup Ads Express\     (o assistente de setup, com console)
# O instalador (installer_windows.iss) empacota as duas pastas juntas.

$ErrorActionPreference = "Stop"
$py = "C:\Users\Leon\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python).Source }

Write-Host "==> Limpando build anterior..." -ForegroundColor Cyan
Remove-Item -Recurse -Force build, "dist\Ads Express", "dist\Setup Ads Express" -ErrorAction SilentlyContinue

Write-Host "==> Conferindo template de config embutido..." -ForegroundColor Cyan
# O template distribuido e versionado em packaging\default_config\config.toml (limpo,
# sem dados pessoais). NAO copiar config\config.toml aqui: isso vazaria a config do dev
# (veo_project, voice_id) pra todo usuario. Para atualizar o template, edite o arquivo
# versionado a mao.
if (-not (Test-Path packaging\default_config\config.toml)) {
    throw "Template ausente: packaging\default_config\config.toml (deveria estar versionado no git)."
}

Write-Host "==> Build do app (Ads Express)..." -ForegroundColor Cyan
& $py -m PyInstaller packaging\AdsExpress.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "Falha no build do app." }

Write-Host "==> Build do assistente (Setup Ads Express)..." -ForegroundColor Cyan
& $py -m PyInstaller packaging\Setup.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "Falha no build do Setup." }

Write-Host "==> Pronto." -ForegroundColor Green
Write-Host "    dist\Ads Express\Ads Express.exe"
Write-Host "    dist\Setup Ads Express\Setup Ads Express.exe"
